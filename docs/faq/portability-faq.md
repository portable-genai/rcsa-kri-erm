# Portability FAQ

For architecture, cloud governance and exit planning. The question underneath all of these is "how
do we leave, and how do we know the answer is true today rather than on the day it was written?"

### What is the lock-in surface?

Every outbound dependency is a `@runtime_checkable` Protocol in `ports/` (audit, control library,
embeddings, generation, identity, metric feed, observability, review router, theme feed), bound per
profile from `config/settings.yaml`. There is no cloud SDK import anywhere in `domain/`, and the
managed adapters import their SDK LAZILY inside the method, so the other two families import with no
SDK installed at all. Every consequential calculation (residual risk, KRI banding and breach
severity, merge candidacy, reopen decisions) is pure stdlib in `domain/`, not a managed service.

### What are the three profiles?

| Profile | What it is | Who it is for |
|---|---|---|
| `local` | SDK-free offline stack: seeded dev personas, a hash-chained SQLite WORM audit log, the demo bank's seeded control library, KRI feed and `issue-remediation-capa` themes, a deterministic hashing embedder and a deterministic stub narrator | dev, test, CI, and the offline demo |
| `gcp` | the managed stack: IAP identity, Cloud Logging WORM, Gemini narration, Vertex AI embeddings, an authenticated read of `obligations-control-mapping`'s control library, a BigQuery metric feed, `issue-remediation-capa`'s theme feed, an HTTP client to the `human-review-console` | a managed deployment, once its three placeholder reads are implemented |
| `onprem` | fail-fast `NotImplementedError` placeholders | the sovereign exit: a client binds its own in-country implementations here |

`ERM_PROFILE` selects the family. Unset means the offline adapters bind but nobody chose them, which
withdraws every relaxation rather than granting one.

### Is the managed profile actually finished?

The model seams are; three of the reads are not, and the repo says so in code rather than in a
footnote. `managed_readiness.INCOMPLETE_MANAGED_OPERATIONS` names the `obligations-control-mapping` control-library read
(both methods), the BigQuery metric feed and the `issue-remediation-capa` theme feed. The API preflight refuses to boot
under a managed profile while one of them is bound, and Terraform's `managed_profile_implemented`
local (`infra/terraform/managed_readiness.tf`) gates the serving edge the same way. Two of the three
are waiting on siblings rather than on this repo: `issue-remediation-capa` is unbuilt, so its offline fixture is the
recorded contract pinned by `tests/contract/test_theme_feed_contract.py`.

### Is the portability claim tested, or just documented?

Tested, three ways, all in the offline gate or one command:

- `tests/contract/test_port_parity.py` asserts set equality across all five homes of a port (the
  `PORT_PROTOCOLS` map, `config.DEFAULT_BINDINGS`, the `Container` accessor, `settings.yaml` and the
  canonical-call table), so a port cannot be added in four places and run unenforced.
- `tests/contract/test_behavioral_parity.py` proves the offline family ANSWERS, the on-premises
  family RAISES and the managed family REFUSES rather than silently succeeding. This matters most on
  the narration and embedding seams: a placeholder that quietly returned an empty note or an empty
  vector map would look exactly like a working one.
- `make portability` is the executable claim: eight named checks with a pass or fail each (every
  port bound in every profile, adapter construction and Protocol conformance, the offline family
  answering, the exit family refusing, rewritten-record detection, anchored truncation detection,
  the trail leaving the codebase intact, and no cloud SDK imported), exiting non-zero on any
  failure. The stronger SDK-free proof lives in `tests/contract/_sdk_free_probe.py`, which BLOCKS
  the `google` import in a fresh interpreter rather than hoping the machine has none installed.

### Where does the data live, and can we take it with us?

This repo deliberately owns very little data. The control library belongs to `obligations-control-mapping` and is read, never
mirrored; the themes belong to `issue-remediation-capa` and are read one way; the metric feed is a read. What this
service owns is its assessments, its evaluations and its audit trail. The audit trail round-trips to
and from JSON Lines, so the record of every score, breach, merge proposal and reopen is a file copy.
The value objects in `domain/erm_models.py` are plain frozen dataclasses, so serialising an
assessment is a schema decision rather than a vendor extraction.

### What does swapping the embedder cost?

More than swapping the narrator, and this is the one portability answer that is not free. The
narrator changes prose only, so any narrator produces the same numbers. The EMBEDDER feeds the
de-dup engine, so a different embedder proposes a different set of merge candidates. The similarity
floor is calibrated to the bound embedder: 0.5 suits the offline hashing embedder, which separates a
near-duplicate pair at roughly 0.67 from unrelated controls below 0.15, while a semantic embedder
lives in a much tighter cosine space and needs a higher floor. Re-calibrate and pin your value with
a test whenever you change embedder. No merge is ever applied automatically, so the failure mode is
noise in a human queue rather than a silent data change.

### How do we actually exit?

[`../onprem-migration.md`](../onprem-migration.md) is the path. The short version: the domain is
pure stdlib and moves unchanged; what you implement is one adapter per port under
`adapters/onprem/`, each of which currently raises with a message naming what to bind. Nothing in
`domain/` has to change, which is the point of the split.

### Can it run with no model at all?

Yes, and that is the load-bearing property rather than a convenience. Every consequential figure is
produced by a deterministic engine, so with the stub narrator bound the residual scores, the RAG
bands, the KRI evaluations, the breach severities, the reopen decisions and the escalations are
identical. The narrator changes one note and nothing else, and even that has a deterministic
fallback used whenever the note is malformed, ungrounded or the narrator raises. The de-dup path is
the exception worth stating: it needs SOME embedder, and offline that is a deterministic hashing
function rather than a model. See [`../model-card.md`](../model-card.md).

### Is the data residency claim portable too?

The region is chosen once and shared by the runtime and Terraform: `config/settings.yaml:region`,
`infra/terraform/render.tf.json:render_region`, and the Terraform `region` / `allowed_regions` pair,
which refuses an unapproved region at plan time. Changing jurisdiction is a configuration change in
those three places plus a re-run of `infra/terraform/production_edge.tftest.hcl`, not a code change.
