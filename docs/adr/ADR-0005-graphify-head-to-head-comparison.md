# ADR-0005: Justify the deterministic linker against graphify with a measured head-to-head, not assertion

- Date: 2026-05-22
- Status: accepted

## Context

On 2026-05-22, Graphify was the main off-the-shelf language-model graph-builder alternative. The deterministic linker needed a same-corpus comparison before the project could justify continued development.

## Decision

Build a one-shot eval module `.tools/comparison/` (deliberately outside `entity_linker`, because comparison is an eval and not a production capability) that produces a single markdown report over five axes — determinism (per-source Jaccard across two runs), precision/recall/F1 against the LLM-curated `touches:` treated as gold, audit-trail explainability, speed/cost, and graph-structural metrics — plus a GitHub roadmap check and an honest one-paragraph verdict that may recommend adopting graphify. graphify's entities are scored twice (all entities, and its high-confidence `EXTRACTED` subset) to give it its best showing, and name normalization match-rate is reported so the reader knows how much of the comparison is apples-to-apples.

## Alternatives considered

- Adopting graphify outright — the framework exists precisely to test this; the report may still recommend it.
- Declaring the deterministic tool the winner without measurement — rejected: the verdict section is explicitly not predetermined.
- Including Stage 2 in the comparison — deferred: threshold tuning would muddy the Stage 1 baseline comparison.
- Scoring graphify's entity-to-entity inferences — out of scope: only source-to-entity edges match the `touches:` structure.
- Visualizations beyond markdown, a live/reactive demo, a maintained dashboard — all rejected to ship the eval in one day.

## Consequences

- The two tools are positioned as complements with different value propositions: span-level traceability and determinism on our side, first-class community detection on graphify's.
- The graphify parser must be defensive and must abort loudly on schema divergence rather than emit wrong numbers.
- Risks accepted with mitigations: long graphify runs fall back to a 50-source subset; a graphify failure is itself recorded as a comparison finding.
