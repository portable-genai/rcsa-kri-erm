# Adopting this repo as your base

This repository (Erm1, RCSA, KRI and ERM Operating Copilot) is a **common base** that a bank or
other regulated institution forks to build its own **second-line ERM operating copilot**: the
service that scores residual risk on an RCSA assessment, evaluates KRIs against adopted thresholds,
proposes control de-duplications, and reopens signed-off assessments when a thematic finding lands
on them. It ships a reusable hexagonal core (a pure-stdlib domain, typed ports, three swappable
adapter profiles, a green offline gate) plus four worked deterministic engines over an obviously
fictional bank that you can keep, reseed, or retune.

This guide is the step-by-step for making it yours. It has two halves: a **mechanical rebrand**
(one script) and the **human decisions** the script cannot make for you.

> Related reading: [`ARCHITECTURE.md`](../ARCHITECTURE.md) (the port table and topology),
> [`CONTRIBUTING.md`](../CONTRIBUTING.md) (adding an adapter, adding a port), the
> [`faq/`](faq/) directory, [`model-card.md`](model-card.md) (the model boundary),
> [`practices-audit.md`](practices-audit.md) (the per-check verdict).

---

## 1. What you keep vs what you rewrite

The core is hexagonal, and the boundary between reusable machinery and this vertical is a physical
module split with an enforced dependency direction. `domain/kernel.py` owns the vertical-neutral
contracts and imports nothing from the vertical; `domain/erm_models.py` holds this service's own
risk artifacts.

| Layer | Where | For your own ERM cycle |
|---|---|---|
| **Vertical-neutral machinery** | `domain/kernel.py` (`Citation`, `AuditEvent`, `Severity`, `Decision`, `utcnow`), every Protocol in `ports/`, the container wiring in `config.py` | keep untouched |
| **Engine machinery** | the arithmetic in `domain/rcsa.py`, the banding and trend reading in `domain/kri.py`, the cosine similarity in `domain/dedup.py`, the attach-and-reopen rules in `domain/themes.py`, the schema and groundedness checks in `domain/erm_narration.py` | keep untouched; the shapes are vertical-neutral |
| **Policy (your numbers and rules)** | `ResidualRiskPolicy` in `domain/rcsa.py` (the effectiveness reduction steps, the band cuts, the review floor), `KriPolicy` in `domain/kri.py` (the driver weights and the breach-severity bands), `DEFAULT_SIMILARITY_FLOOR` in `domain/dedup.py`, `ThemeTriggerPolicy` in `domain/themes.py` (the reopen weight floor), the severity keyword bands in `domain/triage_service.py`, the jurisdiction list in `domain/pii.py`, the metric thresholds in `eval/run_eval.py` | change deliberately (see section 4) |
| **Vertical (the bank's content)** | the seeded control library, KRI definitions, metric feed and Aud3 themes in `adapters/local/seed.py`, the narration system prompt in `domain/erm_narration.py`, the eval golden sets in `eval/datasets/` | reseed and rewrite for your own institution |

If your product is another *rate it, threshold it, escalate it* service, the hexagon, the three
profiles, the deterministic-verdict pattern, the eval gate and the Hrz7 review routing transfer
directly; you replace the seeded content and retune the policy.

## 2. Core-vs-adopter-owned files (so upstream merges stay mechanical)

Upstream keeps evolving these; avoid diverging from them so you can pull fixes cleanly:

- **Upstream-owned** (take our changes): `domain/kernel.py`, `ports/`, `tests/contract/`, the eval
  harness mechanics (`eval/run_eval.py`), the CI workflows, the hexagon wiring (`config.py`
  `Container`), `managed_readiness.py` and the deploy stack in `infra/terraform/`.
- **Adopter-owned** (yours; expect to edit): `config/settings.yaml` *values*, the seed in
  `adapters/local/seed.py` and every fixture, the four policy dataclasses, `adapters/onprem/*`, UI
  theming and branding, the golden eval datasets, `infra/terraform/terraform.tfvars`, and the
  regulator crosswalk section of `COMPLIANCE.md`.

Track upstream via git tags; rebase your adopter-owned changes onto each release rather than
merging `main` continuously.

## 3. The mechanical rebrand (one script)

`scripts/rename_fork.py` rewrites the package name (`rcsa_kri_erm`, which is also the
console script), the `ERM_` env prefix (including the bare token that
`infra/terraform/render.tf.json` carries as `render_env_prefix`, so Terraform sets the same variable
names on the service), the cloud resource stem (`erm1-svc`, the Terraform `name_prefix`) and the
distribution / git id in one pass. Preview first, then apply:

```bash
# Preview (writes nothing):
python scripts/rename_fork.py --package acme_erm_copilot --env-prefix ACME \
    --resource acme-erm --dry-run

# Apply:
python scripts/rename_fork.py --package acme_erm_copilot --env-prefix ACME \
    --resource acme-erm --yes

# Then recreate the environment (the distribution name changed) and prove it is green:
python3.12 -m venv .venv && source .venv/bin/activate
make install
make gate
```

`--dist` defaults to the `--resource` value; pass it explicitly when your git id differs from your
resource stem. `--resource` is validated against the same regex the Terraform `name_prefix`
variable enforces, so a stem the stack would refuse fails here instead of at plan time. Add
`--include-docs` to sweep Markdown prose too. The catalog id `Erm1` is left alone unless you pass
`--catalog-id`, so a fork stays traceable to the entry it descends from. The script skips itself, so
the renamer is never left half-rewritten, and it deliberately does NOT touch the human decisions
below.

## 4. The human decisions (the script can't make these)

1. **Region / residency.** The build defaults to `asia-southeast1` (MAS / Singapore), chosen once
   and shared: `config/settings.yaml:region`, `infra/terraform/render.tf.json:render_region` and the
   Terraform `region` / `allowed_regions` pair. Set all of them to your in-country region and re-run
   `infra/terraform/production_edge.tftest.hcl`, whose
   `reject_region_outside_the_residency_allowlist` run refuses a region outside the allowlist at
   plan time. See [`runbook.md`](runbook.md).
2. **Identity / IdP.** This repo owns no login flow: the `gcp` profile verifies the IAP-injected
   assertion at the edge, `local` uses seeded dev personas, and `onprem` is a client IdP
   placeholder. Wire your issuer on the deployed service (auth is configured ON the service, not in
   this code) and set `ERM_IAP_AUDIENCE`. An unset or emptied audience refuses every caller rather
   than verifying without one.
3. **The control library is NOT yours to create here.** Rgc7 owns the obligation to policy to
   control to evidence graph, and `ControlLibraryPort` is deliberately READ-ONLY so this repo cannot
   grow a second catalog (`tests/contract/test_no_control_catalog.py` proves there is no write
   method). Offline, `adapters/local/seed.py` stands in as the demo bank's library. In a deployment
   you point the managed adapter at your Rgc7 instance and key your RCSA ratings on its
   `control_id`.
4. **Policy your risk function owns.** Four frozen dataclasses decide everything consequential:
   - `ResidualRiskPolicy` (`domain/rcsa.py`): how much each effectiveness level reduces likelihood,
     where the RAG cuts fall, and the band at which an assessment must be reviewed. Two rules are
     structural rather than tunable, and you should keep them: only ACCEPTED ratings score, and
     effectiveness reduces likelihood but never impact.
   - `KriPolicy` (`domain/kri.py`): the additive driver weights (threshold distance, trend,
     persistence) and the severity bands they roll into.
   - `DEFAULT_SIMILARITY_FLOOR` (`domain/dedup.py`): calibrated to the BOUND embedder. The offline
     hashing embedder separates a near-duplicate pair from unrelated controls with a wide margin;
     a semantic embedder lives in a tighter space and needs a higher floor. Re-calibrate this when
     you change embedder, and pin your value with a test.
   - `ThemeTriggerPolicy` (`domain/themes.py`): the theme weight at or above which an attached
     theme reopens a signed-off assessment.

   Three of the four are injectable into `ErmService` by constructor argument. The similarity floor
   is not: `ErmService.propose_control_merges` calls `propose_merges(vectors)` without a floor, so
   it always uses `DEFAULT_SIMILARITY_FLOOR` and changing it means editing the constant or threading
   a floor through the service. Either way the defaults live in module code rather than in a
   `policy:` section of `config/settings.yaml` (practices-audit check B4 is the open item); change
   them deliberately and add a test that pins your values.
5. **Tenancy.** Every read is scoped by a `tenant` string and the offline adapters serve the seed
   only to its owning tenant (`demo-bank`), REFUSING any other with
   `domain.errors.TenantAccessDeniedError` (mapped to HTTP 403 by every surface). Returning an
   EMPTY result instead is a filter rather than an authorisation refusal and is indistinguishable
   from a tenant that genuinely has no controls. Your own adapters must keep that shape: raise
   across the boundary, and treat the empty tenant the same way, because no tenant named is no
   authority to read. The tenant reaching the engines must come from the verified
   principal on every surface (the API derives it from the principal; the agent tools take it as a
   REQUIRED argument with no default and refuse without it, so their caller supplies the verified
   value or gets nothing).
6. **Reference data is fictional.** `adapters/local/seed.py` is one synthetic bank, deliberately
   shaped so the engines produce a mix of GREEN, AMBER and RED plus at least one merge candidate,
   one breach and one reopen. Replace it with your own synthetic data. **Do not run against a real
   control library or a real KRI feed without your own security and model-risk sign-off.**
7. **Eval golden sets.** Rebuild the five datasets in `eval/datasets/` (`golden_cases.jsonl`,
   `residual_oracle.jsonl`, `kri_oracle.jsonl`, `merge_oracle.jsonl`, `reopen_oracle.jsonl`) for
   your policy: a fork inherits a green gate that measures the WRONG bank until you do. The seven
   metrics and their thresholds are generic; the golden cases are yours. Note that the oracles are
   independent expectations rather than replays of the engine's own answer, which is what makes them
   worth keeping.
8. **Deployment posture.** Review the Dockerfile (digest-pinned base, non-root uid 10001),
   `infra/terraform/` (Org Policy, CMEK, a dry-run-first VPC-SC perimeter, the locked WORM log
   bucket, the load-balancer-only serving edge) and the loopback-by-default binding before you
   expose anything. The WORM lock is irreversible: confirm `retention_days` before the first apply.
   Note also `managed_readiness.INCOMPLETE_MANAGED_OPERATIONS`: the API preflight refuses to boot
   under a managed profile while the Rgc7 control-library read, the BigQuery metric feed or the Aud3
   theme feed is still a placeholder, so implementing those three is part of going managed.

## 5. Do not duplicate the platform

This repo is one system in a catalog of composable GRC systems. It is deliberately the OWNER of the
second-line ERM cycle and a READER of everything else. What it integrates rather than rebuilds (see
[`faq/features-faq.md`](faq/features-faq.md) for the full map):

- **Rgc7** obligations and control mapping: owns the control library and the evidence graph, read
  over `ControlLibraryPort`. This repo keeps NO control catalog, and the port has no write method so
  it cannot acquire one by accident.
- **Aud2** continuous controls monitoring: owns control-effectiveness testing. Its results reach
  this repo as effectiveness on the control records Rgc7 exposes, not through a second testing
  engine here.
- **Aud3** issue, remediation and CAPA with thematic analysis: owns thematic root-cause analysis.
  This repo consumes its themes one way over `ThemeFeedPort` and never writes back.
- **Hrz7** human-review / maker-checker console: every consequential outcome is routed to it over
  the shared `review-kit` (rule R8); you wire your endpoint (`HRZ_HUMAN_REVIEW_URL`), you do not
  re-implement the console.
- **Hrz5** observability plus immutable WORM audit: audit events and trace spans go to it through
  `AuditSinkPort` and `ObservabilityTracerPort`.
- **Hrz4** AI-quality / model-risk gate: owns promotion. `eval/run_eval.py --mode gate` is the
  client half and refuses to run off the managed profile.
- **Hrz3** agent registry: this agent publishes its A2A card at `/.well-known/agent-card.json`;
  register it rather than inventing a discovery mechanism.

The guardrail gateway (Hrz1) is **not** integrated today, and the enterprise knowledge base (Hrz2)
is not either. Hrz1 becomes mandatory the moment untrusted free text reaches the narrator: see rule
R1 in [`../COMPLIANCE.md`](../COMPLIANCE.md).

## 6. Adoption checklist

- [ ] Ran `scripts/rename_fork.py`, recreated the venv, `make gate` green.
- [ ] Set the region in all three places (settings, `render.tf.json`, tfvars) and re-ran the
      Terraform residency tests.
- [ ] Wired your IdP audience on the deployed service (this repo owns no login flow).
- [ ] Pointed the control-library read at your Rgc7 instance and keyed your ratings on its
      `control_id`, rather than seeding a catalog here.
- [ ] Replaced the seed bank with your own controls, KRI definitions, metric feed and themes.
- [ ] Owned the four policy dataclasses with your risk function, and re-calibrated the de-dup
      similarity floor against the embedder you actually bind.
- [ ] Kept your own adapters refusing a cross-tenant read rather than returning empty, and decided
      where the tenant on each surface comes from.
- [ ] Replaced every synthetic fixture.
- [ ] Rebuilt all five eval golden sets.
- [ ] Reviewed the deploy posture (Dockerfile, Terraform, `retention_days`, bind address) and worked
      through `managed_readiness.INCOMPLETE_MANAGED_OPERATIONS`.
- [ ] Wired your Hrz7 review endpoint and decided which sibling services you integrate vs stub.
- [ ] Read [`model-card.md`](model-card.md) and closed its remaining controls before enabling the
      managed narrator.
- [ ] Recorded your baseline upstream tag so you can take future fixes.
