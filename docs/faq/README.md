# FAQ index

Answers to the questions different teams ask when evaluating, adopting or reviewing this repository
as the second-line ERM operating copilot. Each file is written for a specific audience; skim the one
that matches your role.

| FAQ | For | Answers |
|---|---|---|
| [security-faq.md](security-faq.md) | AppSec / security review | server-side identity, how far tenant scoping actually goes, the exposure guard, secrets, supply chain, the audit chain |
| [portability-faq.md](portability-faq.md) | Architecture / cloud / exit planning | no-lock-in, the three profiles, the sovereign exit, what the embedder swap costs |
| [features-faq.md](features-faq.md) | Product / risk / delivery | what the four engines compute, what the models are allowed to do, and the boundary with sibling catalog systems |
| [adoption-faq.md](adoption-faq.md) | Engineering leads forking the repo | rename, upstream fixes, extension points, what stays open |
| [compliance-faq.md](compliance-faq.md) | Compliance / model risk / second line | why a residual score is defensible, maker-checker, residency, retention, model-risk evidence |

These FAQs deliberately do **not** re-document capabilities owned by sibling systems in the GRC
catalog. Where a concern belongs to another repo (the control library and evidence graph `obligations-control-mapping`,
control-effectiveness testing `continuous-controls-monitoring`, thematic root-cause analysis `issue-remediation-capa`, the guardrail gateway `agent-guardrail-gateway`,
the knowledge base `enterprise-knowledge-base`, the agent registry `agent-registry`, the eval and promotion authority `model-quality-gate`,
observability and the WORM sink `agent-observability`, the human-review console `human-review-console`), the FAQ points at it and
explains the boundary rather than duplicating it. See [features-faq.md](features-faq.md) for the
full "what this repo owns vs what it integrates" map.

Authority order for anything these pages disagree with: [`SPEC.md`](../../SPEC.md), then
[`ARCHITECTURE.md`](../../ARCHITECTURE.md), then [`COMPLIANCE.md`](../../COMPLIANCE.md), then
[`README.md`](../../README.md). These pages restate; they do not decide.
