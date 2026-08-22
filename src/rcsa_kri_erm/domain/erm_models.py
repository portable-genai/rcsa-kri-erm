"""ERM vertical types: the risk artifacts the second-line copilot reasons over.

Pure stdlib. These are the value objects the deterministic engines (``rcsa.py``, ``kri.py``,
``dedup.py``, ``themes.py``) compute over and the narration service restates. Every consequential
number that appears on one of these is produced by an engine, never by a model.

The house rule the type system enforces here: a *proposed* rating is inert. ``RcsaAssessment``
separates ``proposed_ratings`` from ``accepted_ratings`` so residual scoring can only ever read
the accepted set, and a model-authored proposal cannot move a number until a maker signs it off
through Hrz7 (rule R8). See :mod:`.rcsa`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from hex_service_kit.enums import LenientStrEnum

from .kernel import Citation


class RagBand(LenientStrEnum):
    """The three-state RAG posture, ordered worst-first for worst-wins roll-ups."""

    RED = "red"
    AMBER = "amber"
    GREEN = "green"


#: RAG order, worst first. A roll-up takes the max over this order (worst wins).
RAG_ORDER: tuple[RagBand, ...] = (RagBand.RED, RagBand.AMBER, RagBand.GREEN)


class ControlEffectiveness(LenientStrEnum):
    """A control's operating effectiveness, as read from Rgc7 evidence or a maker's rating."""

    INEFFECTIVE = "ineffective"
    PARTIAL = "partial"
    EFFECTIVE = "effective"


class TrendDirection(LenientStrEnum):
    """The deterministic trend of a metric series, computed from the ordered points."""

    IMPROVING = "improving"
    STABLE = "stable"
    WORSENING = "worsening"


class BreachDirection(LenientStrEnum):
    """Which side of a threshold is a breach: an upper bound or a lower bound."""

    UPPER = "upper"  # a value at or ABOVE the threshold breaches (e.g. failed-login rate)
    LOWER = "lower"  # a value at or BELOW the threshold breaches (e.g. capital ratio)


@dataclass(frozen=True, slots=True)
class ControlRecord:
    """One control read from Rgc7's control library (this repo keeps no catalog of its own).

    ``control_id`` is Rgc7's identifier; ``effectiveness`` is the latest Aud2 result exposed as an
    evidence node on Rgc7's graph. This repo persists RATINGS and ASSESSMENTS keyed on this id, and
    never the control's catalog membership. ``tenant`` is the owning partition for cross-tenant
    authorisation.
    """

    control_id: str
    title: str
    tenant: str
    effectiveness: ControlEffectiveness = ControlEffectiveness.PARTIAL
    description: str = ""


@dataclass(frozen=True, slots=True)
class RiskRating:
    """An inherent-risk rating on a 1..5 impact / 1..5 likelihood scale.

    A rating is a *proposal* until a maker accepts it. The engine reads only accepted ratings, so a
    model-drafted proposal changes no residual number until a human signs it off (rule R8).
    """

    control_id: str
    impact: int
    likelihood: int
    effectiveness: ControlEffectiveness = ControlEffectiveness.PARTIAL
    citations: tuple[Citation, ...] = ()


@dataclass(frozen=True, slots=True)
class ResidualRisk:
    """The deterministic residual-risk outcome for one control's accepted rating."""

    control_id: str
    inherent_score: int
    residual_score: int
    residual_likelihood: int
    band: RagBand
    drivers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class RcsaAssessment:
    """One RCSA line: a control, its proposed ratings and the ratings a maker has accepted.

    ``proposed_ratings`` never feed scoring; only ``accepted_ratings`` do. This separation is the
    whole point of the type: it makes "a proposal cannot move a number" a property of the data, not
    a convention a reviewer has to remember.
    """

    control_id: str
    tenant: str
    proposed_ratings: tuple[RiskRating, ...] = ()
    accepted_ratings: tuple[RiskRating, ...] = ()
    theme_signals: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class KriDefinition:
    """A KRI/KCI definition tied to an appetite limit. Evaluated ONLY when ``adopted`` is True.

    A proposed definition (``adopted=False``) is inert exactly as a proposed rating is: the model
    may draft the threshold, but the engine evaluates it only after a human adopts it.
    """

    kri_id: str
    category: str
    metric_key: str
    direction: BreachDirection
    warning_threshold: float
    breach_threshold: float
    appetite_limit: float
    adopted: bool = False


@dataclass(frozen=True, slots=True)
class MetricPoint:
    """One observed metric value at a point in time (the KRI feed's unit)."""

    metric_key: str
    value: float
    as_of: date


@dataclass(frozen=True, slots=True)
class KriEvaluation:
    """The deterministic evaluation of one adopted KRI against its feed at an ``as_of``."""

    kri_id: str
    category: str
    value: float
    band: RagBand
    trend: TrendDirection
    breached: bool
    consecutive_breaches: int
    as_of: date
    drivers: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class Breach:
    """A consequential KRI breach: it sets human review and routes to Hrz7."""

    kri_id: str
    category: str
    severity: RagBand
    score: int
    value: float
    breach_threshold: float
    trend: TrendDirection
    consecutive_breaches: int
    drivers: tuple[tuple[str, str], ...]
    as_of: date


@dataclass(frozen=True, slots=True)
class MergeCandidate:
    """A proposed de-duplication of two controls, above the config similarity floor.

    A merge is consequential (it collapses two risk lines into one), so it is a PROPOSAL routed to
    Hrz7, never an automatic action.
    """

    left_id: str
    right_id: str
    similarity: float


@dataclass(frozen=True, slots=True)
class Theme:
    """An Aud3 thematic cluster consumed as a one-way risk signal."""

    theme_id: str
    label: str
    control_ids: tuple[str, ...]
    weight: int
    member_issue_ids: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True, slots=True)
class ReopenDecision:
    """A deterministic decision to reopen an assessment for review, with its reason."""

    control_id: str
    reopen: bool
    reason: str
    theme_id: str = ""
