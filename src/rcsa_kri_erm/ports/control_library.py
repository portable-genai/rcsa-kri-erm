"""ControlLibraryPort: the READ boundary onto Rgc7's control library (the system of record).

Slice 1 of the Erm1 plan draws a load-bearing boundary: Rgc7 OWNS the obligation to policy to
control to evidence graph, and this repo keeps NO parallel control catalog. It reads controls
(and their latest Aud2 effectiveness, exposed as evidence nodes on Rgc7's graph) through this
port and keys its own RCSA ratings and assessments on Rgc7's ``control_id``.

The port is READ-ONLY on purpose: there is no method here that could write control-catalog
membership, so the no-catalog invariant is a property of the boundary rather than a rule a
reviewer has to enforce (``tests/contract/test_no_control_catalog.py`` proves it).

A profiled adapter family sits behind it: a remote read of Rgc7's REST/A2A surface under ``gcp``
(SDK imports lazy), a deterministic fixture library offline, and an on-prem fail-fast placeholder.

A read the adapter is not authorised to serve is a REFUSAL, never an empty result. An empty tuple
is a successful answer meaning "Rgc7 holds no controls for this tenant", and a caller cannot tell
that apart from "you may not read this tenant". Adapters raise
``domain.errors.TenantAccessDeniedError``, which every surface maps to HTTP 403.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.erm_models import ControlRecord


@runtime_checkable
class ControlLibraryPort(Protocol):
    def list_controls(self, tenant: str) -> tuple[ControlRecord, ...]:
        """Return the controls Rgc7 holds for ``tenant``. Never a write; never a local catalog.

        An empty tuple means Rgc7 holds no controls for a tenant this caller MAY read. A tenant
        it may not read, and a call that names no tenant at all, raise
        ``TenantAccessDeniedError`` instead.
        """
        ...

    def get_control(self, control_id: str, tenant: str) -> ControlRecord | None:
        """Return one control by Rgc7 id for ``tenant``, or ``None`` if Rgc7 holds no such id.

        ``None`` means no such id within a tenant this caller may read; a tenant it may not read
        raises ``TenantAccessDeniedError`` rather than reporting the id as absent.
        """
        ...
