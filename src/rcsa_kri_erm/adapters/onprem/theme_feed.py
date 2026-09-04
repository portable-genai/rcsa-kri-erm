"""On-prem ThemeFeedPort: fail-fast portability placeholder.

The client wires its own issue-remediation-capa (issue/CAPA) theme feed behind this seam. Read-only,
and it refuses at call time rather than returning an empty tuple that a caller could mistake for "no
themes".
"""

from __future__ import annotations

from ...config import Settings
from ...domain.erm_models import Theme


class OnPremThemeFeedAdapter:
    """Satisfies ThemeFeedPort but refuses at call time: the client binds its own theme feed."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def themes(self, tenant: str) -> tuple[Theme, ...]:
        raise NotImplementedError(
            "on-prem theme feed is a portability placeholder: bind the client's own "
            "issue-remediation-capa "
            "deployment or issue-management feed (see docs/onprem-migration.md)"
        )
