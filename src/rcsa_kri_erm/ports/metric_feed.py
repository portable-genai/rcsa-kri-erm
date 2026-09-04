"""MetricFeedPort: the KRI/KCI metric feed boundary.

Slice 3 of the rcsa-kri-erm plan ingests observed metric values and evaluates them against adopted
KRI thresholds. This port supplies the feed: BigQuery under ``gcp`` (SDK imports lazy), a
deterministic CSV fixture offline, and an on-prem fail-fast placeholder. The threshold and trend
ENGINE (``domain/kri.py``) is pure and never touches this port; it is handed the points the port
returned.

The read is scoped by ``as_of`` so a replay is pinned to a stated evaluation date and a later
observation cannot leak into a historical evaluation.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from ..domain.erm_models import MetricPoint


@runtime_checkable
class MetricFeedPort(Protocol):
    def fetch(self, metric_keys: tuple[str, ...], as_of: str) -> tuple[MetricPoint, ...]:
        """Return observed points for ``metric_keys`` on or before ``as_of`` (ISO date string).

        Ordering is not guaranteed by the port; the engine sorts. A failure to reach the feed is a
        raised error (managed) or ``NotImplementedError`` (on-prem), never a silent empty tuple.
        """
        ...
