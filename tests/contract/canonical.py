"""ONE canonical request per port, shared by the structural and behavioural contract suites.

Parity means the same request through every implementation, so the request needs a single home.
Retyping it per suite is how two "parity" tests end up asserting different things.

Each :class:`PortCase` answers three questions about one port:

* ``invoke``   : what a single canonical call to this port looks like;
* ``answered`` : what it means for the OFFLINE family to have actually answered (a port that
  returns ``None`` and records nothing has not answered, it has merely not raised);
* ``managed_refusal`` : what the MANAGED family must do when called with no cloud reachable.
  Never a silent success: either it refuses because it is unconfigured, or its lazy SDK import
  fails. Both are honest; returning as if the work happened is not.

Adding a port means adding a case here. ``test_port_parity.py`` fails the build if this table
and the port map ever disagree, so the touch list in ``CONTRIBUTING.md`` is enforced rather than
merely written down.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from agent_eval_kit import EvalReport
from hex_service_kit.identity import IdentityError, Principal, RequestContext
from hex_service_kit.observability import TokenUsage

from rcsa_kri_erm.domain.kernel import (
    AuditEvent,
    Citation,
    Decision,
    Severity,
)
from rcsa_kri_erm.domain.models import (
    TriageResult,
)
from rcsa_kri_erm.ports.generation import GenerationRequest

from tests.fixtures import sample_cases

#: The demo bank's tenant, the owning partition of the seeded control library, KRI feed and themes.
CANONICAL_TENANT = "demo-bank"

#: The audit record every audit-port implementation is handed. Already redacted, as the port
#: requires: a raw identifier must never reach a WORM record.
CANONICAL_EVENT = AuditEvent(
    action="triage",
    actor=sample_cases.ACTOR,
    decision=Decision.ESCALATED,
    severity=Severity.HIGH,
    redacted_summary="Acme Holdings (FICTIONAL): triaged high",
    citations=(Citation(source_id="case:acme", title="Case description", snippet="urgent"),),
)

#: The escalated result every review-router implementation is handed (rule R8's payload).
CANONICAL_RESULT = TriageResult(
    subject=sample_cases.ESCALATING_CASE.subject,
    severity=Severity.HIGH,
    decision=Decision.ESCALATED,
    summary=f"{sample_cases.ESCALATING_CASE.subject}: triaged high",
    requires_human_review=True,
    citations=(Citation(source_id="case:acme", title="Case description", snippet="urgent"),),
)

#: The inbound transport context every identity implementation is handed.
CANONICAL_CONTEXT = RequestContext(headers={"x-dev-persona": "auditor"})


@dataclass(frozen=True, slots=True)
class PortCase:
    """One port's canonical call plus the two verdicts the parity suites need."""

    invoke: Callable[[Any], Any]
    answered: Callable[[Any, Any], bool]
    managed_refusal: tuple[type[BaseException], ...]
    detail: str


def _audit_invoke(adapter: Any) -> Any:
    return adapter.record(CANONICAL_EVENT)


def _audit_answered(adapter: Any, _result: Any) -> bool:
    stored = adapter.log.read_all()
    return bool(stored) and stored[-1]["actor"] == sample_cases.ACTOR and adapter.verify().ok


def _identity_invoke(adapter: Any) -> Any:
    return adapter.resolve(CANONICAL_CONTEXT)


def _identity_answered(_adapter: Any, result: Any) -> bool:
    return isinstance(result, Principal) and bool(result.actor)


def _review_invoke(adapter: Any) -> Any:
    return adapter.route(CANONICAL_RESULT, maker=sample_cases.ACTOR, tenant=sample_cases.TENANT)


def _review_answered(adapter: Any, result: Any) -> bool:
    return bool(result) and len(adapter.outbox.pending()) == 1


#: The narration request every generation implementation is handed. The facts are the engine-owned
#: figures the offline narrator restates, so its answer is grounded by construction.
CANONICAL_GENERATION = GenerationRequest(
    system="restate the engine figures",
    prompt="Facts: residual_score=15, band=red.",
    facts=(("residual_score", "15"), ("band", "red")),
)


def _generation_invoke(adapter: Any) -> Any:
    return adapter.generate(CANONICAL_GENERATION)


def _generation_answered(_adapter: Any, result: Any) -> bool:
    text = getattr(result, "text", "")
    return bool(text) and '"note"' in text


def _control_library_invoke(adapter: Any) -> Any:
    return adapter.list_controls(CANONICAL_TENANT)


def _control_library_answered(_adapter: Any, result: Any) -> bool:
    return bool(result) and all(getattr(c, "control_id", "") for c in result)


def _embeddings_invoke(adapter: Any) -> Any:
    return adapter.embed({"a": "quarterly access recertification", "b": "access recertified"})


def _embeddings_answered(_adapter: Any, result: Any) -> bool:
    if not isinstance(result, dict) or set(result) != {"a", "b"}:
        return False
    lengths = {len(vec) for vec in result.values()}
    return len(lengths) == 1 and next(iter(lengths)) > 0


def _metric_feed_invoke(adapter: Any) -> Any:
    return adapter.fetch(("failed_login_rate",), "2026-12-31")


def _metric_feed_answered(_adapter: Any, result: Any) -> bool:
    return bool(result) and all(getattr(p, "metric_key", "") == "failed_login_rate" for p in result)


def _theme_feed_invoke(adapter: Any) -> Any:
    return adapter.themes(CANONICAL_TENANT)


def _theme_feed_answered(_adapter: Any, result: Any) -> bool:
    return bool(result) and all(getattr(t, "theme_id", "") for t in result)


def _tracer_invoke(adapter: Any) -> Any:
    with adapter.span("canonical.unit", action="canonical"):
        adapter.record_token_usage(TokenUsage(input_tokens=7, output_tokens=2), "canonical-model")
    return True


def _tracer_answered(adapter: Any, result: Any) -> bool:
    return bool(result)


def _evaluation_invoke(adapter: Any) -> Any:
    return adapter.evaluate("eval/datasets/canonical.jsonl")


def _evaluation_answered(adapter: Any, result: Any) -> bool:
    return isinstance(result, EvalReport) and result.dataset.endswith("canonical.jsonl")


CANONICAL_CALLS: dict[str, PortCase] = {
    "audit": PortCase(
        invoke=_audit_invoke,
        answered=_audit_answered,
        # The lazy `google.cloud` import is the first thing the managed sink does.
        managed_refusal=(ImportError,),
        detail="write one already-redacted WORM record",
    ),
    "identity": PortCase(
        invoke=_identity_invoke,
        answered=_identity_answered,
        # No IAP assertion header offline, so the managed adapter refuses before importing.
        managed_refusal=(IdentityError,),
        detail="resolve a verified principal from transport context",
    ),
    "review_router": PortCase(
        invoke=_review_invoke,
        answered=_review_answered,
        # Rule R8: with no console configured the managed router must refuse, not swallow.
        managed_refusal=(RuntimeError,),
        detail="route one escalated result to human review",
    ),
    "generation": PortCase(
        invoke=_generation_invoke,
        answered=_generation_answered,
        # The managed narrator lazily imports the Gemini SDK, absent offline and in CI.
        managed_refusal=(ImportError,),
        detail="narrate a grounded note from the engine facts",
    ),
    "control_library": PortCase(
        invoke=_control_library_invoke,
        answered=_control_library_answered,
        # The managed read lazily imports google.auth for its S2S call, absent offline.
        managed_refusal=(ImportError,),
        detail="read Rgc7's control library for a tenant",
    ),
    "embeddings": PortCase(
        invoke=_embeddings_invoke,
        answered=_embeddings_answered,
        # The managed embedder lazily imports the Vertex SDK, absent offline.
        managed_refusal=(ImportError,),
        detail="embed control text into equal-length vectors",
    ),
    "metric_feed": PortCase(
        invoke=_metric_feed_invoke,
        answered=_metric_feed_answered,
        # The managed feed lazily imports the BigQuery SDK, absent offline.
        managed_refusal=(ImportError,),
        detail="read observed metric points bounded by as_of",
    ),
    "theme_feed": PortCase(
        invoke=_theme_feed_invoke,
        answered=_theme_feed_answered,
        # The managed read lazily imports google.auth for its S2S call, absent offline.
        managed_refusal=(ImportError,),
        detail="read Aud3's themes for a tenant",
    ),
    "tracer": PortCase(
        invoke=_tracer_invoke,
        answered=_tracer_answered,
        # NOTHING. Tracing is not essential to correctness, so the managed adapter must not refuse
        # offline either: with no SDK it degrades to a no-op and the traced body still runs. An
        # adapter that raised here would take a request down over a diagnostic.
        managed_refusal=(),
        detail="open one span and report the cost of a model call",
    ),
    "evaluation": PortCase(
        invoke=_evaluation_invoke,
        answered=_evaluation_answered,
        # The managed gate reaches Hrz4 over HTTP, which is unreachable offline.
        managed_refusal=(Exception,),
        detail="score one golden dataset through the promotion authority",
    ),
}
