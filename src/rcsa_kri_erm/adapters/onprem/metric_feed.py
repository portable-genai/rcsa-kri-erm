"""On-prem MetricFeedPort: fail-fast portability placeholder.

The client wires its own metric warehouse behind this seam. It refuses at call time rather than
returning an empty feed that a caller could mistake for "no observations".
"""

from __future__ import annotations

from ...config import Settings
from ...domain.erm_models import MetricPoint


class OnPremMetricFeedAdapter:
    """Satisfies MetricFeedPort but refuses at call time: the client binds its own feed."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def fetch(self, metric_keys: tuple[str, ...], as_of: str) -> tuple[MetricPoint, ...]:
        raise NotImplementedError(
            "on-prem metric feed is a portability placeholder: bind the client's own metric "
            "warehouse (see docs/onprem-migration.md)"
        )
