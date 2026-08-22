"""Prove each ERM metric can go RED. A metric that cannot fail is not a metric.

Every score in ``eval/run_eval.py`` is measured against an INDEPENDENT hand-computed oracle, never
against the pipeline's own verdict. This suite proves the falsification directly: for each metric a
GREEN input scores at or above the threshold and a mutated RED input scores below it, via
``agent_eval_kit.assert_each_can_go_red`` (per-case, each carrying its own target).
"""

from __future__ import annotations

from datetime import date

from agent_eval_kit import assert_each_can_go_red

from rcsa_kri_erm.adapters.local.embeddings import LocalEmbeddingsAdapter
from rcsa_kri_erm.config import Settings
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
)
from rcsa_kri_erm.domain.kri import evaluate_one
from rcsa_kri_erm.domain.rcsa import ResidualRiskPolicy, residual_for_rating
from rcsa_kri_erm.domain.themes import reopen_decisions

_POLICY = ResidualRiskPolicy()


def _residual_score(rating: RiskRating) -> float:
    """1.0 when the engine bands this rating RED, else 0.0 (the oracle band for the green case)."""
    return 1.0 if residual_for_rating(rating, _POLICY).band is RagBand.RED else 0.0


def test_residual_accuracy_can_go_red() -> None:
    assert_each_can_go_red(
        _residual_score,
        {
            # A severe, uncontrolled risk bands RED (green); adding an effective control drops the
            # residual likelihood so it no longer reaches the RED floor (red mutant).
            "high_impact_control": (
                RiskRating("c", 5, 5, ControlEffectiveness.INEFFECTIVE),
                RiskRating("c", 3, 3, ControlEffectiveness.EFFECTIVE),
            ),
        },
        threshold=0.99,
        metric="residual_accuracy",
    )


def _kri_breached(series: tuple[float, ...]) -> float:
    """1.0 when the engine calls the latest point a breach, else 0.0."""
    key = "m"
    points = tuple(MetricPoint(key, v, date(2026, 1 + i, 1)) for i, v in enumerate(series))
    definition = KriDefinition(
        kri_id="k",
        category="eval",
        metric_key=key,
        direction=BreachDirection.UPPER,
        warning_threshold=2.0,
        breach_threshold=5.0,
        appetite_limit=5.0,
        adopted=True,
    )
    evaluation = evaluate_one(definition, points, str(points[-1].as_of))
    return 1.0 if evaluation is not None and evaluation.breached else 0.0


def test_kri_threshold_exactness_can_go_red() -> None:
    assert_each_can_go_red(
        _kri_breached,
        {
            # A value over the breach threshold is a breach (green); one under it is not (red).
            "upper_bound": ((1.0, 6.0), (1.0, 4.0)),
        },
        threshold=1.0,
        metric="kri_threshold_exactness",
    )


def _merge_precision(controls: tuple[tuple[str, str], ...]) -> float:
    """Precision of proposed merges against the single true duplicate pair (left,right)."""
    embedder = LocalEmbeddingsAdapter(Settings(profile="local"))
    texts = {cid: text for cid, text in controls}
    vectors = embedder.embed(texts)
    proposed = {(c.left_id, c.right_id) for c in propose_merges(vectors)}
    if not proposed:
        return 0.0
    expected = {("A", "B")}
    return len(proposed & expected) / len(proposed)


def test_merge_precision_can_go_red() -> None:
    assert_each_can_go_red(
        _merge_precision,
        {
            # A and B are near-duplicates and C is unrelated: only (A,B) is proposed (green).
            # The red mutant relabels C's text to match A, so a second, wrong pair is proposed and
            # precision falls below the floor.
            "one_true_pair": (
                (
                    ("A", "quarterly privileged access recertification by owner"),
                    ("B", "privileged access recertified each quarter by owner"),
                    ("C", "annual disaster recovery failover exercise"),
                ),
                (
                    ("A", "quarterly privileged access recertification by owner"),
                    ("B", "privileged access recertified each quarter by owner"),
                    ("C", "quarterly privileged access recertification by owner too"),
                ),
            ),
        },
        threshold=0.99,
        metric="merge_precision",
    )


def _reopen_correct(theme_weight: int) -> float:
    """1.0 when the engine's reopen for a themed control matches the oracle (reopen expected)."""
    themes = (Theme("T", "drift", ("CTL-X",), theme_weight),)
    assessments = (RcsaAssessment("CTL-X", "demo-bank"),)
    decision = reopen_decisions(assessments, themes)[0]
    return 1.0 if decision.reopen else 0.0


def test_reopen_accuracy_can_go_red() -> None:
    assert_each_can_go_red(
        _reopen_correct,
        {
            # A high-weight theme forces a reopen (green); a low-weight one does not (red mutant),
            # so a check that expects a reopen scores it 0.0.
            "weighted_theme": (4, 2),
        },
        threshold=0.99,
        metric="reopen_accuracy",
    )


def test_dedup_similarity_is_ordered() -> None:
    """The near-duplicate pair sits far above unrelated pairs in the embedder space."""
    embedder = LocalEmbeddingsAdapter(Settings(profile="local"))
    vectors = embedder.embed(
        {
            "A": "quarterly privileged access recertification by owner",
            "B": "privileged access recertified each quarter by owner",
            "C": "annual disaster recovery failover exercise",
        }
    )
    dup = cosine_similarity(vectors["A"], vectors["B"])
    unrelated = cosine_similarity(vectors["A"], vectors["C"])
    assert dup > 0.5 > unrelated
