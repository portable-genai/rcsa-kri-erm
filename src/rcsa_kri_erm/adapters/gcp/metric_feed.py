"""GCP MetricFeedPort: a BigQuery read of the KRI metric feed (SDK imports stay lazy).

The threshold/trend engine is pure; this only supplies points. The BigQuery import lives INSIDE the
method so the offline profiles import this module with no cloud SDK installed and the managed
family refuses under the offline gate.
"""

from __future__ import annotations

from ...config import Settings
from ...domain.erm_models import MetricPoint


class CloudMetricFeedAdapter:
    """Read observed metric points from BigQuery, bounded by ``as_of``."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def fetch(
        self, metric_keys: tuple[str, ...], as_of: str
    ) -> tuple[MetricPoint, ...]:  # pragma: no cover - needs live GCP
        from google.cloud import bigquery  # noqa: F401

        raise RuntimeError(
            "the managed KRI feed is not configured for this deployment; set the BigQuery "
            "dataset and table for the metric feed (see docs/runbook.md)"
        )
