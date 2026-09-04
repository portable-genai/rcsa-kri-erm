"""Freeze the issue-remediation-capa theme-feed contract while issue-remediation-capa is unbuilt.

issue-remediation-capa is a catalog sibling that is not built, so rcsa-kri-erm consumes its one-way
theme feed through a FROZEN fixture whose shape is pinned here. When issue-remediation-capa ships,
its remote adapter must return this same shape; this test is the recorded agreement, so a drift on
either side is a build failure rather than a silent mismatch at integration time.

The contract: `themes(tenant)` returns a tuple of `Theme` records, each carrying a stable
`theme_id`, a human label, the tuple of `control_ids` the theme spans, an integer `weight`, and the
member issue ids that back it. The owning tenant reads its themes; any other tenant is REFUSED. That
last clause is part of the frozen contract, so issue-remediation-capa's remote adapter has to refuse
too: pinning the opposite (`themes("some-other-bank") == ()`) would record a silent empty answer as
the agreed behaviour and carry that defect into issue-remediation-capa at integration time.
"""

from __future__ import annotations

import pytest

from rcsa_kri_erm.adapters.local.theme_feed import LocalThemeFeedAdapter
from rcsa_kri_erm.config import Settings
from rcsa_kri_erm.domain.erm_models import Theme
from rcsa_kri_erm.domain.errors import TenantAccessDeniedError

_TENANT = "demo-bank"

#: The recorded shape of the feed: theme_id -> (control_ids, weight). Pinning the ids and weights
#: freezes the contract the reopen engine depends on (a high-weight access theme forces a reopen).
_EXPECTED: dict[str, tuple[tuple[str, ...], int]] = {
    "THM-ACCESS-DRIFT": (("CTL-ACCESS-01", "CTL-ACCESS-07"), 4),
    "THM-DR-GAPS": (("CTL-DR-02",), 2),
}


def _adapter() -> LocalThemeFeedAdapter:
    return LocalThemeFeedAdapter(Settings(profile="local"))


def test_theme_feed_returns_the_frozen_shape() -> None:
    themes = _adapter().themes(_TENANT)
    assert themes, "the frozen issue-remediation-capa fixture must serve the demo tenant's themes"
    assert all(isinstance(t, Theme) for t in themes)
    got = {t.theme_id: (t.control_ids, t.weight) for t in themes}
    assert got == _EXPECTED
    for theme in themes:
        assert theme.label, "each theme carries a human label"
        assert theme.member_issue_ids, "each theme cites the issues that back it"


def test_theme_feed_refuses_a_tenant_it_does_not_serve() -> None:
    """A refusal, not an empty tuple: the caller must be able to tell the two apart."""
    with pytest.raises(TenantAccessDeniedError):
        _adapter().themes("some-other-bank")
