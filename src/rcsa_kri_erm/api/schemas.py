"""API request/response schemas (Pydantic) mapped to/from the pure-domain models."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from ..domain.models import TriageResult


class TriageRequest(BaseModel):
    subject: str
    text: str


class CitationModel(BaseModel):
    source_id: str
    title: str
    snippet: str = ""


class TriageResponse(BaseModel):
    subject: str
    severity: str
    decision: str
    summary: str
    requires_human_review: bool
    #: Where the escalation WENT (rule R8): the human-review-console review id, or the local queue
    #: reference. Empty exactly when ``review_routing`` is not ``routed``.
    review_ref: str = ""
    #: What happened to the hand-off: routed, failed, off or not_required. ``failed`` means the
    #: result is NOT queued for review, and the console says so.
    review_routing: Literal["routed", "failed", "off", "not_required"] = "not_required"
    citations: list[CitationModel] = []

    @classmethod
    def from_domain(
        cls, result: TriageResult, *, review_ref: str = "", review_routing: str = "not_required"
    ) -> TriageResponse:
        return cls(
            subject=result.subject,
            severity=result.severity.value,
            decision=result.decision.value,
            summary=result.summary,
            requires_human_review=result.requires_human_review,
            review_ref=review_ref,
            review_routing=review_routing,  # type: ignore[arg-type]
            citations=[
                CitationModel(source_id=c.source_id, title=c.title, snippet=c.snippet)
                for c in result.citations
            ],
        )


class HealthResponse(BaseModel):
    status: str
    profile: str
    region: str
    #: What the UI's model pill states before any answer: where the runtime sits and which model
    #: the bound generator calls. Both are read off the service because the browser cannot know
    #: either. Once a request is answered, the pill shows that response's ``X-Answered-By``.
    runtime: str = "local"  # "gcp" | "local"
    generator_model: str = "deterministic-offline-stub"
