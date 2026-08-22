"""On-prem GenerationPort: fail-fast portability placeholder.

The client wires its own model endpoint behind this seam. Until then it refuses at call time
rather than pretending to narrate, so a placeholder never becomes a silent no-op.
"""

from __future__ import annotations

from ...config import Settings
from ...ports.generation import GenerationRequest, GenerationResponse


class OnPremGenerationAdapter:
    """Satisfies GenerationPort but refuses at call time: the client binds its own model."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        raise NotImplementedError(
            "on-prem generation is a portability placeholder: bind the client's own model "
            "endpoint (see docs/onprem-migration.md)"
        )
