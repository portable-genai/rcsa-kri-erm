"""Unit tests for the pure ERM engines: residual risk, KRI, de-dup, themes."""

from __future__ import annotations

from datetime import date

from rcsa_kri_erm.domain.dedup import cosine_similarity, propose_merges
from rcsa_kri_erm.domain.erm_models import (
    BreachDirection,
    ControlEffectiveness,
    KriDefinition,
    MetricPoint,
    RagBand,
    RcsaAssessment,
    RiskRating,
    Theme,
    TrendDirection,
)
from rcsa_kri_erm.domain.kri import (
    breach_from_evaluation,
    evaluate,
    evaluate_one,
    rollup_band,
)
from rcsa_kri_erm.domain.rcsa import (
    ResidualRiskPolicy,
    residual_for_assessment,
    residual_for_rating,
    worst_band,
)
from rcsa_kri_erm.domain.themes import reopen_decisions


# --------------------------------------------------------------------------- #
# Residual risk
# --------------------------------------------------------------------------- #
def test_effectiveness_reduces_likelihood_not_impact() -> None:
    policy = ResidualRiskPolicy()
    ineffective = residual_for_rating(
        RiskRating("c", 5, 5, ControlEffectiveness.INEFFECTIVE), policy
    )
    effective = residual_for_rating(RiskRating("c", 5, 5, ControlEffectiveness.EFFECTIVE), policy)
    assert ineffective.residual_score == 25 and ineffective.band is RagBand.RED
    # impact unchanged (5), likelihood reduced by 2 -> 5 * 3 = 15
    assert effective.residual_score == 15
    assert effective.inherent_score == 25  # inherent ignores the control


def test_residual_likelihood_floored_at_one() -> None:
    policy = ResidualRiskPolicy()
    residual = residual_for_rating(RiskRating("c", 4, 1, ControlEffectiveness.EFFECTIVE), policy)
    assert residual.residual_likelihood == 1  # 1 - 2 floored to 1, never zero
    assert residual.residual_score == 4


def test_only_accepted_ratings_score() -> None:
    """A proposal is inert: an assessment carrying only proposals scores nothing."""
    proposals_only = RcsaAssessment(
        control_id="c",
        tenant="demo-bank",
        proposed_ratings=(RiskRating("c", 5, 5, ControlEffectiveness.INEFFECTIVE),),
        accepted_ratings=(),
    )
    assert residual_for_assessment(proposals_only) == ()
    assert worst_band(residual_for_assessment(proposals_only)) is RagBand.GREEN

    accepted = RcsaAssessment(
        control_id="c",
        tenant="demo-bank",
        proposed_ratings=(RiskRating("c", 1, 1, ControlEffectiveness.EFFECTIVE),),
        accepted_ratings=(RiskRating("c", 5, 5, ControlEffectiveness.INEFFECTIVE),),
    )
    residuals = residual_for_assessment(accepted)
    assert len(residuals) == 1 and residuals[0].band is RagBand.RED


# --------------------------------------------------------------------------- #
# KRI
# --------------------------------------------------------------------------- #
def _series(key: str, values: list[float]) -> tuple[MetricPoint, ...]:
    return tuple(MetricPoint(key, v, date(2026, 1 + i, 1)) for i, v in enumerate(values))


def test_unadopted_kri_is_never_evaluated() -> None:
    proposed = KriDefinition(
        kri_id="k",
        category="x",
        metric_key="m",
        direction=BreachDirection.UPPER,
        warning_threshold=2.0,
        breach_threshold=5.0,
        appetite_limit=5.0,
        adopted=False,
    )
    assert evaluate_one(proposed, _series("m", [9.0]), "2026-01-01") is None
    assert evaluate((proposed,), _series("m", [9.0]), "2026-01-01") == ()


def test_lower_bound_breach_and_trend() -> None:
    definition = KriDefinition(
        kri_id="cap",
        category="capital",
        metric_key="m",
        direction=BreachDirection.LOWER,
        warning_threshold=12.0,
        breach_threshold=10.5,
        appetite_limit=10.5,
        adopted=True,
    )
    evaluation = evaluate_one(definition, _series("m", [11.0, 10.0]), "2026-02-01")
    assert evaluation is not None
    assert evaluation.band is RagBand.RED and evaluation.breached
    assert evaluation.trend is TrendDirection.WORSENING  # falling value on a lower-bound KRI


def test_as_of_excludes_later_points() -> None:
    definition = KriDefinition(
        kri_id="k",
        category="x",
        metric_key="m",
        direction=BreachDirection.UPPER,
        warning_threshold=2.0,
        breach_threshold=5.0,
        appetite_limit=5.0,
        adopted=True,
    )
    series = _series("m", [1.0, 9.0])  # month 1 clean, month 2 breaching
    evaluation = evaluate_one(definition, series, "2026-01-15")  # only month 1 is in scope
    assert evaluation is not None and not evaluation.breached and evaluation.value == 1.0


def test_breach_severity_is_additive_and_persistence_raises_it() -> None:
    definition = KriDefinition(
        kri_id="k",
        category="x",
        metric_key="m",
        direction=BreachDirection.UPPER,
        warning_threshold=2.0,
        breach_threshold=5.0,
        appetite_limit=5.0,
        adopted=True,
    )
    one = evaluate_one(definition, _series("m", [6.0]), "2026-01-01")
    many = evaluate_one(definition, _series("m", [6.0, 6.0, 6.0]), "2026-03-01")
    assert one is not None and many is not None
    breach_one = breach_from_evaluation(definition, one)
    breach_many = breach_from_evaluation(definition, many)
    assert breach_one is not None and breach_many is not None
    assert breach_many.score > breach_one.score  # persistence adds points


def test_non_breach_yields_no_breach() -> None:
    definition = KriDefinition(
        kri_id="k",
        category="x",
        metric_key="m",
        direction=BreachDirection.UPPER,
        warning_threshold=2.0,
        breach_threshold=5.0,
        appetite_limit=5.0,
        adopted=True,
    )
    evaluation = evaluate_one(definition, _series("m", [3.0]), "2026-01-01")
    assert evaluation is not None and not evaluation.breached
    assert breach_from_evaluation(definition, evaluation) is None


def test_rollup_is_worst_wins() -> None:
    green = KriDefinition("g", "x", "mg", BreachDirection.UPPER, 2.0, 5.0, 5.0, adopted=True)
    red = KriDefinition("r", "x", "mr", BreachDirection.UPPER, 2.0, 5.0, 5.0, adopted=True)
    points = _series("mg", [0.0]) + _series("mr", [9.0])
    evaluations = evaluate((green, red), points, "2026-01-01")
    assert rollup_band(evaluations) is RagBand.RED


# --------------------------------------------------------------------------- #
# De-dup and themes
# --------------------------------------------------------------------------- #
def test_propose_merges_is_deterministic_and_symmetric_once() -> None:
    vectors = {
        "A": (1.0, 0.0, 0.0),
        "B": (0.99, 0.14, 0.0),
        "C": (0.0, 0.0, 1.0),
    }
    first = propose_merges(vectors, floor=0.5)
    second = propose_merges(vectors, floor=0.5)
    assert first == second
    assert [(c.left_id, c.right_id) for c in first] == [("A", "B")]  # each pair once, sorted


def test_cosine_zero_vector() -> None:
    assert cosine_similarity((0.0, 0.0), (1.0, 1.0)) == 0.0


def test_reopen_requires_a_weighted_attached_theme() -> None:
    themes = (
        Theme("hi", "drift", ("CTL-A",), 4),
        Theme("lo", "gaps", ("CTL-B",), 1),
    )
    assessments = (
        RcsaAssessment("CTL-A", "demo-bank"),  # high-weight theme -> reopen
        RcsaAssessment("CTL-B", "demo-bank"),  # low-weight theme -> no reopen
        RcsaAssessment("CTL-C", "demo-bank"),  # no theme -> no reopen
    )
    decisions = {d.control_id: d for d in reopen_decisions(assessments, themes)}
    assert decisions["CTL-A"].reopen and decisions["CTL-A"].theme_id == "hi"
    assert not decisions["CTL-B"].reopen
    assert not decisions["CTL-C"].reopen and decisions["CTL-C"].theme_id == ""
