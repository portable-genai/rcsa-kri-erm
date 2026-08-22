"""GCP EmbeddingsPort: Vertex AI text embeddings (SDK imports stay lazy).

The de-dup engine is pure; this only supplies vectors. The Vertex import lives INSIDE the method so
the offline profiles import this module with no cloud SDK installed and the managed family refuses
under the offline gate.
"""

from __future__ import annotations

from collections.abc import Mapping

from ...config import Settings


class CloudEmbeddingsAdapter:
    """Embed control text through a managed Vertex AI embedding model."""

    _MODEL = "text-embedding-004"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def embed(
        self, texts: Mapping[str, str]
    ) -> dict[str, tuple[float, ...]]:  # pragma: no cover - needs live GCP
        from vertexai.language_models import TextEmbeddingModel

        model = TextEmbeddingModel.from_pretrained(self._MODEL)
        keys = list(texts)
        vectors = model.get_embeddings([texts[k] for k in keys])
        return {key: tuple(vec.values) for key, vec in zip(keys, vectors, strict=True)}
