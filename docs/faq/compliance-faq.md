# Compliance FAQ

For compliance, model risk and the second line. The mapping table with a file reference on every row
is [`../../COMPLIANCE.md`](../../COMPLIANCE.md); this page answers the questions that come back
after reading it.

### Is a residual score from this system defensible?

That is the reason the arithmetic is pure code. `domain/rcsa.py` computes every residual score over
a frozen, bank-owned `ResidualRiskPolicy`, and three rules make the number mean something:

- **Only accepted ratings score.** `residual_for_assessment` reads `accepted_ratings` and never
  `proposed_ratings`, so a proposal moves no number until a maker signs it off through Hrz7. An
  assessment carrying only proposals scores as if it had none.
- **Effectiveness reduces likelihood, never impact.** A working control makes a loss less likely; it
  does not make the loss smaller. Residual likelihood is floored at 1, so a control can never zero
  out a risk.
- **The bands come from the policy, not from a model.** `ResidualRiskPolicy.band_for` reads
  config-owned floors, and the worst band across an assessment is what sets the review requirement.

The same inputs always produce the same assessment, so a figure quoted to a risk committee or a
regulator can be replayed from the audit record.

### And a KRI breach?

Same shape, with two extra properties. Only ADOPTED definitions evaluate, so a proposed threshold is
inert. And the breach severity is an ADDITIVE NAMED-DRIVER score rather than an opaque number:
threshold distance, trend direction and persistence each contribute a stated number of points from
`KriPolicy`, summed and banded. You can show a committee which driver moved the severity, which is
the property that makes it arguable rather than merely reported. The evaluation is pinned to an
explicit `as_of`, so a historical replay never sees a later observation.

### Who signs off?

A human, always, for anything consequential. Setting `requires_human_review` and calling
`ReviewRouterPort.route` is one act rather than a flag plus an intention, and `ErmService` routes
four kinds of outcome the moment each is produced: an assessment whose worst residual band reaches
the review floor, every proposed control merge, every KRI breach and every theme-driven reopen.
`tests/unit/test_review_routing.py` asserts the routing rather than the flag, a CRITICAL band demands
two approvals rather than one (`adapters/_review_payload.py`), and under the managed profile the
router REFUSES when no console is configured, so a deployment cannot swallow an escalation silently.

### Where does the data live, and is residency enforced or just documented?

Enforced at deploy time. The region is chosen once (`asia-southeast1`) and shared by the runtime and
Terraform: `infra/terraform/variables.tf` validates the region against the residency allowlist at
plan, `org_policy.tf` pins `gcp.resourceLocations` to that region's location group, and every
regional resource (the CMEK key ring, the WORM log bucket, the Cloud Run service) is created in it.
`infra/terraform/production_edge.tftest.hcl` is the standing proof: its
`reject_region_outside_the_residency_allowlist` and `residency_defaults_are_in_country` runs fail if
the allowlist stops refusing or a resource drifts off region, and they run against a mocked provider
so they need no project and no credentials. The stack has never been applied.

### What about key management and least privilege?

One REGIONAL CMEK key with a 90-day rotation, and an explicit key binding for EACH service agent
that encrypts under it, because CMEK does not cascade (`infra/terraform/kms.tf`). One serving
identity holding only the roles a request needs, each traceable to a bound adapter, with
`logging.logWriter` write only so the process cannot read back the WORM trail it writes (`iam.tf`).
Exportable service-account keys are forbidden by org policy rather than merely avoided, and a key
creation raises an alert if one happens anyway (`org_policy.tf`, `monitoring.tf`).

### How long is the audit trail kept, and can it be edited?

The Cloud Logging bucket is LOCKED by default and its retention variable refuses anything below six
months (`reject_retention_below_six_months` in the Terraform test). The lock is irreversible: once
applied, retention cannot be reduced and the bucket cannot be deleted for the full window, not even
with project-owner rights, and `reject_reducing_existing_locked_retention` fails a plan that tries.
Confirm `retention_days` before the first apply. DATA_READ audit logging is enabled too, so a read
is itself recorded.

Offline the same guarantee is earned differently: the log is hash-chained AND externally anchored,
because a truncated tail leaves a shorter chain that verifies perfectly. The retention schedule and
the legal basis for the trail are adopter-owned.

### What personal data does this system process?

Very little by design: it reasons over controls, ratings, metric values and themes rather than
customer records. Whatever does appear is masked before every boundary (the audit write, the
outbound review payload, and any tool result that could enter a model's context), with the
jurisdiction rows and their ORDER chosen in `domain/pii.py`. The `pii_safety` metric holds this at
`>= 0.99` and is proved able to go red.

### Can one business unit see another's controls?

Every read is scoped by tenant, but read the mechanism honestly before you rely on it. The offline
adapters FILTER the seed to the requesting tenant and return an EMPTY result for any other; nothing
raises. An empty result is indistinguishable from a tenant that genuinely has no controls, so it is
a partition rather than an authorisation refusal. On the HTTP surface the tenant comes from the
verified principal; on the agent-tool surface it is a function argument the caller supplies.
Hardening both is adoption step 5 in [`../ADOPTING.md`](../ADOPTING.md), and it should be closed
before a second tenant is served.

### What model-risk evidence exists?

[`../model-card.md`](../model-card.md) records both model boundaries as built. The narrator writes
one note that restates engine figures; its reply is schema-validated and groundedness-checked and
discarded on failure, with a deterministic fallback used instead and `model_authored` recording
which path ran. The embedder feeds the de-dup engine, so it can change which merges are PROPOSED,
which is why the similarity floor is calibrated to the bound embedder and why no merge is ever
applied automatically. The offline eval scores seven metrics on every change, each engine metric
against an independent oracle, and five of the seven are proved able to go red by planted mutants.

What is NOT yet in place: `gemini-3.5-flash` and `text-embedding-004` are pinned defaults in the
adapters rather than confirmed deployment decisions and both ids are regional, there is no token
budget, rate limit or kill switch on either seam, no live-model eval run has been registered with
the Hrz4 promotion gate, and prompt-injection screening through Hrz1 is not bound. Until those
close, the managed model paths are not production-cleared and the deterministic path is what should
be relied on.

### Which regulations does this claim to satisfy?

None, on your behalf. The mapping in `COMPLIANCE.md` is to the CATALOG's own principles (P-01 to
P-13) and platform rules (R1 to R8). The crosswalk from those to MAS TRM, CPS 234, CPS 230, HKMA or
PDPA control ids, and the judgement that a control is SUFFICIENT for a regulation, is explicitly
adopter-owned. No row in that document should be quoted as regulatory assurance, and the second-line
review of the deterministic policy in `domain/` is bank-owned logic rather than a vendor default to
inherit unexamined. The reference policy numbers shipped here are a working starting point, not an
interpretation of what any regulator requires of you.

### What is still open at go-live?

The `Partial` and `TODO (repo owner)` rows in `COMPLIANCE.md`, each of which names exactly what is
missing. The ones that need a risk acceptance if you go live without them: the three managed reads
named in `managed_readiness.py` (the Rgc7 control library, the BigQuery metric feed, the Aud3 theme
feed), a cross-tenant read that refuses rather than returning empty, rule R1 (the Hrz1 guardrail
binding), rule R5 and P-08 (the Hrz4 metric bundle), P-10 (timeouts, circuit breaker and a
documented kill switch), and P-01's private-egress rule, which depends on your own network rather
than on this repo.
