"""Local ControlLibraryPort: the seeded control library of the demo bank (SDK-free).

Stands in for a remote read of obligations-control-mapping's control library. It is READ-ONLY (the
port has no write method), so this repo keeps no catalog of its own even in the offline profile: the
fixture IS obligations-control-mapping's library for the demo tenant.

A read for any OTHER tenant is REFUSED, not answered. Returning an empty tuple is a successful
answer indistinguishable from a legitimate "obligations-control-mapping holds no controls for this
tenant": the de-dup sweep embeds nothing, proposes nothing and reports "no merge candidates" as a
finding, so an isolation failure and a clean library look identical to every caller and every log
line. See ``domain/errors.py``.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.erm_models import ControlRecord
from ...domain.errors import TenantAccessDeniedError
from .seed import SEED_CONTROLS, SEED_TENANT


class LocalControlLibraryAdapter:
    """Serve the seeded controls for the owning tenant; refuse any other tenant."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def list_controls(self, tenant: str) -> tuple[ControlRecord, ...]:
        self._authorise(tenant)
        return tuple(c for c in SEED_CONTROLS if c.tenant == tenant)

    def get_control(self, control_id: str, tenant: str) -> ControlRecord | None:
        self._authorise(tenant)
        for control in SEED_CONTROLS:
            if control.control_id == control_id and control.tenant == tenant:
                return control
        return None

    @staticmethod
    def _authorise(tenant: str) -> None:
        """Refuse before reading. The empty tenant is refused for the same reason a wrong one is.

        No tenant named is no authority to read, and substituting a default is how the agent
        surface came to act on the seeded bank's partition for a caller who named nobody.
        """
        if tenant != SEED_TENANT:
            raise TenantAccessDeniedError(
                f"this control library serves tenant {SEED_TENANT!r} only; refusing a read for "
                f"{tenant!r} rather than answering it with an empty library"
            )
