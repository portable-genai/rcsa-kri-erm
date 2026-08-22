"""GCP GenerationPort: Gemini narration (SDK imports stay lazy).

The model is used for narration only; the consequential numbers are computed by the deterministic
engine and merely restated here. The Gemini SDK import lives INSIDE the method so the
``local``/``onprem`` profiles import this module with no cloud SDK installed, and the managed
family REFUSES under the offline gate (the import raises) rather than answering.
"""

from __future__ import annotations

from ...config import Settings
from ...ports.generation import GenerationRequest, GenerationResponse


class CloudGenerationAdapter:
    """Narrate through a managed Gemini model."""

    _MODEL = "gemini-3.5-flash"

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def generate(
        self, request: GenerationRequest
    ) -> GenerationResponse:  # pragma: no cover - needs live GCP
        import google.generativeai as genai

        model = genai.GenerativeModel(self._MODEL, system_instruction=request.system)
        completion = model.generate_content(
            request.prompt,
            generation_config={
                "response_mime_type": "application/json",
                "max_output_tokens": request.max_output_tokens,
                "temperature": 0.2,
            },
        )
        return GenerationResponse(text=completion.text or "", model=self._MODEL)
