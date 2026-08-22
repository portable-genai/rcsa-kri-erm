"""Local GenerationPort: a deterministic, SDK-free narrator for the offline profile.

It stands in for a managed model in the gate, the tests and the demo. It never decides anything:
it restates the engine-owned facts it is handed as a short JSON note, so its output is grounded by
construction and the whole offline pipeline (including the narration path) runs with no network and
no cloud SDK. A silent empty return would let a producer ship the narration seam unwired, so this
deliberately produces a real, inspectable note.
"""

from __future__ import annotations

import json

from ...config import Settings
from ...ports.generation import GenerationRequest, GenerationResponse


class LocalGenerationAdapter:
    """Restate the request's engine facts as a deterministic JSON note (no model, no network)."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(self, request: GenerationRequest) -> GenerationResponse:
        restated = "; ".join(f"{key}={value}" for key, value in request.facts)
        note = f"Restating engine figures: {restated}." if restated else "No figures to restate."
        return GenerationResponse(text=json.dumps({"note": note}), model="local-deterministic")
