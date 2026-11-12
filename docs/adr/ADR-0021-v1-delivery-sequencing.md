# ADR-0021: Deliver portable compiler lifecycle before optional expansion

- Date: 2026-11-12
- Author: Codex
- Version: 1.0
- Audience: Glassgraph maintainers planning implementation

## Decision

We sequence portable integration, canonical compiler lifecycle, retrieval integration, and release qualification before optional product expansion.

## Context

Issue #24 owns the implementation roadmap and links to existing work.
ADR-0018 allows small package increments without introducing competing authorities.
The M3 evidence helper and output replay are prototypes, not a complete compiler or model runtime.
Pre-existing relation, graph, content, and comparison issues retain their own scope and history.

## Options

| Option | Pros | Cons | Cost / effort |
|---|---|---|---|
| Compiler lifecycle first | Establishes trustworthy identities and stale-state handling | Delays visible graph and model features | Focused dependency-ordered increments |
| Graph and model features first | Produces immediate demonstrations | Builds on incomplete canonical state and stale evidence risks | Rework across several features |
| Full expansion before any release | Broad feature set | Makes optional research a core release blocker | Largest coupled delivery scope |

## Decision and rationale

Use the dependency route in [issue #24](https://github.com/tinix84/glassgraph/issues/24).
Complete the portable execution context before exposing root-dependent compiler commands.
Implement manifests and invalidation before attaching retrieval and advisory consumers to canonical output.
Prepare topic-driven reference inputs before the locked retrieval evaluation that consumes them.
Require the ADR-0020 gates before making a release claim.
Allow qualified relation expansion after canonical evidence exists.
Keep local inference optional and gated by operation.
Graph analysis, cards, and generated proposals remain derived views.

## Consequences

Each scheduled increment gets its own implementation issue, acceptance evidence, reviewed PR, and merge.
Existing issues remain linked, without rewritten history or automatic closure.
The roadmap decision can finish while product implementation and benchmark adjudication remain unfinished.
Data migration and file retirement retain their separate safety and approval requirements.

