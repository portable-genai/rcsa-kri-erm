"""Domain errors that carry an HTTP-mappable meaning without importing a web framework.

The domain stays pure stdlib; these are plain exceptions the surfaces map to status codes.
"""

from __future__ import annotations


class TenantAccessDeniedError(PermissionError):
    """A caller asked a port for a partition it is not the tenant of, or named no tenant at all.

    Mapped to HTTP 403 by every surface. It exists because the alternative shape is worse than a
    wrong status code: a cross-tenant read returning an EMPTY TUPLE is a successful
    answer indistinguishable from a legitimate "this tenant has no controls". The service then
    computed a verdict over nothing and reported it as a finding ("no merge candidates", "no
    theme names this control"), so an isolation failure and a clean result looked the same to
    every caller, every log line and every reviewer.

    403 rather than 404 is deliberate: the records EXIST and this caller may not have them, and
    404 would make the partition probeable with a tenant-name generator.

    The EMPTY tenant lands here too. No tenant named is no authority to read, and substituting a
    default is precisely how the agent surface came to read the seeded bank's partition for a
    caller who named nobody.
    """
