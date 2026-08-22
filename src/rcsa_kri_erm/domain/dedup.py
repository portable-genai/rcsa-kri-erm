"""Control de-duplication: propose merge candidates from embeddings, above a config floor.

Slice 1 of the Erm1 plan. The embeddings themselves come from a port (Vertex under ``gcp``, a
deterministic hashing embedder offline); this module is PURE arithmetic over the vectors it is
handed. Cosine similarity is deterministic, so the same control set always proposes the same
candidates.

A merge is CONSEQUENTIAL: it collapses two risk lines into one. So the engine only ever
*proposes* candidates above the floor; accepting a merge routes to Hrz7 (rule R8). Nothing here
imports a framework, a cloud SDK or the port.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

from .erm_models import MergeCandidate

__all__ = ["DEFAULT_SIMILARITY_FLOOR", "cosine_similarity", "propose_merges"]

#: Reference cosine-similarity floor above which two controls are proposed as duplicates. The
#: value is calibrated to the BOUND embedder: the offline deterministic hashing embedder separates
#: a near-duplicate pair (~0.67) from unrelated controls (<0.15) with wide margin, so 0.5 catches
#: the duplicates and nothing else. A semantic embedder (Vertex under ``gcp``) lives in a tighter
#: space and would raise this; it is config-owned (B4), never a constant a caller cannot move.
DEFAULT_SIMILARITY_FLOOR = 0.5


def cosine_similarity(left: tuple[float, ...], right: tuple[float, ...]) -> float:
    """Cosine similarity of two equal-length vectors; 0.0 when either is a zero vector."""
    if len(left) != len(right):
        raise ValueError("cosine_similarity needs equal-length vectors")
    dot = sum(a * b for a, b in zip(left, right, strict=True))
    left_norm = math.sqrt(sum(a * a for a in left))
    right_norm = math.sqrt(sum(b * b for b in right))
    if left_norm == 0.0 or right_norm == 0.0:
        return 0.0
    return dot / (left_norm * right_norm)


def propose_merges(
    embeddings: Mapping[str, tuple[float, ...]],
    floor: float = DEFAULT_SIMILARITY_FLOOR,
) -> tuple[MergeCandidate, ...]:
    """Propose every control pair whose cosine similarity is at or above ``floor``.

    The output is ordered by descending similarity, then by the pair of ids, so the proposal set
    is stable across runs. Ids are compared so each unordered pair is considered once, and the
    candidate always carries them in sorted order.
    """
    ids = sorted(embeddings)
    candidates: list[MergeCandidate] = []
    for i, left_id in enumerate(ids):
        for right_id in ids[i + 1 :]:
            score = cosine_similarity(embeddings[left_id], embeddings[right_id])
            if score >= floor:
                candidates.append(
                    MergeCandidate(left_id=left_id, right_id=right_id, similarity=round(score, 6))
                )
    candidates.sort(key=lambda c: (-c.similarity, c.left_id, c.right_id))
    return tuple(candidates)
