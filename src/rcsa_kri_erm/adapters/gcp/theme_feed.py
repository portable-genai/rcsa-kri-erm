"""GCP ThemeFeedPort: a remote READ of issue-remediation-capa's theme feed (imports stay lazy).

issue-remediation-capa owns thematic RCA; this adapter reads its one-way REST/A2A feed over an
authenticated S2S call. The auth SDK import lives INSIDE the method so the offline profiles import
this module with no cloud SDK installed and the managed family refuses under the offline gate.
Read-only: there is no write path back to issue-remediation-capa.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.erm_models import Theme


class CloudThemeFeedAdapter:
    """Read issue-remediation-capa's themes for a tenant over an authenticated S2S call."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def themes(self, tenant: str) -> tuple[Theme, ...]:  # pragma: no cover - needs live GCP
        import google.auth  # noqa: F401

        raise RuntimeError(
            "the managed issue-remediation-capa theme feed is not configured for this deployment; "
            "issue-remediation-capa is an "
            "unbuilt sibling and its read endpoint must be set (see docs/runbook.md)"
        )
