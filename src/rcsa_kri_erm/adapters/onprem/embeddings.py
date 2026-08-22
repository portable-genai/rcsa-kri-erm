"""On-prem EmbeddingsPort: fail-fast portability placeholder.

The client wires its own embedding endpoint behind this seam. It refuses at call time rather than
returning an empty map that a caller could mistake for a real embedding.
"""

from __future__ import annotations

from collections.abc import Mapping

from ...config import Settings


class OnPremEmbeddingsAdapter:
    """Satisfies EmbeddingsPort but refuses at call time: the client binds its own embedder."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def embed(self, texts: Mapping[str, str]) -> dict[str, tuple[float, ...]]:
        raise NotImplementedError(
            "on-prem embeddings is a portability placeholder: bind the client's own embedding "
            "endpoint (see docs/onprem-migration.md)"
        )
