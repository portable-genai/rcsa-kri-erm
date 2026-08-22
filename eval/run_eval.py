#!/usr/bin/env python3
"""Evaluation gate for RCSA, KRI and ERM Operating Copilot (Erm1).

Two named layers via ``--mode`` (the scaffold is ``agent_eval_kit.eval_main``):

* **smoke** (default) - the offline pre-merge check CI runs on every change: it drives the real
  ``TriageService`` against a golden set with SDK-free local adapters and scores two metrics.
* **gate** - the promotion verdict from the shared Hrz4 authority (requires the ``gcp``
  profile), via ``agent_eval_kit.PromotionGateClient``.

Exit is ``0`` iff every metric meets its threshold (and, in gate mode, the authority agrees).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterable, Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

from agent_eval_kit import EvalMetricResult, EvalReport, PromotionGateClient, eval_main
from pii_kit import pack_leak

from rcsa_kri_erm.adapters.local.audit import (
    LocalAuditAdapter,
)
from rcsa_kri_erm.adapters.local.embeddings import (
    LocalEmbeddingsAdapter,
)
from rcsa_kri_erm.adapters.local.generation import (
    LocalGenerationAdapter,
)
from rcsa_kri_erm.adapters.local.seed import (
    SEED_CONTROLS,
    SEED_THEMES,
)
from rcsa_kri_erm.adapters.local.tracer import (
    LocalNoopTracerAdapter,
)
from rcsa_kri_erm.config import (
    Settings,
)
from rcsa_kri_erm.domain.dedup import (
    propose_merges,
)
from rcsa_kri_erm.domain.erm_models import (
    BreachDirection,
    ControlEffectiveness,
    KriDefinition,
    MetricPoint,
    RcsaAssessment,
    RiskRating,
)
from rcsa_kri_erm.domain.erm_narration import (
    build_request,
    note_is_grounded,
    parse_note,
)
from rcsa_kri_erm.domain.kri import (
    breach_from_evaluation,
    evaluate_one,
)
from rcsa_kri_erm.domain.models import (
    TriageInput,
)
from rcsa_kri_erm.domain.pii import (
    PII_PATTERNS,
)
from rcsa_kri_erm.domain.rcsa import (
    ResidualRiskPolicy,
    residual_for_rating,
)
from rcsa_kri_erm.domain.themes import (
    reopen_decisions,
)
from rcsa_kri_erm.domain.triage_service import (
    TriageService,
)

_REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DATASET = _REPO_ROOT / "eval" / "datasets" / "golden_cases.jsonl"
_DATA = _REPO_ROOT / "eval" / "datasets"
RESIDUAL_DATASET = _DATA / "residual_oracle.jsonl"
KRI_DATASET = _DATA / "kri_oracle.jsonl"
REOPEN_DATASET = _DATA / "reopen_oracle.jsonl"
MERGE_DATASET = _DATA / "merge_oracle.jsonl"

THRESHOLDS: dict[str, float] = {
    "decision_accuracy": 0.80,
    "pii_safety": 0.99,
    "residual_accuracy": 0.99,
    "kri_threshold_exactness": 1.0,
    "merge_precision": 0.99,
    "reopen_accuracy": 0.99,
    "breach_narration_groundedness": 0.99,
}
#: The registered Hrz4 metric bundle for this vertical (Hrz4 owns the metrics + thresholds).
_BUNDLE = "rcsa-kri-erm"


def _load(path: Path) -> list[dict[str, str]]:
    cases: list[dict[str, str]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        cases.append(json.loads(line))
    if not cases:
        raise SystemExit(f"{path}: golden dataset is empty")
    return cases


def _load_rows(path: Path) -> list[dict[str, object]]:
    """Load a jsonl oracle whose rows carry mixed types (bools, ints, lists), not just strings."""
    rows: list[dict[str, object]] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    if not rows:
        raise SystemExit(f"{path}: oracle dataset is empty")
    return rows


def _mean(scores: list[float]) -> float:
    return round(sum(scores) / len(scores), 4) if scores else 0.0


def audit_texts(rows: Iterable[Mapping[str, Any]]) -> list[str]:
    """Every CONTENT-bearing field of every audit row, which is what a leak scan has to read.

    Collecting ``redacted_summary`` and nothing else would name the one field the
    redactor already masks: the metric would ask the redactor whether it had redacted, believe
    the answer, and report a green while the SAME record's citation snippet carries the
    identifier verbatim. Citations travel inside the record, and they carry raw source text in
    ``snippet`` and, routinely, in ``source_id`` (a locator built from a case subject or a
    control id).

    ``actor`` is excluded deliberately: it is the verified principal and an address by design, so
    a blanket scan over a whole row could never go green, and a metric nobody can make green
    gets deleted rather than fixed.
    """
    texts: list[str] = []
    for row in rows:
        texts.append(str(row.get("redacted_summary", "")))
        texts.append(json.dumps(row.get("citations", []), sort_keys=True))
    return texts


def pii_safety(records: Sequence[str], planted: Sequence[str]) -> float:
    """No identifier may survive into an audit record, by the pack rows OR by planted literal.

    Two oracles, because they fail independently: the pack scan uses the same rows the redactor
    masks with (so a redactor that skipped a field is caught), and the planted-literal check
    fires even if a pattern row is broken (so a pack that stopped matching is caught too).
    """
    pack_leaked = any(pack_leak(text, PII_PATTERNS) for text in records)
    literal_leaked = any(token in text for token in planted for text in records)
    return 0.0 if (pack_leaked or literal_leaked) else 1.0


def score_residual(rows: list[dict[str, object]]) -> float:
    """Engine residual score and band vs the INDEPENDENT hand-computed oracle."""
    policy = ResidualRiskPolicy()
    scores: list[float] = []
    for row in rows:
        rating = RiskRating(
            control_id=str(row["id"]),
            impact=int(str(row["impact"])),
            likelihood=int(str(row["likelihood"])),
            effectiveness=ControlEffectiveness(str(row["effectiveness"])),
        )
        residual = residual_for_rating(rating, policy)
        ok = (
            residual.inherent_score == int(str(row["expected_inherent"]))
            and residual.residual_score == int(str(row["expected_residual"]))
            and residual.band.value == str(row["expected_band"])
        )
        scores.append(1.0 if ok else 0.0)
    return _mean(scores)


def _kri_from_row(row: dict[str, object]) -> tuple[KriDefinition, tuple[MetricPoint, ...], str]:
    series = [float(v) for v in row["series"]]  # type: ignore[union-attr]
    key = str(row["metric_key"])
    points = tuple(MetricPoint(key, value, date(2026, 1 + i, 1)) for i, value in enumerate(series))
    as_of = str(points[-1].as_of)
    definition = KriDefinition(
        kri_id=str(row["id"]),
        category="eval",
        metric_key=key,
        direction=BreachDirection(str(row["direction"])),
        warning_threshold=float(str(row["warning"])),
        breach_threshold=float(str(row["breach"])),
        appetite_limit=float(str(row["breach"])),
        adopted=True,
    )
    return definition, points, as_of


def score_kri(rows: list[dict[str, object]]) -> float:
    """Engine band / breached / trend / consecutive vs the INDEPENDENT oracle, exact."""
    scores: list[float] = []
    for row in rows:
        definition, points, as_of = _kri_from_row(row)
        evaluation = evaluate_one(definition, points, as_of)
        if evaluation is None:
            scores.append(0.0)
            continue
        ok = (
            evaluation.band.value == str(row["expected_band"])
            and evaluation.breached == bool(row["expected_breached"])
            and evaluation.trend.value == str(row["expected_trend"])
            and evaluation.consecutive_breaches == int(str(row["expected_consecutive"]))
        )
        scores.append(1.0 if ok else 0.0)
    return _mean(scores)


def score_breach_groundedness(rows: list[dict[str, object]]) -> float:
    """The RAW local narrator over each breach's engine facts: every figure must be grounded."""
    generation = LocalGenerationAdapter(Settings(profile="local"))
    scores: list[float] = []
    for row in rows:
        definition, points, as_of = _kri_from_row(row)
        evaluation = evaluate_one(definition, points, as_of)
        if evaluation is None or not evaluation.breached:
            continue
        breach = breach_from_evaluation(definition, evaluation)
        if breach is None:  # pragma: no cover - breached implies a breach
            continue
        request = build_request(f"KRI {breach.kri_id}", breach.drivers, "Draft the breach note.")
        raw = generation.generate(request)
        note = parse_note(raw.text)
        grounded = note is not None and note_is_grounded(note, request.facts)
        scores.append(1.0 if grounded else 0.0)
    return _mean(scores)


def score_merge(rows: list[dict[str, object]]) -> float:
    """De-dup PRECISION: proposed pairs vs the independent golden duplicate-pair set."""
    embedder = LocalEmbeddingsAdapter(Settings(profile="local"))
    scores: list[float] = []
    for row in rows:
        tenant = str(row["tenant"])
        expected = {tuple(pair) for pair in row["expected_pairs"]}  # type: ignore[union-attr]
        controls = [c for c in SEED_CONTROLS if c.tenant == tenant]
        texts = {c.control_id: f"{c.title} {c.description}" for c in controls}
        vectors = embedder.embed(texts)
        proposed = {(c.left_id, c.right_id) for c in propose_merges(vectors)}
        if not proposed:
            scores.append(0.0)
            continue
        precision = len(proposed & expected) / len(proposed)
        scores.append(precision)
    return _mean(scores)


def score_reopen(rows: list[dict[str, object]]) -> float:
    """Engine reopen decisions vs the INDEPENDENT oracle over the seeded theme fixture."""
    tenant = "demo-bank"
    assessments = tuple(
        RcsaAssessment(control_id=str(row["control_id"]), tenant=tenant) for row in rows
    )
    decisions = {d.control_id: d.reopen for d in reopen_decisions(assessments, SEED_THEMES)}
    scores = [
        1.0 if decisions.get(str(row["control_id"])) == bool(row["expected_reopen"]) else 0.0
        for row in rows
    ]
    return _mean(scores)


def run_smoke(dataset: Path) -> EvalReport:
    cases = _load(dataset)
    settings = Settings(profile="local", audit_path=":memory:")
    audit = LocalAuditAdapter(settings)
    service = TriageService(audit, tracer=LocalNoopTracerAdapter(settings))

    decision_scores: list[float] = []
    for case in cases:
        result = service.triage(
            TriageInput(subject=case["subject"], text=case["text"]), actor="eval-bot"
        )
        decision_scores.append(1.0 if result.severity.value == case["expected_severity"] else 0.0)

    # pii_safety: no raw identifier may survive into any audit record. `audit_texts` decides
    # WHICH fields count as the record's content; see its docstring for why the summary alone is
    # not the record.
    records = audit_texts(audit.log.read_all())
    planted = [case["planted"] for case in cases if case.get("planted")]

    # The ERM vertical: each deterministic engine scored against its OWN independent, hand-computed
    # oracle (never the pipeline's own verdict), plus the raw narrator held to the engine figures.
    residual_rows = _load_rows(RESIDUAL_DATASET)
    kri_rows = _load_rows(KRI_DATASET)
    reopen_rows = _load_rows(REOPEN_DATASET)
    merge_rows = _load_rows(MERGE_DATASET)
    erm_examples = len(residual_rows) + len(kri_rows) + len(reopen_rows) + len(merge_rows)

    results = (
        EvalMetricResult.scored(
            "decision_accuracy", _mean(decision_scores), THRESHOLDS["decision_accuracy"]
        ),
        EvalMetricResult.scored(
            "pii_safety", pii_safety(records, planted), THRESHOLDS["pii_safety"]
        ),
        EvalMetricResult.scored(
            "residual_accuracy", score_residual(residual_rows), THRESHOLDS["residual_accuracy"]
        ),
        EvalMetricResult.scored(
            "kri_threshold_exactness", score_kri(kri_rows), THRESHOLDS["kri_threshold_exactness"]
        ),
        EvalMetricResult.scored(
            "merge_precision", score_merge(merge_rows), THRESHOLDS["merge_precision"]
        ),
        EvalMetricResult.scored(
            "reopen_accuracy", score_reopen(reopen_rows), THRESHOLDS["reopen_accuracy"]
        ),
        EvalMetricResult.scored(
            "breach_narration_groundedness",
            score_breach_groundedness(kri_rows),
            THRESHOLDS["breach_narration_groundedness"],
        ),
    )
    return EvalReport(dataset=str(dataset), results=results, n_examples=len(cases) + erm_examples)


def run_gate(dataset: Path) -> tuple[EvalReport, bool]:
    settings = Settings.load()
    if settings.profile != "gcp":
        raise SystemExit(
            "--mode gate is the promotion authority and requires "
            f"ERM_PROFILE=gcp (got {settings.profile!r}); "
            "run --mode smoke for the offline pre-merge check."
        )
    client = PromotionGateClient(
        os.environ.get("ERM_QUALITY_URL", "http://localhost:8084"),
        bundle=_BUNDLE,
        model="gemini-3.5-flash",
    )
    return client.evaluate(str(dataset)), client.gate(str(dataset))


if __name__ == "__main__":
    raise SystemExit(
        eval_main(
            smoke=run_smoke,
            gate=run_gate,
            default_dataset=DEFAULT_DATASET,
            description="Offline / Hrz4 evaluation gate for Erm1.",
        )
    )
