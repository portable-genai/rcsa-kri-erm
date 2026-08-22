"""Residual-risk engine: pure code over ACCEPTED ratings, config-owned policy numbers.

Slice 2 of the Erm1 plan. The consequential residual score is arithmetic on a frozen,
bank-owned :class:`ResidualRiskPolicy` (B4: policy numbers in config, engine in code). Two rules
make it defensible in front of a regulator:

* **Only accepted ratings score.** :func:`residual_for_assessment` reads
  ``assessment.accepted_ratings`` and never ``proposed_ratings``. A model-drafted proposal
  changes no number until a maker signs it off through Hrz7. ``tests`` prove an assessment with
  only proposals scores as if it had none.
* **Effectiveness reduces likelihood, never impact.** A working control makes a loss less
  likely; it does not make the loss smaller. The reduction is a config-owned step per
  effectiveness level, and residual likelihood is floored at 1 so a control can never zero out a
  risk.

Nothing here imports a framework, a cloud SDK or a port. The LLM never produces a score; it only
narrates one (see ``erm_narration.py``).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .erm_models import (
    ControlEffectiveness,
    RagBand,
    RcsaAssessment,
    ResidualRisk,
    RiskRating,
)

__all__ = [
    "ResidualRiskPolicy",
    "residual_for_assessment",
    "residual_for_rating",
    "worst_band",
]

#: Reference likelihood reduction per effectiveness level. A fully effective control buys the most
#: reduction; an ineffective one buys none. Bank-owned (B4); defaults ARE the reference policy.
_DEFAULT_EFFECTIVENESS_REDUCTION: dict[str, int] = {
    ControlEffectiveness.EFFECTIVE.value: 2,
    ControlEffectiveness.PARTIAL.value: 1,
    ControlEffectiveness.INEFFECTIVE.value: 0,
}

#: Reference band floors on the 1..25 residual score, evaluated worst-first.
_DEFAULT_BAND_THRESHOLDS: dict[str, int] = {
    RagBand.RED.value: 15,
    RagBand.AMBER.value: 8,
    RagBand.GREEN.value: 0,
}


@dataclass(frozen=True, slots=True)
class ResidualRiskPolicy:
    """Bank-owned residual-risk numbers (B4). Defaults equal the reference policy."""

    min_scale: int = 1
    max_scale: int = 5
    effectiveness_reduction: dict[str, int] = field(
        default_factory=lambda: dict(_DEFAULT_EFFECTIVENESS_REDUCTION)
    )
    band_thresholds: dict[str, int] = field(default_factory=lambda: dict(_DEFAULT_BAND_THRESHOLDS))
    #: Residual band at or above which the assessment is consequential enough to force review.
    review_band: str = RagBand.AMBER.value

    def clamp_scale(self, value: int) -> int:
        """Clamp an impact/likelihood onto the policy's declared scale."""
        return max(self.min_scale, min(self.max_scale, int(value)))

    def band_for(self, score: int) -> RagBand:
        """Band a residual score against the config-owned floors, worst first."""
        for band in (RagBand.RED, RagBand.AMBER, RagBand.GREEN):
            floor = self.band_thresholds.get(band.value)
            if floor is not None and score >= int(floor):
                return band
        return RagBand.GREEN


def residual_for_rating(rating: RiskRating, policy: ResidualRiskPolicy) -> ResidualRisk:
    """Compute the residual risk for one accepted rating, with named drivers.

    ``inherent = impact * likelihood``; ``residual = impact * max(1, likelihood - reduction)``.
    Every figure is derived here; a caller that hands this a *proposed* rating is misusing the
    engine, which is why the register only ever passes accepted ratings (see
    :func:`residual_for_assessment`).
    """
    impact = policy.clamp_scale(rating.impact)
    likelihood = policy.clamp_scale(rating.likelihood)
    inherent = impact * likelihood

    reduction = int(policy.effectiveness_reduction.get(rating.effectiveness.value, 0))
    residual_likelihood = max(policy.min_scale, likelihood - reduction)
    residual = impact * residual_likelihood
    band = policy.band_for(residual)

    drivers: tuple[tuple[str, str], ...] = (
        ("impact", str(impact)),
        ("likelihood", str(likelihood)),
        ("inherent_score", str(inherent)),
        ("effectiveness", rating.effectiveness.value),
        ("likelihood_reduction", str(reduction)),
        ("residual_likelihood", str(residual_likelihood)),
        ("residual_score", str(residual)),
        ("band", band.value),
    )
    return ResidualRisk(
        control_id=rating.control_id,
        inherent_score=inherent,
        residual_score=residual,
        residual_likelihood=residual_likelihood,
        band=band,
        drivers=drivers,
    )


def residual_for_assessment(
    assessment: RcsaAssessment, policy: ResidualRiskPolicy | None = None
) -> tuple[ResidualRisk, ...]:
    """Score every ACCEPTED rating on an assessment. Proposed ratings are ignored by design.

    Returns one :class:`ResidualRisk` per accepted rating, in input order. An assessment carrying
    only proposals returns an empty tuple: nothing a maker has not signed off can move a residual
    number.
    """
    resolved = policy or ResidualRiskPolicy()
    return tuple(residual_for_rating(rating, resolved) for rating in assessment.accepted_ratings)


def worst_band(residuals: tuple[ResidualRisk, ...]) -> RagBand:
    """The worst residual band across a set (worst-wins), or GREEN when the set is empty."""
    worst = RagBand.GREEN
    order = (RagBand.GREEN, RagBand.AMBER, RagBand.RED)
    for residual in residuals:
        if order.index(residual.band) > order.index(worst):
            worst = residual.band
    return worst
