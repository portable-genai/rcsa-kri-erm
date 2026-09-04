"""On-prem ControlLibraryPort: fail-fast portability placeholder.

The client wires its own read of the control system of record (its obligations-control-mapping
deployment or an equivalent) behind this seam. Read-only, and it refuses at call time rather than
returning an empty library that a caller could mistake for "no controls".
"""

from __future__ import annotations

from ...config import Settings
from ...domain.erm_models import ControlRecord


class OnPremControlLibraryAdapter:
    """Satisfies ControlLibraryPort but refuses at call time: the client binds its own read."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def list_controls(self, tenant: str) -> tuple[ControlRecord, ...]:
        raise NotImplementedError(
            "on-prem control-library read is a portability placeholder: bind the client's own "
            "control system of record (see docs/onprem-migration.md)"
        )

    def get_control(self, control_id: str, tenant: str) -> ControlRecord | None:
        raise NotImplementedError(
            "on-prem control-library read is a portability placeholder "
            "(see docs/onprem-migration.md)"
        )
