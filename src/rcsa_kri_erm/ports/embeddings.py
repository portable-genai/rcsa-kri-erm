"""EmbeddingsPort: the vector boundary for control de-duplication and taxonomy matching.

The de-dup ENGINE (``domain/dedup.py``) is pure arithmetic over vectors; this port is where the
vectors come from. Under ``gcp`` it is Vertex AI text embeddings (SDK imports lazy); offline it is
a deterministic hashing embedder so the same text always yields the same vector and the whole
de-dup pipeline replays byte-for-byte; on-premises it fails fast until the client binds its own
embedder.

The port returns a mapping keyed by the caller's own ids, so the engine can propose merges without
ever knowing which embedder produced the vectors.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Protocol, runtime_checkable


@runtime_checkable
class EmbeddingsPort(Protocol):
    def embed(self, texts: Mapping[str, str]) -> dict[str, tuple[float, ...]]:
        """Embed each ``id -> text`` into a fixed-length vector, returning ``id -> vector``.

        Every vector in one call has the same length. A failure to reach the embedder is a raised
        error (managed) or ``NotImplementedError`` (on-prem placeholder), never a silent empty map.
        """
        ...
