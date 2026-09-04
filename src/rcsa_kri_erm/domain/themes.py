"""issue-remediation-capa theme consumption: attach themes to assessments, decide reopens
deterministically.

Slice 4 of the rcsa-kri-erm plan. issue-remediation-capa owns thematic RCA; this repo CONSUMES its
themes one-way as a risk signal (issue-remediation-capa is not yet built, so the read is served by a
frozen-fixture adapter whose contract is pinned by a fixture test). The consequential decision here
is which assessments REOPEN for review, and it is a pure, config-owned rule set:

* a theme attaches to an assessment when the theme names that assessment's ``control_id``;
* an attached theme forces a reopen when its ``weight`` is at or above the config floor.

A reopen is consequential (it puts a signed-off assessment back in the maker's queue), so the
service routes it to human-review-console. This module only decides; it performs no I/O.
"""

from __future__ import annotations

from dataclasses import dataclass

from .erm_models import RcsaAssessment, ReopenDecision, Theme

__all__ = ["ThemeTriggerPolicy", "attach_themes", "reopen_decisions"]

#: Reference theme weight at or above which an attached theme forces a reopen.
_DEFAULT_REOPEN_WEIGHT_FLOOR = 3


@dataclass(frozen=True, slots=True)
class ThemeTriggerPolicy:
    """Bank-owned trigger numbers (B4). Defaults equal the reference policy."""

    reopen_weight_floor: int = _DEFAULT_REOPEN_WEIGHT_FLOOR


def attach_themes(assessment: RcsaAssessment, themes: tuple[Theme, ...]) -> tuple[str, ...]:
    """The ids of themes that name this assessment's control, in input order (deterministic)."""
    return tuple(t.theme_id for t in themes if assessment.control_id in t.control_ids)


def reopen_decisions(
    assessments: tuple[RcsaAssessment, ...],
    themes: tuple[Theme, ...],
    policy: ThemeTriggerPolicy | None = None,
) -> tuple[ReopenDecision, ...]:
    """Decide, per assessment, whether an attached theme forces a reopen.

    Deterministic: for each assessment the highest-weight attached theme is considered, and a
    reopen is decided when that weight is at or above the floor. One decision per assessment, in
    input order.
    """
    resolved = policy or ThemeTriggerPolicy()
    by_id = {t.theme_id: t for t in themes}
    out: list[ReopenDecision] = []
    for assessment in assessments:
        attached = attach_themes(assessment, themes)
        if not attached:
            out.append(
                ReopenDecision(
                    control_id=assessment.control_id,
                    reopen=False,
                    reason="no theme names this control",
                )
            )
            continue
        strongest = max(attached, key=lambda tid: by_id[tid].weight)
        weight = by_id[strongest].weight
        if weight >= resolved.reopen_weight_floor:
            out.append(
                ReopenDecision(
                    control_id=assessment.control_id,
                    reopen=True,
                    reason=(
                        f"theme {strongest!r} (weight {weight}) at or above the reopen floor "
                        f"{resolved.reopen_weight_floor}"
                    ),
                    theme_id=strongest,
                )
            )
        else:
            out.append(
                ReopenDecision(
                    control_id=assessment.control_id,
                    reopen=False,
                    reason=(
                        f"strongest attached theme {strongest!r} (weight {weight}) below the "
                        f"reopen floor {resolved.reopen_weight_floor}"
                    ),
                    theme_id=strongest,
                )
            )
    return tuple(out)
