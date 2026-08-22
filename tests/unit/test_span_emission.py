"""Both orchestrators open ONE leaf span per entry point, and no span carries content.

A trace backend is not the WORM audit trail. It has no redaction stage, no retention policy
written against a regulator's requirement, and a far wider read audience than the audit store.
So the value of tracing these paths depends entirely on the spans carrying structural
attributes only: which action, whose, which tenant. A case subject, a control id, a rating, a
narrated note or a planted identifier reaching a span has left the boundary redaction exists
to hold, and it has left it silently.

Two orchestrators are pinned because both sit on real request paths: ``/v1/triage`` (plus the
CLI, the agent tool, the demo and the eval smoke) drives ``TriageService.triage``, and the
agent tools ``assess_rcsa_control`` and ``propose_control_merges`` drive the two surfaced
``ErmService`` entry points. Each content case plants the NRIC in the input that call site
actually receives, so the checks run against data that would actually leak.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from rcsa_kri_erm.adapters.local.seed import SEED_TENANT
from rcsa_kri_erm.config import Container, build_container
from rcsa_kri_erm.domain.erm_models import (
    ControlEffectiveness,
    RcsaAssessment,
    RiskRating,
)
from rcsa_kri_erm.domain.erm_service import ErmService, MergeOutcome, RcsaOutcome
from rcsa_kri_erm.domain.models import TriageInput
from rcsa_kri_erm.domain.triage_service import TriageService

from tests.conftest import local_settings
from tests.fixtures import sample_cases

#: The complete attribute key set each span may carry. Adding to one of these is a decision
#: about what leaves the trust boundary, so it is made here rather than at the call site.
_TRIAGE_KEYS = {"action", "actor"}
_ERM_KEYS = {"action", "actor", "tenant"}

#: A control id with the planted identifier, so a span that leaked the subject would fail on
#: this literal rather than on a subtlety.
_PII_CONTROL_ID = f"CTL-NRIC-{sample_cases.PLANTED_NRIC}"


class _RecordingTracer:
    """Captures every span name and attribute so the test can inspect what was emitted."""

    def __init__(self) -> None:
        self.spans: list[tuple[str, dict[str, str]]] = []

    @contextmanager
    def span(self, name: str, **attributes: str) -> Iterator[None]:
        self.spans.append((name, dict(attributes)))
        yield

    def record_token_usage(self, usage: object, model: str) -> None:
        return None


def _triage(case: TriageInput) -> _RecordingTracer:
    container = build_container(local_settings())
    tracer = _RecordingTracer()
    service = TriageService(container.audit, tracer=tracer)  # type: ignore[arg-type]
    service.triage(case, actor=sample_cases.ACTOR)
    return tracer


def _erm(container: Container, tracer: _RecordingTracer) -> ErmService:
    """The REAL local adapters, exactly as the agent tools wire them."""
    return ErmService(
        audit=container.audit,
        review_router=container.review_router,
        generation=container.generation,
        control_library=container.control_library,
        embeddings=container.embeddings,
        metric_feed=container.metric_feed,
        theme_feed=container.theme_feed,
        tracer=tracer,  # type: ignore[arg-type]
    )


def _assess() -> tuple[_RecordingTracer, RcsaOutcome]:
    """A red RCSA line on a control id carrying the planted NRIC, so it escalates AND leaks."""
    container = build_container(local_settings())
    tracer = _RecordingTracer()
    assessment = RcsaAssessment(
        control_id=_PII_CONTROL_ID,
        tenant=SEED_TENANT,
        accepted_ratings=(RiskRating(_PII_CONTROL_ID, 5, 5, ControlEffectiveness.INEFFECTIVE),),
    )
    outcome = _erm(container, tracer).assess_rcsa(assessment, actor=sample_cases.ACTOR)
    return tracer, outcome


def _merge() -> tuple[_RecordingTracer, MergeOutcome]:
    container = build_container(local_settings())
    tracer = _RecordingTracer()
    outcome = _erm(container, tracer).propose_control_merges(SEED_TENANT, actor=sample_cases.ACTOR)
    return tracer, outcome


def _emitted(tracer: _RecordingTracer) -> str:
    """Every attribute KEY and VALUE that was emitted, as one searchable blob."""
    parts: list[str] = []
    for name, attributes in tracer.spans:
        parts.append(name)
        parts.extend(attributes)
        parts.extend(attributes.values())
    return " ".join(parts)


# --------------------------------------------------------------------------- #
# The spans exist at all
# --------------------------------------------------------------------------- #
def test_triaging_a_case_opens_exactly_one_named_span() -> None:
    tracer = _triage(sample_cases.ROUTINE_CASE)
    assert [name for name, _ in tracer.spans] == ["erm.triage"]


def test_assessing_an_rcsa_line_opens_exactly_one_named_span() -> None:
    tracer, _ = _assess()
    assert [name for name, _ in tracer.spans] == ["erm.assess_rcsa"]


def test_a_merge_sweep_opens_exactly_one_named_span() -> None:
    tracer, _ = _merge()
    assert [name for name, _ in tracer.spans] == ["erm.propose_control_merges"]


# --------------------------------------------------------------------------- #
# What the spans carry
# --------------------------------------------------------------------------- #
def test_the_triage_span_carries_the_structural_attributes_an_operator_needs() -> None:
    _, attributes = _triage(sample_cases.ROUTINE_CASE).spans[0]
    assert attributes["action"] == "triage"
    assert attributes["actor"] == sample_cases.ACTOR


def test_the_erm_spans_carry_the_structural_attributes_an_operator_needs() -> None:
    """Enough to answer "whose ERM call is slow, in which tenant", and nothing more."""
    tracer, _ = _assess()
    _, attributes = tracer.spans[0]
    assert attributes["action"] == "assess_rcsa"
    assert attributes["actor"] == sample_cases.ACTOR
    assert attributes["tenant"] == SEED_TENANT

    tracer, _ = _merge()
    _, attributes = tracer.spans[0]
    assert attributes["action"] == "propose_control_merges"
    assert attributes["actor"] == sample_cases.ACTOR
    assert attributes["tenant"] == SEED_TENANT


@pytest.mark.parametrize(
    "case",
    [sample_cases.ROUTINE_CASE, sample_cases.ESCALATING_CASE, sample_cases.PII_CASE],
    ids=["routine", "escalating", "pii"],
)
def test_the_triage_attribute_set_is_a_fixed_allowlist_whatever_the_verdict(
    case: TriageInput,
) -> None:
    for _, attributes in _triage(case).spans:
        assert set(attributes) == _TRIAGE_KEYS


def test_the_erm_attribute_sets_are_a_fixed_allowlist_even_when_the_outcome_escalates() -> None:
    """A red line and a merge sweep must not start explaining themselves on the span."""
    tracer, outcome = _assess()
    assert outcome.requires_human_review, (
        "the red fixture stopped escalating, so this test no longer proves an escalating "
        "outcome keeps its content off the span"
    )
    for _, attributes in tracer.spans:
        assert set(attributes) == _ERM_KEYS, (
            "a new span attribute appeared; confirm it is structural, then widen "
            "_ERM_KEYS here deliberately"
        )
    merge_tracer, _ = _merge()
    for _, attributes in merge_tracer.spans:
        assert set(attributes) == _ERM_KEYS


# --------------------------------------------------------------------------- #
# What the spans must never carry
# --------------------------------------------------------------------------- #
def test_no_triage_span_attribute_carries_case_content_or_the_planted_identifier() -> None:
    """The case used here has an NRIC planted in its description, so a leak would show."""
    emitted = _emitted(_triage(sample_cases.PII_CASE))
    forbidden = [
        sample_cases.PLANTED_NRIC,
        sample_cases.PII_CASE.subject,
        sample_cases.PII_CASE.text,
        "ops@gamma.example",
    ]
    for literal in forbidden:
        assert literal, "an empty needle would pass this test for the wrong reason"
        assert literal.lower() not in emitted.lower(), f"a span attribute carried {literal!r}"


def test_no_erm_span_attribute_carries_control_content_or_the_planted_identifier() -> None:
    """The control id carries the planted NRIC, and the note restates engine figures."""
    tracer, outcome = _assess()
    emitted = _emitted(tracer)
    forbidden = [sample_cases.PLANTED_NRIC, _PII_CONTROL_ID, outcome.note]
    for literal in forbidden:
        assert literal, "an empty needle would pass this test for the wrong reason"
        assert literal.lower() not in emitted.lower(), f"a span attribute carried {literal!r}"

    merge_tracer, merge_outcome = _merge()
    merge_emitted = _emitted(merge_tracer).lower()
    assert merge_outcome.candidates, "an empty sweep would pass this test for the wrong reason"
    for candidate in merge_outcome.candidates:
        assert candidate.left_id.lower() not in merge_emitted
        assert candidate.right_id.lower() not in merge_emitted


def test_every_emitted_attribute_value_is_a_string_the_port_declares() -> None:
    """``span(name, **attributes: str)``: a non-string would serialise however the SDK felt."""
    assess_tracer, _ = _assess()
    merge_tracer, _ = _merge()
    values: list[Any] = [
        v
        for tracer in (assess_tracer, merge_tracer, _triage(sample_cases.ESCALATING_CASE))
        for _, attributes in tracer.spans
        for v in attributes.values()
    ]
    assert values
    assert all(isinstance(value, str) for value in values)
