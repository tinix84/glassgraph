# ADR-0020: Separate core release gates from optional inference admission

- Date: 2026-11-12
- Author: Codex
- Version: 1.0
- Audience: Glassgraph maintainers and release reviewers

## Decision

We require measured core release gates and separate admission gates for each optional local-model operation.

## Context

Issue #23 owns the exact gate definitions and measurement protocol.
Earlier decisions fix evidence identity, relation qualification, benchmark privacy, and retrieval speed.
ADR-0016 supplies topic-driven reference search, holdout briefs, and owner review of material disagreements.
The assist prototype validates supplied output but does not attest a model or establish semantic grounding.
Specification completion must not be mistaken for release readiness.

## Options

| Option | Pros | Cons | Cost / effort |
|---|---|---|---|
| One combined release profile | One checklist | Optional inference could block a useful model-free release | Couples compiler and model qualification |
| Core plus per-operation admission | Preserves the complete deterministic path | Requires explicit feature enablement records | Separate, reusable evidence reports |
| Tests alone establish readiness | Cheap and reproducible | Synthetic tests cannot establish private relevance or model quality | Insufficient operational evidence |

## Decision and rationale

Use the normative criteria in [issue #23](https://github.com/tinix84/glassgraph/issues/23).
Preserve existing evidence, relation, privacy, and speed requirements.
Add explicit targets for relevance, no-answer behavior, memory, editor independence, and context efficiency.
These targets are design choices, not measured claims.
Strict evidence and lifecycle gates protect Markdown authority.
Quality targets require ADR-0016's frozen private search trials and reference-relative measurements as well as synthetic regression tests.
The owner reviews research briefs and material conclusions; the research agent performs reference-search bookkeeping.
Memory headroom and context caps protect the minimum-hardware profile.
Token efficiency must retain required evidence and count serialization overhead.

Treat missing, stale, or unmeasured evidence as unmeasured. It cannot satisfy a gate.
Separate the model-free release from optional operation admission.
Require runtime provenance, offline execution, stability, quality, and measured value before enabling each model operation.
Exact quotes and citation IDs do not prove semantic support.

## Consequences

Every release report binds gate results to frozen inputs and records pass, fail, or unmeasured.
Optional inference can remain disabled while the core qualifies independently.
A successful run on a larger host does not establish minimum-hardware compatibility.
Gate changes require a new decision and a new comparable evaluation record.
Issue #6 remains the owner of runtime integration and model admission.

