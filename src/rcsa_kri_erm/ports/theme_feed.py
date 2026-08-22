"""ThemeFeedPort: the one-way READ boundary onto Aud3's thematic-analysis feed.

Slice 4 of the Erm1 plan consumes Aud3 themes as a risk signal. The boundary is deliberately
read-only: Aud3 owns thematic RCA and this repo never writes back, so there is no method here that
could. Aud3 is not yet built, so the offline family serves a FROZEN fixture whose shape is pinned
by a fixture contract test (``tests/contract/test_theme_feed_contract.py``); when Aud3 ships, the
remote adapter reads its live REST/A2A feed and the fixture stays as the recorded contract.

Under ``gcp`` the remote adapter reads Aud3's feed (SDK/HTTP imports lazy); offline it is the
frozen fixture; on-premises it fails fast.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.erm_models import Theme


@runtime_checkable
class ThemeFeedPort(Protocol):
    def themes(self, tenant: str) -> tuple[Theme, ...]:
        """Return Aud3's current themes for ``tenant``. Read-only: there is no write path.

        A failure to reach the feed is a raised error (managed) or ``NotImplementedError``
        (on-prem placeholder), never a silent empty tuple that a caller could read as "no themes".

        A tenant this adapter may not serve follows the same rule. Answering it with ``()``
        would leave the reopen engine deciding over an empty theme set and reporting "no theme
        names this control" as a finding, so it raises
        ``domain.errors.TenantAccessDeniedError``, which every surface maps to HTTP 403.
        """
        ...
