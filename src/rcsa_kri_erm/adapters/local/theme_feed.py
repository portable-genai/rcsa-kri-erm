"""Local ThemeFeedPort: the frozen Aud3 theme fixture (SDK-free).

Aud3 is not built, so this is the RECORDED CONTRACT of its one-way theme feed: the shape a remote
adapter will read once Aud3 ships. It is read-only (the port has no write path) and serves the demo
bank's themes.

A read for any OTHER tenant is REFUSED, not answered. Returning an empty tuple leaves the reopen
engine deciding every assessment over an empty theme set and reporting "no theme names this
control" as a finding, which is a verdict computed over nothing. The port requires that a caller
never get a silent empty tuple it could read as "no themes", and all three adapter families agree
on that. See ``domain/errors.py``.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.erm_models import Theme
from ...domain.errors import TenantAccessDeniedError
from .seed import SEED_TENANT, SEED_THEMES


class LocalThemeFeedAdapter:
    """Serve the frozen Aud3 theme fixture for the owning tenant; refuse any other."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def themes(self, tenant: str) -> tuple[Theme, ...]:
        if tenant != SEED_TENANT:
            raise TenantAccessDeniedError(
                f"this theme feed serves tenant {SEED_TENANT!r} only; refusing a read for "
                f"{tenant!r} rather than answering it with an empty theme set"
            )
        return SEED_THEMES
