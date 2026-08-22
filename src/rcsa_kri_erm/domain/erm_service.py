"""The ERM orchestration service: engines + narration + redact-before-audit + R8 routing.

This is the seam where the four deterministic engines (``rcsa``, ``kri``, ``dedup``, ``themes``)
meet the ports. The engines own every number; this service only sequences them, narrates the
result through the model (schema-validated, discarded on failure), writes an already-redacted
audit record, and ROUTES every consequential outcome to Hrz7 in the same call that produced it
(rule R8). It never decides a band or a score itself.

Consequential outcomes, each routed the moment it is produced:

* an RCSA assessment whose worst residual band reaches the review floor;
* every proposed control merge (a merge collapses two risk lines, so a human decides);
* every KRI breach;
* every theme-driven reopen of a signed-off assessment.

The ports arrive individually rather than as a container so the domain never imports the wiring
layer, exactly as ``triage_service`` takes only its audit port.
"""

from __future__ import annotations

from dataclasses import dataclass

from pii_kit import redact

from ..ports.audit import AuditSinkPort
from ..ports.control_library import ControlLibraryPort
from ..ports.embeddings import EmbeddingsPort
from ..ports.generation import GenerationPort
from ..ports.metric_feed import MetricFeedPort
from ..ports.observability import ObservabilityTracerPort
from ..ports.review_router import ReviewRouterPort
from ..ports.theme_feed import ThemeFeedPort
from .dedup import propose_merges
from .erm_models import (
    Breach,
    KriDefinition,
    KriEvaluation,
    MergeCandidate,
    RagBand,
    RcsaAssessment,
    ReopenDecision,
    ResidualRisk,
)
from .erm_narration import NarrationService
from .kernel import AuditEvent, Citation, Decision, Severity, utcnow
from .kri import KriPolicy, breach_from_evaluation, evaluate, rollup_band
from .models import TriageResult
from .pii import PII_PATTERNS
from .rcsa import ResidualRiskPolicy, residual_for_assessment, worst_band
from .themes import ThemeTriggerPolicy, reopen_decisions

__all__ = [
    "ErmService",
    "KriOutcome",
    "MergeOutcome",
    "RcsaOutcome",
    "ReopenOutcome",
    "band_to_severity",
]

#: RagBand -> Severity for the review envelope. RED risk is HIGH; a KRI breach at RED is CRITICAL
#: (dual control), handled in :meth:`ErmService.evaluate_kris`.
_BAND_SEVERITY: dict[str, Severity] = {
    RagBand.RED.value: Severity.HIGH,
    RagBand.AMBER.value: Severity.MEDIUM,
    RagBand.GREEN.value: Severity.LOW,
}


def band_to_severity(band: RagBand) -> Severity:
    """Map a RAG band onto the kernel severity used by the review envelope."""
    return _BAND_SEVERITY.get(band.value, Severity.LOW)


@dataclass(frozen=True, slots=True)
class RcsaOutcome:
    """The result of assessing one RCSA line."""

    control_id: str
    residuals: tuple[ResidualRisk, ...]
    worst_band: RagBand
    note: str
    requires_human_review: bool
    review_ref: str
    citations: tuple[Citation, ...]


@dataclass(frozen=True, slots=True)
class MergeOutcome:
    """The result of proposing control merges over a library."""

    candidates: tuple[MergeCandidate, ...]
    review_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class KriOutcome:
    """The result of evaluating adopted KRIs against the feed."""

    evaluations: tuple[KriEvaluation, ...]
    rollup: RagBand
    breaches: tuple[Breach, ...]
    breach_notes: tuple[str, ...]
    review_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ReopenOutcome:
    """The result of deciding theme-driven reopens over a set of assessments."""

    decisions: tuple[ReopenDecision, ...]
    review_refs: tuple[str, ...]


#: One span per RCSA assessment, and one per merge-proposal sweep. Leaf spans on the two
#: entry points the agent tools expose. Structural attributes only: see each method.
_ASSESS_RCSA_SPAN = "erm.assess_rcsa"
_PROPOSE_MERGES_SPAN = "erm.propose_control_merges"


class ErmService:
    """Sequence the ERM engines, narrate, audit and route consequential outcomes to Hrz7."""

    def __init__(
        self,
        *,
        audit: AuditSinkPort,
        review_router: ReviewRouterPort,
        generation: GenerationPort,
        control_library: ControlLibraryPort,
        embeddings: EmbeddingsPort,
        metric_feed: MetricFeedPort,
        theme_feed: ThemeFeedPort,
        tracer: ObservabilityTracerPort,
        residual_policy: ResidualRiskPolicy | None = None,
        kri_policy: KriPolicy | None = None,
        theme_policy: ThemeTriggerPolicy | None = None,
    ) -> None:
        self._audit = audit
        self._review = review_router
        self._control_library = control_library
        self._embeddings = embeddings
        self._metric_feed = metric_feed
        self._theme_feed = theme_feed
        # REQUIRED, and deliberately not an optional with a no-op default. A default would let a
        # new surface construct a service that emits nothing, and the deployment would look
        # traced because the exporter was bound. A surface that forgets the tracer fails to
        # construct instead, which is a failure somebody sees.
        self._tracer = tracer
        self._narrator = NarrationService(generation)
        self._residual_policy = residual_policy or ResidualRiskPolicy()
        self._kri_policy = kri_policy or KriPolicy()
        self._theme_policy = theme_policy or ThemeTriggerPolicy()

    # ------------------------------------------------------------------ #
    # Slice 2: RCSA residual risk
    # ------------------------------------------------------------------ #
    def assess_rcsa(self, assessment: RcsaAssessment, *, actor: str) -> RcsaOutcome:
        """Score the accepted ratings on one assessment, narrate, audit and route if consequential.

        Only accepted ratings score (proposed ones are inert, by construction of the engine). The
        assessment is consequential when its worst residual band reaches the policy review floor.

        The whole path runs inside one span, and its attributes are STRUCTURAL only: the
        action, the actor and the tenant. Never the control id, never a rating, never the
        narrated note. A trace backend is not the WORM audit trail: it has no redaction
        stage, a wider read audience and no retention rule written against a regulator's
        requirement, so anything content-shaped that reaches a span has left the boundary
        the redacted audit write exists to hold, and it has left it silently.
        """
        with self._tracer.span(
            _ASSESS_RCSA_SPAN, action="assess_rcsa", actor=actor, tenant=assessment.tenant
        ):
            residuals = residual_for_assessment(assessment, self._residual_policy)
            band = worst_band(residuals)
            facts = (
                ("control_id_count", str(len({r.control_id for r in residuals}))),
                ("accepted_ratings", str(len(assessment.accepted_ratings))),
                (
                    "worst_residual_score",
                    str(max((r.residual_score for r in residuals), default=0)),
                ),
                ("worst_band", band.value),
            )
            note = self._narrator.narrate(
                f"RCSA {assessment.control_id}", facts, "Summarise the residual-risk posture."
            ).text
            citations = (
                Citation(
                    source_id=f"control:{assessment.control_id}",
                    title="RCSA assessment",
                    snippet=f"worst residual band {band.value}",
                ),
            )
            escalate = self._at_or_above_review_band(band)
            review_ref = ""
            if escalate:
                review_ref = self._route(
                    subject=f"RCSA {assessment.control_id}",
                    severity=band_to_severity(band),
                    summary=note,
                    citations=citations,
                    actor=actor,
                    tenant=assessment.tenant,
                )
            self._record("rcsa_assess", actor, escalate, band_to_severity(band), note, citations)
            return RcsaOutcome(
                control_id=assessment.control_id,
                residuals=residuals,
                worst_band=band,
                note=note,
                requires_human_review=escalate,
                review_ref=review_ref,
                citations=citations,
            )

    # ------------------------------------------------------------------ #
    # Slice 1: control de-duplication
    # ------------------------------------------------------------------ #
    def propose_control_merges(self, tenant: str, *, actor: str) -> MergeOutcome:
        """Read the library, embed controls, propose merges, and route each proposal to Hrz7.

        One span for the whole sweep, with structural attributes only: the action, the actor
        and the tenant. Never a control id, a title, a description or a similarity figure.
        See :meth:`assess_rcsa` for why a trace backend must never carry content.
        """
        with self._tracer.span(
            _PROPOSE_MERGES_SPAN, action="propose_control_merges", actor=actor, tenant=tenant
        ):
            controls = self._control_library.list_controls(tenant)
            texts = {c.control_id: f"{c.title} {c.description}" for c in controls}
            vectors = self._embeddings.embed(texts)
            candidates = propose_merges(vectors)
            refs: list[str] = []
            for candidate in candidates:
                citations = (
                    Citation(
                        source_id=f"merge:{candidate.left_id}:{candidate.right_id}",
                        title="Control de-duplication proposal",
                        snippet=f"cosine {candidate.similarity}",
                    ),
                )
                summary = (
                    f"Proposed merge of {candidate.left_id} and {candidate.right_id} "
                    f"at similarity {candidate.similarity}."
                )
                refs.append(
                    self._route(
                        subject=f"merge:{candidate.left_id}:{candidate.right_id}",
                        severity=Severity.MEDIUM,
                        summary=summary,
                        citations=citations,
                        actor=actor,
                        tenant=tenant,
                    )
                )
                self._record("merge_propose", actor, True, Severity.MEDIUM, summary, citations)
            return MergeOutcome(candidates=candidates, review_refs=tuple(refs))

    # ------------------------------------------------------------------ #
    # Slice 3: KRI evaluation and breach handling
    # ------------------------------------------------------------------ #
    def evaluate_kris(
        self, definitions: tuple[KriDefinition, ...], *, as_of: str, actor: str, tenant: str = ""
    ) -> KriOutcome:
        """Evaluate adopted KRIs, roll up worst-wins, and route every breach to Hrz7."""
        metric_keys = tuple(d.metric_key for d in definitions if d.adopted)
        points = self._metric_feed.fetch(metric_keys, as_of)
        evaluations = evaluate(definitions, points, as_of)
        rollup = rollup_band(evaluations)
        by_id = {d.kri_id: d for d in definitions}

        breaches: list[Breach] = []
        notes: list[str] = []
        refs: list[str] = []
        for evaluation in evaluations:
            breach = breach_from_evaluation(by_id[evaluation.kri_id], evaluation, self._kri_policy)
            if breach is None:
                continue
            breaches.append(breach)
            facts = breach.drivers
            note = self._narrator.narrate(
                f"KRI {breach.kri_id}",
                facts,
                "Draft the breach narrative, probable cause and committee commentary.",
            ).text
            notes.append(note)
            citations = (
                Citation(
                    source_id=f"kri:{breach.kri_id}",
                    title="KRI breach",
                    snippet=f"score {breach.score} severity {breach.severity.value}",
                ),
            )
            severity = Severity.CRITICAL if breach.severity is RagBand.RED else Severity.HIGH
            refs.append(
                self._route(
                    subject=f"KRI {breach.kri_id}",
                    severity=severity,
                    summary=note,
                    citations=citations,
                    actor=actor,
                    tenant=tenant,
                )
            )
            self._record("kri_breach", actor, True, severity, note, citations)
        return KriOutcome(
            evaluations=evaluations,
            rollup=rollup,
            breaches=tuple(breaches),
            breach_notes=tuple(notes),
            review_refs=tuple(refs),
        )

    # ------------------------------------------------------------------ #
    # Slice 4: Aud3 theme consumption and reopen triggers
    # ------------------------------------------------------------------ #
    def reopen_from_themes(
        self, assessments: tuple[RcsaAssessment, ...], tenant: str, *, actor: str
    ) -> ReopenOutcome:
        """Read Aud3 themes, decide reopens deterministically, route each reopen to Hrz7."""
        themes = self._theme_feed.themes(tenant)
        decisions = reopen_decisions(assessments, themes, self._theme_policy)
        refs: list[str] = []
        for decision in decisions:
            if not decision.reopen:
                continue
            citations = (
                Citation(
                    source_id=f"theme:{decision.theme_id}",
                    title="Theme-driven reopen",
                    snippet=decision.reason,
                ),
            )
            refs.append(
                self._route(
                    subject=f"reopen:{decision.control_id}",
                    severity=Severity.HIGH,
                    summary=decision.reason,
                    citations=citations,
                    actor=actor,
                    tenant=tenant,
                )
            )
            self._record("theme_reopen", actor, True, Severity.HIGH, decision.reason, citations)
        return ReopenOutcome(decisions=decisions, review_refs=tuple(refs))

    # ------------------------------------------------------------------ #
    # Internals
    # ------------------------------------------------------------------ #
    def _at_or_above_review_band(self, band: RagBand) -> bool:
        order = (RagBand.GREEN, RagBand.AMBER, RagBand.RED)
        floor = RagBand(self._residual_policy.review_band)
        return order.index(band) >= order.index(floor)

    def _route(
        self,
        *,
        subject: str,
        severity: Severity,
        summary: str,
        citations: tuple[Citation, ...],
        actor: str,
        tenant: str,
    ) -> str:
        result = TriageResult(
            subject=subject,
            severity=severity,
            decision=Decision.ESCALATED,
            summary=summary,
            requires_human_review=True,
            citations=citations,
        )
        return self._review.route(result, maker=actor, tenant=tenant)

    def _record(
        self,
        action: str,
        actor: str,
        escalate: bool,
        severity: Severity,
        summary: str,
        citations: tuple[Citation, ...],
    ) -> None:
        self._audit.record(
            AuditEvent(
                action=action,
                actor=actor,
                decision=Decision.ESCALATED if escalate else Decision.ALLOWED,
                severity=severity,
                redacted_summary=redact(summary, PII_PATTERNS),
                citations=citations,
                timestamp=utcnow(),
            )
        )
