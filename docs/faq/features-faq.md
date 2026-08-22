# Features FAQ

For a product owner, a risk lead or a delivery manager deciding what this system does, what it
refuses to do, and where its responsibility ends.

### What does it actually do?

It operates the second-line ERM cycle over a control library it READS rather than owns. Four
deterministic engines and one narrated step:

1. **Residual risk** (`domain/rcsa.py`): given an RCSA assessment's ACCEPTED ratings, it computes a
   residual score per rating and the worst RAG band across them, using a frozen bank-owned
   `ResidualRiskPolicy`. Effectiveness reduces likelihood, never impact, and residual likelihood is
   floored at 1, so a control can never zero out a risk.
2. **KRI and KCI evaluation** (`domain/kri.py`): observed points from the metric feed are banded
   GREEN, AMBER or RED against each ADOPTED definition's warning and breach thresholds, respecting
   whether the threshold is an upper or a lower bound. Trend is the latest point against the
   previous one at an explicit `as_of`. Breach severity is an additive named-driver score, threshold
   distance plus trend plus persistence, banded by policy.
3. **Control de-duplication** (`domain/dedup.py`): cosine similarity over vectors from the
   embeddings port proposes merge candidates above a config-owned floor.
4. **Theme-driven reopens** (`domain/themes.py`): an Aud3 theme attaches to an assessment when it
   names that assessment's control, and forces a reopen when its weight reaches the policy floor.

Narration sits on top and computes nothing.

### What makes a residual score defensible?

Three rules in the engines, all pure code:

- **Only accepted ratings score.** `residual_for_assessment` reads `accepted_ratings` and never
  `proposed_ratings`, so a model-drafted or maker-drafted proposal moves no number until a checker
  signs it off through Hrz7. An assessment carrying only proposals scores as if it had none, and the
  tests pin that.
- **Only adopted KRI definitions evaluate.** A proposed threshold is inert until a human adopts it.
- **The bands are computed from a named policy.** `ResidualRiskPolicy` and `KriPolicy` are frozen
  dataclasses whose defaults are the reference policy and whose values are yours to set; the engine
  reads them rather than hard-coding a cut.

The model plays no part in any of it, so the same assessment always produces the same score and a
figure quoted to a committee can be replayed from the audit record.

### What are the models allowed to do?

Two seams, different in kind. The **narrator** writes a short committee-ready note that restates
engine figures; its reply must parse as JSON with a `note` key and may quote only integers the
engine produced, or it is discarded and a deterministic note built from the same facts is used
instead. The **embedder** turns control text into vectors for the de-dup engine; it can change which
merge candidates are PROPOSED, which is why the similarity floor is calibrated to the bound embedder
and why no merge is ever applied automatically. See [`../model-card.md`](../model-card.md).

### What will it refuse to do?

- **It will not keep a control catalog.** `ControlLibraryPort` is read-only by construction: there
  is no write method to call, and `tests/contract/test_no_control_catalog.py` fails the build if one
  appears. Rgc7 is the system of record.
- **It will not write back to Aud3.** The theme feed is one way for the same reason.
- **It will not score a proposal.** Proposed ratings and unadopted KRI definitions are inert.
- **It will not apply a merge.** Collapsing two risk lines is consequential, so a candidate is
  proposed and routed, never applied.
- **It will not auto-execute a consequential result.** An assessment at or above the review band,
  every proposed merge, every KRI breach and every theme-driven reopen sets `requires_human_review`
  and is ROUTED to the Hrz7 console in the same call that produced it (rule R8). A CRITICAL band
  demands two approvals rather than one.
- **It will not become healthy on a managed profile with placeholder reads bound.** The preflight
  refuses to start (`managed_readiness.py`).
- **It will not answer without provenance.** Every claim carries a `Citation`.

### Which surfaces expose it?

The FastAPI app (`POST /v1/triage`), the argparse CLI (`triage`), the agent tools (`triage_case`,
`verify_audit_trail`, `assess_rcsa_control`, `propose_control_merges`, advertised on the A2A card at
`/.well-known/agent-card.json`), the embeddable `ui/` micro-frontend, and the eval harness.

Note the honest limit on surface coverage. The ERM engines are reachable today through the agent
tools, the demo and the eval; there is no HTTP route or CLI subcommand for an RCSA assessment, a
merge proposal, a KRI evaluation or a theme reopen, and `ErmService.evaluate_kris` and
`ErmService.reopen_from_themes` have no tool of their own either. Adding those surfaces is
straightforward and is not done. Note also that the repo carries two verticals side by side: the
Erm1 engines (`domain/rcsa.py`, `domain/kri.py`, `domain/dedup.py`, `domain/themes.py`,
`domain/erm_service.py`) and the template's generic triage service (`domain/triage_service.py`,
`/v1/triage`, the CLI and the `triage_case` tool). The triage path is scaffolding the render started
from, not the reason this system exists.

### What does this repo own, and what does it integrate?

| Concern | Owner | How this repo touches it |
|---|---|---|
| RCSA residual risk, KRI evaluation, control de-duplication and theme-driven reopens | **this repo (Erm1)** | four pure engines plus the orchestration in `domain/erm_service.py`. |
| The obligation, policy, control and evidence graph | **Rgc7** obligations and control mapping | read over `ControlLibraryPort`, which has no write method. This repo keys its ratings on Rgc7's `control_id` and keeps no catalog. |
| Control-effectiveness testing | **Aud2** continuous controls monitoring | its results reach this repo as effectiveness on the control records Rgc7 exposes; there is no second testing engine here. |
| Thematic root-cause analysis over issues and losses | **Aud3** issue, remediation and CAPA tracker | read one way over `ThemeFeedPort`. Aud3 is unbuilt, so the offline fixture is the recorded contract, pinned by `tests/contract/test_theme_feed_contract.py`. |
| Agent discovery and entitlements | **Hrz3** agent registry | this agent publishes a card; the registry owns discovery. |
| Model and agent promotion | **Hrz4** AI quality and model risk | `eval/run_eval.py --mode gate` asks Hrz4; the offline smoke mode never promotes. |
| Traces and the immutable audit sink | **Hrz5** agent observability | `AuditSinkPort` and `ObservabilityTracerPort`. |
| Human review and maker-checker | **Hrz7** human review console | `ReviewRouterPort` over the shared `review-kit`. This repo produces escalations; it does not render a queue. |
| Prompt-injection defence and output filtering | **Hrz1** agent guardrail gateway | **not wired today.** It becomes mandatory the moment untrusted free text reaches the narrator (rule R1), and control text already reaches the embedder. |
| Grounded retrieval over an enterprise corpus | **Hrz2** enterprise knowledge base | not wired; this service reasons over its own artifacts and the reads above. |

### Can I demo it without a cloud project?

Yes, and the demo is code rather than a deck. `make demo` runs a presenter-paced walkthrough over
eight steps (opened, routine, escalation, redaction, review queue, audit, tamper, portability) on
its own loopback server; `make demo-selftest` runs the same arc headless and asserts every narrated
claim, so a claim that stops being true fails a build rather than a meeting; `make demo-static`
renders the same audit-first panels to static HTML for screenshots.
`tests/unit/test_demo_surface.py` holds `demo.STEPS` and `walkthrough.CHECKS` equal, so a claim the
demo makes but nobody verifies cannot exist. The seeded bank is shaped so the engines produce a mix
of GREEN, AMBER and RED plus at least one merge candidate, one breach and one reopen.

### What is not built yet?

The honest list is [`../practices-audit.md`](../practices-audit.md) and the `TODO (repo owner)` rows
in [`../../COMPLIANCE.md`](../../COMPLIANCE.md). The four that matter most for a production
decision: the three managed reads named in `managed_readiness.py`, HTTP and CLI surfaces for the ERM
engines, the Hrz1 guardrail binding, and registering this repo's metric bundle with Hrz4 so
`--mode gate` has an authority to ask.
