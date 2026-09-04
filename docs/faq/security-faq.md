# Security FAQ

For AppSec and security architecture. Every answer names the file that is the evidence, so the
review can read the control rather than the claim.

### Who is the actor on a decision, and can a caller assert it?

On the HTTP surface, a server-verified `Principal`, always. The request schemas carry no `actor`
field: `POST /v1/triage` takes the audit actor and the review maker from the identity adapter, and
every client-supplied actor, tenant, role, ACL and authorization header is discarded at the browser
boundary (`ui/lib/embed-policy.mjs`). Under the `gcp` profile the adapter verifies the IAP-injected
assertion against the configured audience, against IAP's own key set and against the issuer
(`adapters/gcp/identity.py`); an unset or emptied `ERM_IAP_AUDIENCE` REFUSES every caller, because
`audience=None` means google-auth does not verify the audience at all and would accept any
Google-signed token from any project. `tests/unit/test_iap_identity.py` runs in every gate and
`tests/unit/test_iap_crypto_matrix.py` drives the REAL verifier over locally minted assertions.

Read the agent surface differently, because it is different. `agent/tools.py` exposes
`triage_case`, `assess_rcsa_control` and `propose_control_merges` as in-process callables that take
`tenant` as a REQUIRED argument with no default. There is no identity adapter in that path: the
orchestrator that invokes the tool is responsible for supplying the verified value, and the tool
REFUSES (`TenantAccessDeniedError`) rather than choosing a partition when it is not supplied.
`propose_control_merges` used to default it to the seeded `"demo-bank"` and `assess_rcsa_control`
falling back to the same string lets a caller who named no tenant read and act on the seeded
bank's partition while the API derived the same value from the verified principal. `actor` still
defaults, to a constant that names the SERVICE rather than a person: it widens no read and grants
no authority, it only keeps an unattributed act from wearing a human's name. If you expose these
tools outside a trusted orchestrator, resolve identity server-side first.

### Can one tenant read another tenant's controls, metrics or themes?

No, and the mechanism is an authorisation REFUSAL rather than a filter, which is the part that
matters. `LocalControlLibraryAdapter` and `LocalThemeFeedAdapter` raise
`domain.errors.TenantAccessDeniedError` for any tenant they do not serve, and for the empty tenant
on the same rule: no tenant named is no authority to read. Returning an empty tuple instead, with
nothing raised, would make the answer indistinguishable from a tenant that genuinely has no
controls: the de-dup sweep would report "no merge candidates" and the reopen engine "no theme
names this control", verdicts computed over nothing and returned as findings. Every surface maps
the refusal to HTTP 403 (never 404, which would make the partition probeable with a
tenant-name generator, and never 500, which would read as a bug rather than a boundary holding).
`tests/unit/test_tenant_isolation.py` is the standing gate.

### What happens if the profile variable goes missing in production?

The process still binds the SDK-free adapters (the alternative is importing cloud SDKs that are not
installed), but nobody chose them, so every relaxation is withdrawn: the seeded dev personas refuse
to construct, no service-to-service scheme is selected, the dev CORS allowlist and the
`X-Dev-Persona` header are gone, the interactive docs are not registered, and the loopback exposure
guard refuses every route to any non-loopback peer. An emptied or mis-capitalised value raises AT
IMPORT, so the process fails to boot rather than serving on a posture nobody chose (`config.py`,
`tests/unit/test_profile_single_source.py`).

### Does setting the service-to-service token open anything?

No, and this is enforced rather than intended. The exposure guard's posture is derived from the
identity BINDING (the adapter declares `VERIFIED` / `CLIENT_ASSERTED` / `UNIMPLEMENTED` in
`ports/identity.py`), never from a credential. `ERM_S2S_TOKEN` authenticates a calling SERVICE and
no end user. `tests/unit/test_end_user_auth_posture.py` walks the guard's argument through the
constants it names and fails the build if a credential reappears at any depth, because it did once:
setting the token switched the guard off for the end-user routes it was protecting.

### Can a managed deployment go live with half its reads unimplemented?

No. Three managed adapters are still placeholders that raise, so
`managed_readiness.INCOMPLETE_MANAGED_OPERATIONS` names them (the `obligations-control-mapping` control-library read in both
its methods, the BigQuery metric feed and the `issue-remediation-capa` theme feed) and the API preflight REFUSES to
start under a managed profile while any of them is bound to a port the request path executes.
Terraform's `managed_profile_implemented` local is the deploy-time half of the same rule.
`tests/unit/test_managed_readiness.py` is the standing gate.

### Where does personal data go?

This service reasons over controls, ratings, metric values and themes rather than customer records,
so the personal-data surface is small by construction. Whatever does appear is masked before it
crosses any boundary: before the audit write, before a review payload leaves the process
(`adapters/_review_payload.py`, against EVERY jurisdiction's rows because the console is a shared
sink), and before a tool result can enter a model's context (`agent/tools.py:_redacted`, which walks
a nested result rather than only its top level). The pattern set and its ORDER are this vertical's
(`domain/pii.py`, national rows first, universal rows last), drawn from the shared `pii-kit`. The
`pii_safety` eval metric holds this at `>= 0.99` and `tests/unit/test_not_falsely_green.py` proves
the metric can go red.

### Can the model exfiltrate or invent anything?

The narrator is reachable through exactly one port (`ports/generation.py`), it receives a system
prompt plus a facts block the engine built, and its reply is parsed and REJECTED unless it is
well-formed JSON with a non-empty `note` and every integer in it is one the engine produced
(`domain/erm_narration.py`: `parse_note`, `note_is_grounded`). A rejected reply is discarded and the
deterministic fallback note is used instead, with `model_authored` recording which path ran. The
groundedness checks are module-level pure functions rather than private methods, deliberately, so
the eval measures the RAW model output through the very same contract the service enforces.

There is a second model seam worth naming in a security review: the EMBEDDER. Control text is sent
to it (Vertex AI under `gcp`), and its vectors feed the de-dup engine. It cannot invent a merge,
because every candidate is routed to a human and none is applied automatically, but it is a data
egress path and a model whose behaviour changes what gets proposed. See
[`../model-card.md`](../model-card.md). Prompt-injection screening through the `agent-guardrail-gateway` is **not** wired yet on either seam.

### How is the audit trail protected?

Append-only and hash-chained, AND externally anchored. The chain catches an edit, a deletion or a
reorder; only the anchor catches a TRUNCATED TAIL, because dropping the newest rows leaves a shorter
chain that verifies perfectly. `audit_anchor_path` (`ERM_AUDIT_ANCHOR`) writes the chain head to a
file on another volume, and `tests/unit/test_audit_anchor.py` proves the detection, proves the
control case goes UNDETECTED without an anchor, and proves an append after truncation refuses rather
than re-anchoring. Under the managed profile the sink is a locked Cloud Logging bucket
(`infra/terraform/logging_worm.tf`), which provides non-rewritability itself.

### What about supply chain?

Both lockfiles are committed and pin every dependency exactly; the catalog commons are pinned to
40-character COMMIT shas rather than tags, because a re-pushed tag changes what installs with no
diff in the lockfile. The base image is digest-pinned, dependabot covers every ecosystem the repo
actually has, and `pip-audit` plus `npm audit --audit-level=high` are HARD CI failures.
`tests/unit/test_repo_artifacts.py` asserts each of these from inside the repo, and it asks git
whether each pinned sha is a COMMIT object rather than an annotated tag object, which a regular
expression cannot tell apart.

### What is deliberately out of scope?

- **Login.** This repo authenticates nobody itself: the platform in front of it does, and the UI
  forwards the assertion without parsing or trusting a parsed copy.
- **Injection defence and output filtering.** Owned by `agent-guardrail-gateway`; not bound yet.
- **The review queue.** Owned by `human-review-console`; this repo produces escalations and routes them.
- **The control library.** Owned by `obligations-control-mapping`. `ControlLibraryPort` has no write method at all, and
  `tests/contract/test_no_control_catalog.py` proves it, so this repo cannot grow a shadow catalog.
- **Control-effectiveness testing.** Owned by `continuous-controls-monitoring`; its results arrive as effectiveness on the
  control records `obligations-control-mapping` exposes.
- **Thematic root-cause analysis.** Owned by `issue-remediation-capa`; the feed is read one way and never written back.
- **Network egress control.** VPC-SC governs access to Google APIs across perimeters, not arbitrary
  internet egress. The private-egress rule that lets this service reach the control library, the
  metric and theme feeds and the `human-review-console` and nothing else is an adopter network decision,
  called out in `COMPLIANCE.md` P-01.
