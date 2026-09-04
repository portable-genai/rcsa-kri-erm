"""The ERM orchestration service: R8 routing on consequential outcomes, audit hygiene.

Proves the seam rules the plan requires: every consequential outcome (an amber/red RCSA line, a
merge proposal, a KRI breach, a theme reopen) is ROUTED to human-review-console in the same call
that produced it, a green RCSA line is not, and no raw identifier survives into an audit record.
"""

from __future__ import annotations

from pii_kit import pack_leak

from rcsa_kri_erm.adapters.local.seed import SEED_KRIS, SEED_TENANT
from rcsa_kri_erm.config import Settings, build_container
from rcsa_kri_erm.domain.erm_models import (
    ControlEffectiveness,
    RagBand,
    RcsaAssessment,
    RiskRating,
)
from rcsa_kri_erm.domain.erm_service import ErmService
from rcsa_kri_erm.domain.pii import PII_PATTERNS

_AS_OF = "2026-08-31"


def _service(container) -> ErmService:  # type: ignore[no-untyped-def]
    return ErmService(
        audit=container.audit,
        review_router=container.review_router,
        generation=container.generation,
        control_library=container.control_library,
        embeddings=container.embeddings,
        metric_feed=container.metric_feed,
        theme_feed=container.theme_feed,
        tracer=container.tracer,
    )


def _fresh() -> tuple[ErmService, object]:
    container = build_container(Settings(profile="local", audit_path=":memory:"))
    return _service(container), container


def test_red_rcsa_line_routes_and_green_does_not() -> None:
    service, container = _fresh()

    red = RcsaAssessment(
        control_id="CTL-CHG-04",
        tenant=SEED_TENANT,
        accepted_ratings=(RiskRating("CTL-CHG-04", 5, 5, ControlEffectiveness.INEFFECTIVE),),
    )
    outcome = service.assess_rcsa(red, actor="risk-analyst")
    assert outcome.worst_band is RagBand.RED
    assert outcome.requires_human_review and outcome.review_ref
    assert len(container.review_router.outbox.pending()) == 1

    green = RcsaAssessment(
        control_id="CTL-OK",
        tenant=SEED_TENANT,
        accepted_ratings=(RiskRating("CTL-OK", 1, 2, ControlEffectiveness.EFFECTIVE),),
    )
    green_outcome = service.assess_rcsa(green, actor="risk-analyst")
    assert green_outcome.worst_band is RagBand.GREEN
    assert not green_outcome.requires_human_review and not green_outcome.review_ref
    assert len(container.review_router.outbox.pending()) == 1  # unchanged: green never routes


def test_every_result_carries_a_citation() -> None:
    service, _ = _fresh()
    outcome = service.assess_rcsa(
        RcsaAssessment(
            "CTL-CHG-04",
            SEED_TENANT,
            accepted_ratings=(RiskRating("CTL-CHG-04", 3, 3, ControlEffectiveness.PARTIAL),),
        ),
        actor="risk-analyst",
    )
    assert outcome.citations and all(c.source_id for c in outcome.citations)


def test_kri_breach_routes_to_review() -> None:
    service, container = _fresh()
    outcome = service.evaluate_kris(
        SEED_KRIS, as_of=_AS_OF, actor="risk-analyst", tenant=SEED_TENANT
    )
    assert outcome.rollup is RagBand.RED
    assert outcome.breaches, "the seeded login KRI must breach"
    assert len(outcome.review_refs) == len(outcome.breaches)
    assert len(container.review_router.outbox.pending()) == len(outcome.breaches)


def test_theme_reopen_routes() -> None:
    service, container = _fresh()
    assessments = (
        RcsaAssessment("CTL-ACCESS-01", SEED_TENANT),
        RcsaAssessment("CTL-DR-02", SEED_TENANT),
    )
    outcome = service.reopen_from_themes(assessments, SEED_TENANT, actor="risk-analyst")
    reopened = [d for d in outcome.decisions if d.reopen]
    assert [d.control_id for d in reopened] == ["CTL-ACCESS-01"]
    assert len(outcome.review_refs) == 1
    assert len(container.review_router.outbox.pending()) == 1


def test_no_pii_survives_into_the_audit_record() -> None:
    service, container = _fresh()
    service.evaluate_kris(SEED_KRIS, as_of=_AS_OF, actor="risk-analyst", tenant=SEED_TENANT)
    service.propose_control_merges(SEED_TENANT, actor="risk-analyst")
    records = [str(e.get("redacted_summary", "")) for e in container.audit.log.read_all()]
    assert records, "the run must have written audit records"
    assert not any(pack_leak(text, PII_PATTERNS) for text in records)


def test_merge_proposal_routes() -> None:
    service, container = _fresh()
    outcome = service.propose_control_merges(SEED_TENANT, actor="risk-analyst")
    assert outcome.candidates, "the seeded near-duplicate access controls must propose a merge"
    assert len(outcome.review_refs) == len(outcome.candidates)
    assert len(container.review_router.outbox.pending()) == len(outcome.candidates)
