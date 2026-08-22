"""Nothing redaction removed survives anywhere else in the WORM record (check C3).

Both services masked ``redacted_summary`` and then handed the SAME event their citations
untouched, so the identifier the summary no longer carried was persisted verbatim one field
away, in a record that is by design immutable and long-retained. The summary is not the record.

Two rules this suite holds, and they pull in opposite directions, which is why both are written
down:

* every CONTENT field is scanned: the summary, and each citation's locator, title and snippet.
  A triage locator is built from the case subject and its snippet is cut from the case text; an
  ERM locator is built from a control id, a merge pair or a theme id. All of them are text this
  service did not author, wearing a structural-looking name.
* the ATTRIBUTION field is not. ``actor`` is the verified principal and is an address by design,
  so a blanket scan over a whole audit row could never go green, and a scan that "fixed" that by
  masking the actor would erase the only column that says who acted.

Scored two ways, as the eval metric is: the shared pack's own rows, plus the planted literals,
which still fire if a pattern row is broken.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

import pytest
from pii_kit import pack_leak

from rcsa_kri_erm.adapters._review_payload import result_to_review
from rcsa_kri_erm.adapters.local.audit import LocalAuditAdapter
from rcsa_kri_erm.config import Container
from rcsa_kri_erm.domain.erm_models import (
    ControlEffectiveness,
    RcsaAssessment,
    RiskRating,
)
from rcsa_kri_erm.domain.erm_service import ErmService
from rcsa_kri_erm.domain.models import TriageInput
from rcsa_kri_erm.domain.pii import PII_PATTERNS
from rcsa_kri_erm.domain.triage_service import TriageService

from tests.fixtures import sample_cases

_PLANTED = (sample_cases.PLANTED_NRIC, sample_cases.PLANTED_EMAIL)


def _content(row: Mapping[str, Any]) -> str:
    """Every content-bearing field of one audit row, as one scannable blob.

    ``actor`` and the structural columns are excluded deliberately: see the module docstring.
    """
    return " ".join(
        (
            str(row.get("redacted_summary", "")),
            json.dumps(row.get("citations", []), sort_keys=True),
        )
    )


def _assert_clean(rows: list[dict[str, Any]]) -> None:
    assert rows, "the service wrote no audit record, so this proves nothing"
    for row in rows:
        blob = _content(row)
        assert not pack_leak(blob, PII_PATTERNS), f"pack row matched in the WORM record: {blob}"
        for token in _PLANTED:
            assert token not in blob, f"planted {token!r} survived into the WORM record: {blob}"


def _erm(container: Container) -> ErmService:
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


def _rows(container: Container) -> list[dict[str, Any]]:
    audit = container.audit
    assert isinstance(audit, LocalAuditAdapter)
    return list(audit.log.read_all())


@pytest.mark.parametrize(
    "case",
    [sample_cases.PII_CASE, sample_cases.PII_SUBJECT_CASE],
    ids=["identifier-in-text", "identifier-in-subject-and-text"],
)
def test_no_identifier_reaches_the_audit_record(
    triage_service: TriageService, container: Container, case: TriageInput
) -> None:
    triage_service.triage(case, actor=sample_cases.ACTOR)
    _assert_clean(_rows(container))


def test_no_identifier_reaches_the_audit_record_on_the_erm_path(container: Container) -> None:
    """The ERM service writes the same record type, so the same rule holds on its citations.

    Its locator is ``control:<control_id>``, and a control id is a client naming convention this
    service does not control. Seven ``_record`` call sites share the write, which is why the
    boundary sits on the type rather than on any one of them.
    """
    rating = RiskRating(
        control_id=sample_cases.PII_CONTROL_ID,
        impact=5,
        likelihood=5,
        effectiveness=ControlEffectiveness.INEFFECTIVE,
    )
    assessment = RcsaAssessment(
        control_id=sample_cases.PII_CONTROL_ID,
        tenant=sample_cases.TENANT,
        accepted_ratings=(rating,),
    )
    _erm(container).assess_rcsa(assessment, actor=sample_cases.ACTOR)
    _assert_clean(_rows(container))


def test_the_actor_is_kept_verbatim_because_it_is_attribution(
    triage_service: TriageService, container: Container
) -> None:
    """The caveat, pinned: the principal is an address and must NOT be masked away."""
    triage_service.triage(sample_cases.PII_CASE, actor=sample_cases.ACTOR)

    actors = [str(row.get("actor", "")) for row in _rows(container)]
    assert actors == [sample_cases.ACTOR]


def test_review_payload_is_redacted_in_every_field_that_crosses_the_wire(
    triage_service: TriageService,
) -> None:
    """The console is a shared sink, and a locator, a case ref and a dedup key cross it too.

    ``subject`` was masked while ``case_ref`` and ``source_key`` carried the same string raw, and
    the citation ``snippet`` was masked while its ``source_id`` and ``title`` were not. Every one
    of them is on the wire to Hrz7, so every one of them is scanned here.
    """
    result = triage_service.triage(sample_cases.PII_SUBJECT_CASE, actor=sample_cases.ACTOR)
    review = result_to_review(result, maker=sample_cases.ACTOR, tenant=sample_cases.TENANT)

    blob = json.dumps(
        {
            "subject": review.subject,
            "summary": review.summary,
            "case_ref": review.case_ref,
            "source_key": review.source_key,
            "citations": [
                {"source_id": c.source_id, "title": c.title, "snippet": c.snippet}
                for c in review.citations
            ],
        },
        sort_keys=True,
    )
    assert not pack_leak(blob, PII_PATTERNS), f"pack row matched in the review payload: {blob}"
    for token in _PLANTED:
        assert token not in blob, f"planted {token!r} crossed to the console: {blob}"
