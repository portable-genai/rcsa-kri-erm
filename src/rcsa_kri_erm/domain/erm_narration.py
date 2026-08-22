"""Narration: the model restates the engine's numbers, and never produces them.

Given a set of engine-owned facts (already computed by the deterministic engines in ``rcsa.py`` /
``kri.py``), this asks the generation port for a short note and holds it to two hard rules before
it is allowed out:

* **Schema validation, discard on failure.** The model must return JSON with a ``note`` key.
  Malformed output, or output missing the key, is discarded, not repaired.
* **Groundedness, discard on failure.** Every integer in the note must be one the engine actually
  produced (the facts). A note that invents a figure is discarded.

When a model note is discarded, a deterministic note built purely from the engine facts is used
instead, so a surface always has a grounded sentence and never a hallucinated one. The parsing and
groundedness checks are module-level pure functions, so the eval can measure RAW model output
through the very same contract the service enforces (a groundedness metric that watched only the
already-filtered service output could never go red).
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass

from ..ports.generation import GenerationPort, GenerationRequest

__all__ = [
    "NarratedNote",
    "NarrationService",
    "build_request",
    "fallback_text",
    "grounded_integers",
    "note_is_grounded",
    "parse_note",
]

_INT = re.compile(r"-?\d+")

_SYSTEM = (
    "You are a second-line operational-risk analyst assistant. You restate the risk figures you "
    "are given as a short committee-ready note. You never invent a number: use only the figures "
    "in the facts block."
)


@dataclass(frozen=True, slots=True)
class NarratedNote:
    """A note plus how it was produced."""

    text: str
    model_authored: bool
    grounded: bool


def grounded_integers(facts: tuple[tuple[str, str], ...]) -> set[str]:
    """Every integer token that appears in the engine-owned facts (the grounded number set)."""
    allowed: set[str] = set()
    for _key, value in facts:
        allowed.update(_INT.findall(value))
    return allowed


def note_is_grounded(text: str, facts: tuple[tuple[str, str], ...]) -> bool:
    """True when every integer in ``text`` is one the engine facts contain."""
    allowed = grounded_integers(facts)
    return all(token in allowed for token in _INT.findall(text))


def build_request(
    scope: str, facts: tuple[tuple[str, str], ...], instruction: str
) -> GenerationRequest:
    """The exact narration request the service sends, exposed so the eval can reuse it."""
    block = "\n".join(f"{key}={value}" for key, value in facts)
    prompt = (
        f"Scope: {scope}\n"
        f"Task: {instruction}\n"
        f"Facts (use ONLY these numbers):\n{block}\n"
        'Return JSON of the form {"note": "<one or two sentences>"}.'
    )
    return GenerationRequest(system=_SYSTEM, prompt=prompt, facts=facts, response_keys=("note",))


def parse_note(text: str) -> str | None:
    """Parse the model's raw text into the ``note`` string, or ``None`` if it is not valid."""
    try:
        parsed = json.loads(text.strip())
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(parsed, dict):
        return None
    note = parsed.get("note")
    if not isinstance(note, str) or not note.strip():
        return None
    return note.strip()


def fallback_text(scope: str, facts: tuple[tuple[str, str], ...]) -> str:
    """A deterministic, grounded-by-construction note built purely from the engine facts."""
    restated = "; ".join(f"{key}={value}" for key, value in facts)
    return f"{scope}: {restated}." if restated else f"{scope}: no figures to report."


class NarrationService:
    """Draft a grounded note for a set of engine facts."""

    def __init__(self, generation: GenerationPort) -> None:
        self._generation = generation

    def narrate(
        self, scope: str, facts: tuple[tuple[str, str], ...], instruction: str
    ) -> NarratedNote:
        request = build_request(scope, facts, instruction)
        try:
            response = self._generation.generate(request)
        except Exception:  # noqa: BLE001 - a narration failure must degrade, never crash a decision
            return NarratedNote(
                text=fallback_text(scope, request.facts), model_authored=False, grounded=True
            )

        note = parse_note(response.text)
        if note is None or not note_is_grounded(note, request.facts):
            return NarratedNote(
                text=fallback_text(scope, request.facts), model_authored=False, grounded=True
            )
        return NarratedNote(text=note, model_authored=True, grounded=True)
