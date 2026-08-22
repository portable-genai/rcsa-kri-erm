# Adoption FAQ

For an engineering lead forking this repo as their institution's ERM copilot. The step-by-step is
[`../ADOPTING.md`](../ADOPTING.md); this answers the "will it hurt later?" questions.

### How do I rebrand it for my organisation?

`scripts/rename_fork.py` rewrites the package name (`rcsa_kri_erm`, which is also the
console script), the `ERM_` env prefix (including the bare token that
`infra/terraform/render.tf.json` carries as `render_env_prefix`, so Terraform sets the same variable
names on the service), the Terraform `name_prefix` resource stem (`erm1-svc`) and the distribution /
git id in one pass. Preview with `--dry-run`, apply with `--yes`, then recreate the venv,
`make install`, and run `make gate`. It skips itself, so the renamer is never left half-rewritten,
and it validates `--resource` against the same regex `infra/terraform/variables.tf` enforces, so a
stem the stack would refuse fails here rather than at plan time. The catalog id `Erm1` is left alone
unless you pass `--catalog-id`, so a fork stays traceable to the entry it descends from. The script
does the mechanical rename; the human decisions (region, IdP, the seeded bank, the four policies,
the eval golden sets) are the checklist in `ADOPTING.md`.

### If several institutions fork this, how does each take upstream fixes?

Track upstream via **git tags**. The repo declares a core-vs-adopter-owned boundary
(`ADOPTING.md` section 2): upstream owns `domain/kernel.py`, `ports/`, `tests/contract/`, the eval
harness mechanics, `managed_readiness.py`, CI and the Terraform stack; you own
`config/settings.yaml` values, the seed in `adapters/local/seed.py`, the four policy dataclasses,
`adapters/onprem/*`, UI theming and `terraform.tfvars`. The commons packages (`hex-service-kit`,
`agent-eval-kit`, `pii-kit`, `review-kit`) are pinned by commit sha, so you take their fixes by
bumping the pin rather than by merging code. Rebase your adopter-owned changes onto each release
rather than merging `main` continuously.

### What do we have to supply that is not in this repo?

Four things, and only one of them is code here:

1. **An Rgc7 instance.** This repo reads the control library and keeps no catalog of its own; the
   port has no write method, so there is no shortcut. Offline, `adapters/local/seed.py` stands in.
2. **A metric feed.** `MetricFeedPort` is a BigQuery read under `gcp` and a seeded fixture offline.
   Implementing it against your own warehouse is real work and the managed adapter is a placeholder
   today.
3. **Aud3, eventually.** The theme feed is one way and Aud3 is unbuilt. The offline fixture is the
   RECORDED CONTRACT, pinned by `tests/contract/test_theme_feed_contract.py`, so the remote adapter
   can be swapped in without a domain change when Aud3 ships.
4. **The review console.** An Hrz7 deployment reachable at `HRZ_HUMAN_REVIEW_URL`. The managed router
   REFUSES to swallow an escalation when this is empty, so a fork cannot ship rule R8 unwired and
   green.

### How do I add a new outbound dependency (a new port)?

There is a fixed touch list and a contract test that enforces it. A port must be registered in FIVE
places or it runs with no enforcement at all: `ports/__init__.py` (`PORT_PROTOCOLS`),
`config.DEFAULT_BINDINGS`, a `Container` accessor, `config/settings.yaml`, and a `PortCase` in
`tests/contract/canonical.py`. Then bind it in all three families.
`tests/contract/test_port_parity.py` asserts set equality across the five. See
[`../../CONTRIBUTING.md`](../../CONTRIBUTING.md).

### Can I retune the ERM policy without touching code?

Partly, and the gap is stated honestly. Three of the four policies are frozen dataclasses that
`ErmService` accepts by constructor argument (`ResidualRiskPolicy`, `KriPolicy`,
`ThemeTriggerPolicy`), so a caller can supply its own numbers without touching the engines. The
fourth is not: `propose_merges` takes a `floor` parameter, but
`ErmService.propose_control_merges` calls it without one, so the de-dup floor is always
`DEFAULT_SIMILARITY_FLOOR` and moving it means editing the module constant or threading a floor
through the service. And none of the four is yet a `policy:` block in `config/settings.yaml` with a
`from_policy(...)` constructor, so the defaults live in module code either way. That is the open B4
item in [`../practices-audit.md`](../practices-audit.md). If your risk function must own these
numbers as configuration, plan that addition as part of adoption.

### What is the one number I must re-calibrate rather than inherit?

`DEFAULT_SIMILARITY_FLOOR` in `domain/dedup.py`, currently 0.5. It is calibrated to the OFFLINE
hashing embedder, which puts a near-duplicate pair at roughly 0.67 and unrelated controls below
0.15. A semantic embedder such as Vertex AI text embeddings lives in a much tighter cosine space, so
the same floor would propose far more pairs. The offline gate cannot catch this, because the gate
never binds Vertex. Re-calibrate against the embedder you actually bind and pin your value with a
test.

### Does the gate run for my fork out of the box?

Yes. `make gate` is offline, credential-free and network-free (ruff, ruff format, mypy strict, the
whole suite except integration, and the eval). You add secrets only when you wire the `gcp` profile.
Note the eval measures the REFERENCE bank until you rebuild the five golden sets in
`eval/datasets/` for your own; that is an explicit adoption step, not a silent pass.

### The eval reports high scores. Should we believe them?

Largely yes, and the reason is structural rather than a promise. Each engine metric is scored
against an INDEPENDENT oracle dataset rather than against the pipeline's own verdict, and five of
the seven are proved able to report something else by planted mutants:
`tests/unit/test_erm_not_falsely_green.py` covers `residual_accuracy`, `kri_threshold_exactness`,
`merge_precision` and `reopen_accuracy`, and `tests/unit/test_not_falsely_green.py` covers
`pii_safety`. Two do not have a mutant yet: `decision_accuracy` and
`breach_narration_groundedness`. Read the groundedness one precisely: it drives the RAW local
narrator over each breach's engine facts through the same `parse_note` and `note_is_grounded` the
service enforces, so the CONTRACT is genuinely measured, but the narrator being measured is the
deterministic stub. It says nothing about how a real Gemini reply behaves.

### Will the demo rot after I diverge?

It is guarded, and the guard is inside the gate. A demo step lives in `demo.STEPS` and in
`walkthrough.CHECKS`, and `tests/unit/test_demo_surface.py` holds the two equal, so a claim the demo
makes but nobody verifies cannot exist. `make demo-selftest` runs the whole arc headless over the
real loopback server and exits non-zero when a claim stops being true. If you diverge, keep the step
keys and the `facts` dict the checks read.

### What is still open?

[`../practices-audit.md`](../practices-audit.md) carries the per-check verdict and the work list.
The ones that matter most before production: the three managed reads named in
`managed_readiness.py` (the Rgc7 control library, the BigQuery metric feed, the Aud3 theme feed),
HTTP and CLI surfaces for the ERM engines rather than agent tools alone, a cross-tenant read that
refuses instead of returning empty, binding the Hrz1 guardrail gateway, registering this repo's
metric bundle with Hrz4 so `eval/run_eval.py --mode gate` has an authority to ask, and B4. The
Terraform stack is written, validated and tested against a mocked provider; it has never been
applied.
