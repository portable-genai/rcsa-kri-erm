"""Local MetricFeedPort: the seeded KRI feed of the demo bank (SDK-free, deterministic).

Stands in for a BigQuery read of the metric feed. It filters the in-memory fixture to the requested
metric keys and to points on or before ``as_of``, so a historical replay never sees a later
observation.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.erm_models import MetricPoint
from .seed import SEED_METRICS


class LocalMetricFeedAdapter:
    """Serve seeded metric points for the requested keys, bounded by ``as_of``."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def fetch(self, metric_keys: tuple[str, ...], as_of: str) -> tuple[MetricPoint, ...]:
        wanted = set(metric_keys)
        return tuple(p for p in SEED_METRICS if p.metric_key in wanted and str(p.as_of) <= as_of)
