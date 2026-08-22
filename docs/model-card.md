# Model card: RCSA, KRI and ERM Operating Copilot (Erm1)

This is a STARTER model card. It records the model boundary as built and the controls that must be
completed before a managed deployment. The deterministic engines are the system of record; the
models are bounded, replaceable components that write one note and produce one set of vectors.

Two model seams exist in this repo, and they are different in kind. The **generation** seam narrates
and changes no number. The **embeddings** seam feeds an engine, so it is the one place where
swapping a model can change what the system proposes; it is covered here for that reason.

## What the models do, and do not do

- **Generation does**: write a short committee-ready note that restates figures the engines have
  ALREADY computed. It receives a system instruction plus a facts block of engine-owned key and
  value pairs (`domain/erm_narration.build_request`) and returns JSON with a single `note` key.
- **Generation does NOT**: produce any residual score, RAG band, KRI evaluation, breach severity,
  merge candidate, reopen decision or escalation. Residual risk comes from
  `domain/rcsa.residual_for_assessment` over a frozen `ResidualRiskPolicy`; KRI banding, trend and
  the additive breach-severity score come from `domain/kri.py` over a frozen `KriPolicy`; merge
  candidates come from cosine arithmetic in `domain/dedup.py`; reopens come from
  `domain/themes.reopen_decisions`. All of it is pure stdlib, and `tests/unit/test_erm_engines.py`
  pins the arithmetic. With the local stub narrator bound, every consequential field is identical,
  so a model change cannot move a figure.
- **Embeddings do**: turn control text into vectors, and nothing else. The de-dup engine that reads
  them is pure arithmetic and never learns which embedder produced them.
- **Embeddings do NOT**: decide a merge. `propose_merges` only ever PROPOSES pairs above the
  similarity floor, and every proposal is routed to Hrz7 because a merge collapses two risk lines.
  A different embedder can change which pairs are proposed, which is exactly why the floor is
  calibrated to the bound embedder and why no merge is ever applied automatically.

## Boundary and validation

- The narrator is reachable through exactly one port, `ports/generation.py`, whose whole surface is
  `generate(request) -> GenerationResponse`. There is no second narration seam.
- The reply is held to two hard rules before it is allowed out (`domain/erm_narration.py`):
  **schema validation**, so `parse_note` returns `None` for anything that is not a JSON object with
  a non-empty string `note`, rather than repairing it; and **groundedness**, so `note_is_grounded`
  requires every integer in the note to be one the engine facts contain. A note that invents a
  figure is discarded.
- When a note is discarded, or the narrator raises, `fallback_text` builds a deterministic note
  purely from the engine facts, so a surface always has a grounded sentence and never a
  hallucinated one. `NarratedNote` carries `model_authored` and `grounded`, so the caller can tell
  the two paths apart rather than guessing.
- The parsing and groundedness checks are module-level pure functions rather than private methods,
  deliberately: the `breach_narration_groundedness` eval metric measures the RAW narrator output
  through the very same contract the service enforces. A metric that watched only the
  already-filtered service output could never go red.
- Only ACCEPTED ratings score. `RcsaAssessment` separates `proposed_ratings` from
  `accepted_ratings`, and `residual_for_assessment` reads only the accepted set, so a model-drafted
  proposal moves no number until a maker signs it off through Hrz7.
- Personal data is masked before the audit write, before an outbound review payload and before a
  tool result can enter a model's context (`domain/pii.py`, `adapters/_review_payload.py`,
  `agent/tools.py`).
- Every consequential outcome sets `requires_human_review` and is routed to Hrz7 (rule R8) in the
  same call: an assessment at or above the review band, every proposed merge, every KRI breach and
  every theme-driven reopen. `tests/unit/test_review_routing.py` asserts the routing rather than the
  flag, and a CRITICAL band demands two approvals rather than one
  (`adapters/_review_payload.py`).

## Adapters and profiles

| Profile | Generation adapter | Behaviour |
|---|---|---|
| `local` | `adapters/local/generation.py` | Deterministic stub: restates the request's engine facts as a JSON note. Grounded by construction, SDK-free, no network. A silent empty return would let a producer ship the narration seam unwired, so it emits a real, inspectable note. |
| `gcp` | `adapters/gcp/generation.py` | Gemini via `google.generativeai`, imported lazily inside the method. Model id pinned in the adapter as `_MODEL`, currently `gemini-3.5-flash`, with `response_mime_type=application/json`, `temperature=0.2` and a caller-supplied `max_output_tokens`. |
| `onprem` | `adapters/onprem/generation.py` | Fail-fast placeholder: refuses at call time rather than pretending to narrate, so a placeholder never becomes a silent no-op on the one path where an empty answer would look like a working narrator. |

| Profile | Embeddings adapter | Behaviour |
|---|---|---|
| `local` | `adapters/local/embeddings.py` | A deterministic bag-of-tokens hashing embedder over 64 dimensions, SHA1 per token, sign-folded and L2-normalised. Not semantic, but replayable: the same text always yields the same vector, so the whole de-dup pipeline replays byte for byte. |
| `gcp` | `adapters/gcp/embeddings.py` | Vertex AI text embeddings via `vertexai.language_models.TextEmbeddingModel`, imported lazily. Model id pinned in the adapter as `_MODEL`, currently `text-embedding-004`. |
| `onprem` | `adapters/onprem/embeddings.py` | Fail-fast placeholder: refuses rather than returning an empty map a caller could mistake for a real embedding. |

Both managed adapters execute real calls, so neither appears in
`managed_readiness.INCOMPLETE_MANAGED_OPERATIONS`. What does appear there, and therefore blocks a
managed boot until it is implemented, is the Rgc7 control-library read, the BigQuery metric feed
and the Aud3 theme feed.

## What the eval actually measures

`eval/run_eval.py --mode smoke` scores seven metrics: `decision_accuracy` (0.80), `pii_safety`
(0.99), `residual_accuracy` (0.99), `kri_threshold_exactness` (1.0), `merge_precision` (0.99),
`reopen_accuracy` (0.99) and `breach_narration_groundedness` (0.99). Each engine metric is scored
against an INDEPENDENT oracle dataset in `eval/datasets/` rather than against the pipeline's own
verdict, and five of the seven are proved able to report something else by planted mutants
(`tests/unit/test_erm_not_falsely_green.py` for the four engine metrics,
`tests/unit/test_not_falsely_green.py` for `pii_safety`). `decision_accuracy` and
`breach_narration_groundedness` have no planted mutant yet.

Read `breach_narration_groundedness` precisely: it drives the RAW local narrator over each breach's
engine facts and checks the result through `parse_note` plus `note_is_grounded`. That is a real
measurement of the contract, but the narrator it measures is the deterministic stub, which is
grounded by construction. It cannot tell you how a real Gemini reply behaves.

## Remaining controls (TODO, repo owner)

- **Model id, version and region** (P-07): `gemini-3.5-flash` and `text-embedding-004` are pinned
  defaults in the adapters, not confirmed deployment decisions. Both are regional, and an
  unavailable id fails at call time rather than at boot, so confirm each is served in your
  deployment region, pin the exact version, and record it here before a managed deploy.
- **Re-calibrate the de-dup floor for the bound embedder.** `DEFAULT_SIMILARITY_FLOOR` is 0.5,
  calibrated to the offline hashing embedder, which separates a near-duplicate pair at roughly 0.67
  from unrelated controls below 0.15. A semantic embedder lives in a much tighter cosine space, so
  the same floor would propose far more pairs. Switching to Vertex without re-calibrating is a
  precision regression that the offline gate cannot see, because the gate never binds Vertex. Note
  that the floor is not reachable from the service today: `propose_merges` accepts a `floor`, but
  `ErmService.propose_control_merges` calls it without one, so re-calibrating means editing the
  constant or threading a floor through the service.
- **Budget, rate limit and a kill switch** (P-10, P-11): `max_output_tokens` is per request and
  there is no per-tenant token budget, no request rate limit, and no switch that forces
  deterministic-only operation. The fallback path already exists, since a discarded or failed note
  yields the deterministic text, but nothing yet lets an operator disable the model deliberately.
  The embeddings seam has no budget either, and it is called once per control on every merge
  proposal.
- **Evaluation of the live models**: the offline eval scores the deterministic pipeline with the
  stub narrator and the hashing embedder. Add a managed-profile run, registered with the Hrz4
  promotion gate (P-08, rule R5), that scores `breach_narration_groundedness` with the real model
  bound and `merge_precision` with the real embedder bound.
- **Prompt-injection screening** (rule R1): the Hrz1 guardrail gateway is not bound. Screen any
  untrusted free text that reaches the facts block, and fail closed to deterministic-only when the
  screen is unavailable. The exposure is small today, because the facts block carries engine
  integers, and it grows the moment control descriptions or theme narratives from an external
  source are passed through. Control text also reaches the EMBEDDER, which is a data path worth
  screening in its own right.
- **Reasoning trace**: the audit record carries the validated note and its provenance, not the
  prompt and reply pair. `COMPLIANCE.md` P-07 records that as owed.

Until these are complete the system is safe to run offline (deterministic engines plus the stub
narrator and the hashing embedder) and the managed model paths are not production-cleared.
