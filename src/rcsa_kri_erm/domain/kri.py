"""KRI/KCI engine: threshold and trend evaluation, worst-wins roll-up, breach severity.

Slice 3 of the Erm1 plan. Every consequential judgement is pure code over a frozen, config-owned
:class:`KriPolicy`:

* **Only adopted definitions evaluate.** :func:`evaluate` skips any
  :class:`~.erm_models.KriDefinition` whose ``adopted`` flag is False, so a model-proposed
  threshold is inert until a human adopts it.
* **Threshold evaluation is exact.** A value is banded GREEN / AMBER / RED against the definition's
  warning and breach thresholds, respecting :class:`~.erm_models.BreachDirection` (upper vs lower
  bound). The eval oracle proves this exact at 1.0 and provably red.
* **Trend is deterministic** from the ordered feed at an explicit ``as_of``: the latest point
  versus the previous one, worse/better/stable read through the breach direction.
* **Breach severity is an additive named-driver score** (crib of Rsk1's materiality engine):
  threshold distance, trend direction and persistence are named drivers summed into an integer
  and banded by config. The LLM never produces the score; it narrates it.

No web framework, no cloud SDK, no port, no clock beyond the caller-supplied ``as_of``.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .erm_models import (
    RAG_ORDER,
    Breach,
    BreachDirection,
    KriDefinition,
    KriEvaluation,
    MetricPoint,
    RagBand,
    TrendDirection,
)

__all__ = [
    "KriPolicy",
    "breach_from_evaluation",
    "evaluate",
    "evaluate_one",
    "rollup_band",
]

#: Reference severity band floors on the additive breach score, evaluated worst-first.
_DEFAULT_SEVERITY_THRESHOLDS: dict[str, int] = {
    RagBand.RED.value: 60,
    RagBand.AMBER.value: 30,
    RagBand.GREEN.value: 0,
}


@dataclass(frozen=True, slots=True)
class KriPolicy:
    """Bank-owned KRI numbers (B4). Defaults equal the reference policy."""

    #: Points per whole unit of distance past the breach threshold, capped.
    distance_points_per_unit: int = 8
    max_distance_points: int = 40
    #: Points added when the trend is worsening (a breach getting worse is more severe).
    worsening_points: int = 20
    stable_points: int = 8
    improving_points: int = 0
    #: Points per consecutive breaching period beyond the first, capped (persistence).
    persistence_points_per_period: int = 10
    max_persistence_points: int = 30
    severity_thresholds: dict[str, int] = field(
        default_factory=lambda: dict(_DEFAULT_SEVERITY_THRESHOLDS)
    )

    def severity_for(self, score: int) -> RagBand:
        for band in (RagBand.RED, RagBand.AMBER, RagBand.GREEN):
            floor = self.severity_thresholds.get(band.value)
            if floor is not None and score >= int(floor):
                return band
        return RagBand.GREEN


def _breaches(value: float, threshold: float, direction: BreachDirection) -> bool:
    """Whether ``value`` breaches ``threshold`` on the given side."""
    if direction is BreachDirection.UPPER:
        return value >= threshold
    return value <= threshold


def _band(value: float, definition: KriDefinition) -> RagBand:
    """Band a value GREEN/AMBER/RED against the definition's warning and breach thresholds."""
    if _breaches(value, definition.breach_threshold, definition.direction):
        return RagBand.RED
    if _breaches(value, definition.warning_threshold, definition.direction):
        return RagBand.AMBER
    return RagBand.GREEN


def _ordered_points(points: tuple[MetricPoint, ...], metric_key: str) -> tuple[MetricPoint, ...]:
    """The feed for one metric, ascending by date (stable sort, deterministic)."""
    selected = [p for p in points if p.metric_key == metric_key]
    selected.sort(key=lambda p: p.as_of)
    return tuple(selected)


def _trend(series: tuple[MetricPoint, ...], definition: KriDefinition) -> TrendDirection:
    """Deterministic trend from the last two points, read through the breach direction."""
    if len(series) < 2:
        return TrendDirection.STABLE
    latest = series[-1].value
    previous = series[-2].value
    if latest == previous:
        return TrendDirection.STABLE
    rising = latest > previous
    # For an UPPER-bound KRI a rising value is worsening; for a LOWER-bound one it is improving.
    worsening = rising if definition.direction is BreachDirection.UPPER else not rising
    return TrendDirection.WORSENING if worsening else TrendDirection.IMPROVING


def _consecutive_breaches(series: tuple[MetricPoint, ...], definition: KriDefinition) -> int:
    """Count trailing consecutive breaching periods ending at the latest point."""
    count = 0
    for point in reversed(series):
        if _breaches(point.value, definition.breach_threshold, definition.direction):
            count += 1
        else:
            break
    return count


def evaluate_one(
    definition: KriDefinition,
    points: tuple[MetricPoint, ...],
    as_of: str,
) -> KriEvaluation | None:
    """Evaluate one ADOPTED definition against its feed, or ``None`` if it is not adopted or empty.

    ``as_of`` is carried onto the result so a replay is pinned to a stated evaluation date. The
    feed is filtered to points on or before ``as_of`` so a later observation cannot leak into a
    historical evaluation.
    """
    if not definition.adopted:
        return None
    series = tuple(
        p for p in _ordered_points(points, definition.metric_key) if str(p.as_of) <= as_of
    )
    if not series:
        return None
    latest = series[-1]
    band = _band(latest.value, definition)
    trend = _trend(series, definition)
    breached = _breaches(latest.value, definition.breach_threshold, definition.direction)
    consecutive = _consecutive_breaches(series, definition)
    drivers: tuple[tuple[str, str], ...] = (
        ("value", str(latest.value)),
        ("warning_threshold", str(definition.warning_threshold)),
        ("breach_threshold", str(definition.breach_threshold)),
        ("appetite_limit", str(definition.appetite_limit)),
        ("direction", definition.direction.value),
        ("band", band.value),
        ("trend", trend.value),
        ("consecutive_breaches", str(consecutive)),
    )
    return KriEvaluation(
        kri_id=definition.kri_id,
        category=definition.category,
        value=latest.value,
        band=band,
        trend=trend,
        breached=breached,
        consecutive_breaches=consecutive,
        as_of=latest.as_of,
        drivers=drivers,
    )


def evaluate(
    definitions: tuple[KriDefinition, ...],
    points: tuple[MetricPoint, ...],
    as_of: str,
) -> tuple[KriEvaluation, ...]:
    """Evaluate every adopted definition with a usable feed, in input order."""
    out: list[KriEvaluation] = []
    for definition in definitions:
        evaluation = evaluate_one(definition, points, as_of)
        if evaluation is not None:
            out.append(evaluation)
    return tuple(out)


def rollup_band(evaluations: tuple[KriEvaluation, ...]) -> RagBand:
    """The worst-wins RAG roll-up across a set of evaluations (GREEN when empty)."""
    worst = RagBand.GREEN
    for evaluation in evaluations:
        if RAG_ORDER.index(evaluation.band) < RAG_ORDER.index(worst):
            worst = evaluation.band
    return worst


def breach_from_evaluation(
    definition: KriDefinition,
    evaluation: KriEvaluation,
    policy: KriPolicy | None = None,
) -> Breach | None:
    """Compute the additive named-driver breach severity, or ``None`` if not breached.

    The score sums three named drivers (crib of Rsk1's materiality engine): the clamped distance
    past the breach threshold, a trend contribution, and a persistence contribution for consecutive
    breaches. The band comes from config-owned floors. A model never sees or sets this number.
    """
    if not evaluation.breached:
        return None
    resolved = policy or KriPolicy()

    distance = abs(evaluation.value - definition.breach_threshold)
    distance_points = min(
        int(distance * resolved.distance_points_per_unit), resolved.max_distance_points
    )

    if evaluation.trend is TrendDirection.WORSENING:
        trend_points = resolved.worsening_points
    elif evaluation.trend is TrendDirection.STABLE:
        trend_points = resolved.stable_points
    else:
        trend_points = resolved.improving_points

    extra_periods = max(0, evaluation.consecutive_breaches - 1)
    persistence_points = min(
        extra_periods * resolved.persistence_points_per_period,
        resolved.max_persistence_points,
    )

    score = distance_points + trend_points + persistence_points
    severity = resolved.severity_for(score)
    drivers: tuple[tuple[str, str], ...] = (
        ("threshold_distance", str(round(distance, 4))),
        ("distance_points", str(distance_points)),
        ("trend", evaluation.trend.value),
        ("trend_points", str(trend_points)),
        ("consecutive_breaches", str(evaluation.consecutive_breaches)),
        ("persistence_points", str(persistence_points)),
        ("breach_score", str(score)),
        ("severity", severity.value),
    )
    return Breach(
        kri_id=definition.kri_id,
        category=definition.category,
        severity=severity,
        score=score,
        value=evaluation.value,
        breach_threshold=definition.breach_threshold,
        trend=evaluation.trend,
        consecutive_breaches=evaluation.consecutive_breaches,
        drivers=drivers,
        as_of=evaluation.as_of,
    )
