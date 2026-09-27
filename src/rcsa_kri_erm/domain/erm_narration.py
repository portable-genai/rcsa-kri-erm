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

Rule R1: the guardrail screens BOTH directions of the one generation call this service makes.
INPUT, before the model is called at all: the scope (the one field a caller writes, since it
carries the control or KRI id) on its own, then the whole prompt the model reads, rendered from the
screened scope. The request sent is that screened prompt exactly as the screen returned it. OUTPUT:
the parsed note, before the groundedness check may accept it, and the screened text is what goes
forward. Narration is optional and never consequential (the engines own every band and score), so
a refusal here, a block or a guardrail that could not decide, drops the model note like any other
narration failure: it is audited ``Decision.BLOCKED`` and the deterministic note stands. The
decision it narrates is never blocked, and no partial model note is ever kept.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, replace

from ..ports.audit import AuditSinkPort
from ..ports.generation import GenerationPort, GenerationRequest
from ..ports.guardrail import GuardrailPort
from .kernel import AuditEvent, Decision, Direction, GuardrailVerdict, Severity, utcnow

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
    """A note plus how it was produced.

    ``blocked`` is True when the guardrail refused either direction of the narration call (rule
    R1); the text is then the deterministic note, and the refusal is already in the audit trail.
    """

    text: str
    model_authored: bool
    grounded: bool
    blocked: bool = False


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
    # Free (no temperature sent): a drafted note. The grounding check, not the sampler, bounds it.
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


class _Refused(Exception):
    """A screen refused (and audited) one direction; the model note is dropped."""


class NarrationService:
    """Draft a grounded, guardrail-screened note for a set of engine facts."""

    def __init__(
        self, generation: GenerationPort, *, guardrail: GuardrailPort, audit: AuditSinkPort
    ) -> None:
        self._generation = generation
        # REQUIRED, like the tracer on the services: a default would let a surface construct a
        # narrator that sends unscreened prompts, and nothing would look wrong.
        self._guardrail = guardrail
        self._audit = audit

    def narrate(
        self,
        scope: str,
        facts: tuple[tuple[str, str], ...],
        instruction: str,
        *,
        action: str,
        actor: str,
        severity: Severity,
    ) -> NarratedNote:
        """Narrate ``facts``, screened both directions (rule R1), or fall back deterministically.

        ``action``, ``actor`` and ``severity`` are only what a ``Decision.BLOCKED`` audit record
        needs when a screen refuses: the outcome being narrated, who asked, and its engine band.
        """
        fallback = NarratedNote(
            text=fallback_text(scope, facts), model_authored=False, grounded=True
        )
        audit = (action, actor, severity)
        try:
            screened_scope = self._screen(scope, Direction.INPUT, audit)
            request = build_request(screened_scope, facts, instruction)
            request = replace(request, prompt=self._screen(request.prompt, Direction.INPUT, audit))
        except _Refused:
            return replace(fallback, blocked=True)

        try:
            response = self._generation.generate(request)
        except Exception:  # noqa: BLE001 - a narration failure must degrade, never crash a decision
            return fallback

        note = parse_note(response.text)
        if note is None:
            return fallback
        try:
            note = self._screen(note, Direction.OUTPUT, audit)
        except _Refused:
            return replace(fallback, blocked=True)
        if not note.strip() or not note_is_grounded(note, request.facts):
            return fallback
        return NarratedNote(text=note, model_authored=True, grounded=True)

    def _screen(self, text: str, direction: Direction, audit: tuple[str, str, Severity]) -> str:
        """Screen one text in one direction: the text to use from here on, or :class:`_Refused`.

        The returned text is the verdict's ``sanitized_text`` exactly as given. A block, or a
        guardrail that raised instead of deciding (fail closed), is audited BLOCKED first and then
        refused. An audit write that itself fails propagates: the WORM trail is mandatory, the
        narration is not.
        """
        try:
            verdict: GuardrailVerdict = self._guardrail.screen(text, direction)
        except Exception as exc:  # noqa: BLE001 - an undecided screen is a refusal, not a pass
            self._audit_block(direction, f"guardrail unavailable ({type(exc).__name__})", audit)
            raise _Refused from exc
        if not verdict.allowed or verdict.sanitized_text is None:
            self._audit_block(direction, verdict.reason or "blocked by guardrail", audit)
            raise _Refused
        return verdict.sanitized_text

    def _audit_block(
        self, direction: Direction, reason: str, audit: tuple[str, str, Severity]
    ) -> None:
        """Audit a guardrail refusal on the narration call (rules R1 and R2).

        Never carries the refused text, not even the scope, which is caller-written: only that a
        refusal happened, on which outcome, in which direction, and why. A refused attempt is a
        security-relevant event the WORM trail must hold even though the outcome itself proceeds
        on its deterministic note.
        """
        action, actor, severity = audit
        self._audit.record(
            AuditEvent(
                action=action,
                actor=actor,
                decision=Decision.BLOCKED,
                severity=severity,
                redacted_summary=f"{action}: narration blocked ({direction.value}): {reason}",
                citations=(),
                timestamp=utcnow(),
            )
        )
