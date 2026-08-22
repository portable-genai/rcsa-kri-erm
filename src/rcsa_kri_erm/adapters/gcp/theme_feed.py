"""GCP ThemeFeedPort: a remote READ of Aud3's theme feed (imports stay lazy).

Aud3 owns thematic RCA; this adapter reads its one-way REST/A2A feed over an authenticated S2S
call. The auth SDK import lives INSIDE the method so the offline profiles import this module with
no cloud SDK installed and the managed family refuses under the offline gate. Read-only: there is
no write path back to Aud3.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.erm_models import Theme


class CloudThemeFeedAdapter:
    """Read Aud3's themes for a tenant over an authenticated S2S call."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def themes(self, tenant: str) -> tuple[Theme, ...]:  # pragma: no cover - needs live GCP
        import google.auth  # noqa: F401

        raise RuntimeError(
            "the managed Aud3 theme feed is not configured for this deployment; Aud3 is an "
            "unbuilt sibling and its read endpoint must be set (see docs/runbook.md)"
        )
