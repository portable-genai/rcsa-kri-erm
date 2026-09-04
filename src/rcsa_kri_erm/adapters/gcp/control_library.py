"""GCP ControlLibraryPort: a remote READ of obligations-control-mapping's control-library surface
(imports stay lazy).

obligations-control-mapping is the system of record; this adapter reads its REST/A2A read API over
an authenticated service-to-service call. The auth SDK import lives INSIDE the method so the offline
profiles import this module with no cloud SDK installed and the managed family refuses under the
offline gate. There is deliberately NO write method: this repo keeps no control catalog of its own.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.erm_models import ControlRecord


class CloudControlLibraryAdapter:
    """Read obligations-control-mapping's control library for a tenant over an authenticated S2S
    call.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def list_controls(
        self, tenant: str
    ) -> tuple[ControlRecord, ...]:  # pragma: no cover - live GCP
        import google.auth  # noqa: F401 - presence proves the managed stack is installed

        raise RuntimeError(
            "the managed obligations-control-mapping read is not configured for this deployment; "
            "set the obligations-control-mapping read "
            "endpoint and S2S credentials (see docs/runbook.md)"
        )

    def get_control(
        self, control_id: str, tenant: str
    ) -> ControlRecord | None:  # pragma: no cover - live GCP
        import google.auth  # noqa: F401

        raise RuntimeError(
            "the managed obligations-control-mapping read is not configured for this deployment"
        )
