"""Local EmbeddingsPort: a deterministic hashing embedder (SDK-free, replayable).

It stands in for Vertex AI text embeddings. The same text always yields the same vector, so the
de-dup pipeline replays byte-for-byte offline. It is a bag-of-tokens hashing embedder: not a
semantic model, but deterministic and good enough that near-identical control descriptions land
close together, which is all the offline demo and the de-dup eval need.
"""

from __future__ import annotations

import hashlib
import math
import re
from collections.abc import Mapping

from ...config import Settings

_DIM = 64
_TOKEN = re.compile(r"[a-z0-9]+")


def _embed_text(text: str) -> tuple[float, ...]:
    vector = [0.0] * _DIM
    for token in _TOKEN.findall(text.lower()):
        digest = hashlib.sha1(token.encode("utf-8")).digest()
        index = digest[0] % _DIM
        sign = 1.0 if digest[1] % 2 == 0 else -1.0
        vector[index] += sign
    norm = math.sqrt(sum(v * v for v in vector))
    if norm == 0.0:
        return tuple(vector)
    return tuple(v / norm for v in vector)


class LocalEmbeddingsAdapter:
    """Deterministic hashing embedder: no model, no network, same text -> same vector."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def embed(self, texts: Mapping[str, str]) -> dict[str, tuple[float, ...]]:
        return {key: _embed_text(value) for key, value in texts.items()}
