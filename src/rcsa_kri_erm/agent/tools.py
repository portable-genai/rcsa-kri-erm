"""Tool functions an agent runtime calls: thin, side-effect-honest wrappers on the services.

Design rules, in the order they matter:

* **No business logic here.** The domain service decides HOW; the model only decides WHICH tool
  to call. A rule that lives in a tool wrapper is a rule the CLI and the API do not have.
* **Rule R8 applies on this path too.** An escalated result is ROUTED from inside the tool, in
  the same call that produced it. An agent surface that only returned the flag would be a third
  place an escalation can quietly stop, after the API and the CLI.
* **Import-safe without a runtime.** ``google.adk`` is imported lazily inside
  :func:`build_function_tools`, so these callables are importable, testable and runnable with
  no ADK and no cloud SDK installed.
* **Typed and documented.** A runtime derives each tool's name, description and JSON parameter
  schema from the signature and the docstring, so both are part of the contract.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from hex_service_kit.serialization import to_jsonable
from pii_kit import redact

from ..config import Container, Settings, build_container
from ..domain.erm_models import ControlEffectiveness, RcsaAssessment, RiskRating
from ..domain.erm_service import ErmService
from ..domain.errors import TenantAccessDeniedError
from ..domain.models import TriageInput
from ..domain.pii import PII_PATTERNS
from ..domain.triage_service import TriageService

if TYPE_CHECKING:  # pragma: no cover - typing only, never imported at runtime
    from google.adk.tools import FunctionTool

#: The identity a tool call is attributed to when the runtime propagates none. It names the
#: SERVICE, not a person, so an unattributed action is never mistaken for a human's. This one
#: default is deliberate and is NOT the tenant defect below: it widens no read and grants no
#: authority, it only refuses to let an unattributed act wear a human's name.
DEFAULT_ACTOR = "rcsa-kri-erm-agent"


def _container(settings: Settings | None) -> Container:
    return build_container(settings)


def _require_tenant(tenant: str, *, tool: str) -> str:
    """A tool acts on the partition the CALLER names, or on none at all.

    A tenant-scoped tool carrying a default is the defect this file exists to catch:
    ``propose_control_merges`` declared ``tenant: str = "demo-bank"`` and ``assess_rcsa_control``
    did ``tenant or "demo-bank"``, so a runtime that propagated no tenant silently read and acted
    on the seeded bank's partition, while the API derives the same value from the verified
    principal and can never do that. The parameter is right (the runtime fills it from the resolved
    identity); the default was the defect, and the fix is to refuse rather than to choose.
    """
    if not tenant:
        raise TenantAccessDeniedError(
            f"{tool} was called with no tenant: this surface will not choose a partition for a "
            "caller who named none. Propagate the verified principal's tenant."
        )
    return tenant


def _erm_service(container: Container) -> ErmService:
    """Assemble the ERM orchestration service from the container's bound ports."""
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


def _redacted(node: Any) -> Any:
    """Mask personal data in every string of a tool result, however deeply it is nested.

    A tool result is not an API response. The API returns to the authenticated caller the text
    that caller just submitted; a TOOL result goes into a model's context, and P-04 says
    minimise the data that reaches a model. The evidence snippet a caller may legitimately read
    back is therefore masked here, on the way to the agent, using the same pattern pack the
    audit write masks with. Walking the whole structure rather than three named fields means a
    future field cannot arrive unredacted just because nobody remembered to add it.
    """
    if isinstance(node, str):
        return redact(node, PII_PATTERNS)
    if isinstance(node, dict):
        return {key: _redacted(value) for key, value in node.items()}
    if isinstance(node, list):
        return [_redacted(value) for value in node]
    return node


def triage_case(
    subject: str,
    text: str,
    tenant: str,
    actor: str = DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Triage one case and route it for human review when it escalates.

    Scores the case into a deterministic severity band, writes an already-redacted audit event,
    and, when the band escalates, submits the result to the human-review console (rule R8).

    Args:
      subject: The party or case the description is about.
      text: The free-text case description.
      tenant: The tenant partition this call acts in. REQUIRED, and never defaulted: it is the
        partition asserted on the outbound review, and a review filed under a partition the
        caller did not name is mis-attributed at a shared console.
      actor: The verified identity this call is attributed to.

    Returns:
      A JSON-safe result dict with every string masked for personal data (P-04: a tool result
      goes into a model's context), plus ``review_ref``: where the escalation WENT. It is empty
      only when the result did not escalate, so a caller can tell a routed escalation from a
      flag nobody read.

    Raises:
      TenantAccessDeniedError: no tenant was named, so no partition may be chosen for the caller.
    """
    tenant = _require_tenant(tenant, tool="triage_case")
    container = _container(settings)
    case = TriageInput(subject=subject, text=text)
    result = TriageService(container.audit, tracer=container.tracer).triage(case, actor=actor)
    review_ref = ""
    if result.requires_human_review:
        review_ref = container.review_router.route(result, maker=actor, tenant=tenant)
    payload = _redacted(to_jsonable(result))
    if not isinstance(payload, dict):  # pragma: no cover - dataclasses serialise to objects
        raise TypeError("a triage result must serialise to a JSON object")
    # Attached after the redaction pass: it is a routing reference, not narrative text, and
    # masking an identifier would break the caller's ability to look the review up.
    payload["review_ref"] = review_ref
    return payload


def verify_audit_trail(settings: Settings | None = None) -> dict[str, Any]:
    """Verify the audit trail's hash chain and its external head anchor.

    Returns:
      A dict with ``ok``, the record counts and a ``detail`` string. ``ok`` is false for an
      edited, deleted or reordered record, and, when an external anchor is configured, for a
      truncated tail as well. Without an anchor a truncation cannot be detected, and the detail
      says so rather than implying a stronger guarantee than the store provides.
    """
    resolved = settings or Settings.load()
    audit = _container(resolved).audit
    verify = getattr(audit, "verify", None)
    if verify is None:
        raise NotImplementedError(
            f"the {resolved.profile} audit adapter does not expose chain verification; a "
            "managed WORM sink is verified by its own retention policy, not from here"
        )
    report = verify()
    return {
        "ok": report.ok,
        "entries": report.entries,
        "chained": report.chained,
        "legacy": report.legacy,
        "first_bad_seq": report.first_bad_seq,
        "detail": report.detail,
        "anchored": bool(resolved.audit_anchor_path),
    }


def assess_rcsa_control(
    control_id: str,
    impact: int,
    likelihood: int,
    tenant: str,
    effectiveness: str = "partial",
    actor: str = DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Score one RCSA control's residual risk and route it for review when it is consequential.

    The residual band and score are computed by the deterministic engine over the ACCEPTED
    rating; the model only narrates. When the worst residual band reaches the review floor the
    result is routed to the human-review console in this same call (rule R8).

    Args:
      control_id: The obligations-control-mapping control id the assessment is keyed on.
      impact: Inherent impact on the 1..5 scale.
      likelihood: Inherent likelihood on the 1..5 scale.
      tenant: The tenant partition the assessment is filed under. REQUIRED, and never defaulted:
        falling back to ``"demo-bank"`` would let an unattributed call assess and route against
        the seeded bank's partition.
      effectiveness: Control effectiveness: ``ineffective``, ``partial`` or ``effective``.
      actor: The verified identity this call is attributed to.

    Returns:
      A JSON-safe dict (strings masked for personal data) with the residual band, the engine
      note and ``review_ref``: empty unless the assessment escalated.

    Raises:
      TenantAccessDeniedError: no tenant was named, so no partition may be chosen for the caller.
    """
    tenant = _require_tenant(tenant, tool="assess_rcsa_control")
    container = _container(settings)
    rating = RiskRating(
        control_id=control_id,
        impact=impact,
        likelihood=likelihood,
        effectiveness=ControlEffectiveness(effectiveness),
    )
    assessment = RcsaAssessment(control_id=control_id, tenant=tenant, accepted_ratings=(rating,))
    outcome = _erm_service(container).assess_rcsa(assessment, actor=actor)
    payload = _redacted(
        {
            "control_id": outcome.control_id,
            "worst_band": outcome.worst_band.value,
            "residual_score": max((r.residual_score for r in outcome.residuals), default=0),
            "note": outcome.note,
            "requires_human_review": outcome.requires_human_review,
        }
    )
    if not isinstance(payload, dict):  # pragma: no cover - dicts serialise to objects
        raise TypeError("an RCSA outcome must serialise to a JSON object")
    payload["review_ref"] = outcome.review_ref
    return payload


def propose_control_merges(
    tenant: str,
    actor: str = DEFAULT_ACTOR,
    settings: Settings | None = None,
) -> dict[str, Any]:
    """Propose de-duplication merges over the control library and route each to review.

    The library is READ from obligations-control-mapping (this repo keeps no catalog); the
    embeddings come from the
    bound embedder; the candidate pairs are pure cosine arithmetic. A merge collapses two risk
    lines, so every proposal is routed to the human-review console (rule R8), never auto-applied.

    Args:
      tenant: The tenant whose control library to read. REQUIRED, and never defaulted: this used
        to default to ``"demo-bank"``, so a caller who named no tenant read the seeded bank's
        whole control library and had merge proposals routed against it.
      actor: The verified identity this call is attributed to.

    Returns:
      A JSON-safe dict with the proposed pairs and their ``review_refs``.

    Raises:
      TenantAccessDeniedError: no tenant was named, or the bound library does not serve it.
    """
    tenant = _require_tenant(tenant, tool="propose_control_merges")
    container = _container(settings)
    outcome = _erm_service(container).propose_control_merges(tenant, actor=actor)
    payload = _redacted(
        {
            "candidates": [
                {"left": c.left_id, "right": c.right_id, "similarity": c.similarity}
                for c in outcome.candidates
            ],
            "review_refs": list(outcome.review_refs),
        }
    )
    if not isinstance(payload, dict):  # pragma: no cover - dicts serialise to objects
        raise TypeError("a merge outcome must serialise to a JSON object")
    return payload


#: The tool table. The agent card advertises exactly these, by function name.
TOOL_FUNCTIONS = (triage_case, verify_audit_trail, assess_rcsa_control, propose_control_merges)


def build_function_tools() -> list[FunctionTool]:
    """Wrap each callable as a runtime FunctionTool (the only ADK-dependent code path).

    The import is deliberately here rather than at module scope: without it this module, the
    card and every tool would need an agent runtime installed to be imported at all, and the
    offline gate installs none.
    """
    # No ignore comment: the missing-import error for this module is already reported (and
    # ignored) at the TYPE_CHECKING import above, and a second one would be flagged as unused.
    from google.adk.tools import FunctionTool

    return [FunctionTool(func=function) for function in TOOL_FUNCTIONS]
