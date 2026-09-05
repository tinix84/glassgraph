# ADR-0010: Add a `market` node type and a `used_in` predicate mirroring the external BI taxonomy

- Date: 2026-07-03
- Status: accepted

## Context

Source: `docs/superpowers/RESUME-2026-07-03-bi-increment-b.md` (2026-07-03), following the Phase A relation work of ADR-0009. The typed graph could say who supplies what, but not which market a technology or product serves — the business-intelligence question. Phase A had also dropped the `uses` predicate for 0% precision, leaving a gap in the extracted ontology. An existing product-management vault already maintains a `market / sector / segment` taxonomy across 7 sectors, so the wiki had a ready-made controlled vocabulary rather than needing to invent one.

## Decision

- Add a sixth page type, `market`, named `market___<sector>___<segment>` at segment granularity, mirroring the external BI taxonomy; seed it with 7 corpus-derived segment pages.
- Add `used_in` (`technology|product -> market`) as the first market predicate, replacing the dropped `uses`.
- Keep trends as themes fed by edges rather than as market nodes.
- Apply the same gate as every other extracted predicate: Wilson lower bound >= 0.80 per predicate before any auto-write.
- Register `markets` across the index builder, lint, lookup and the page-type schema; use application-level aliases so bare product terms keep resolving to their technology/product nodes rather than colliding with market nodes.

## Alternatives considered

- Modelling markets as themes — rejected: trends belong in themes, but a market is a stable node the graph points at, not a thesis.
- Sector-level granularity — rejected in favour of segment granularity to match the source taxonomy.
- Reviving `uses` — rejected: it scored 0% precision because it conflates using a technology with developing one.
- Naming markets like other entities — rejected: the triple-underscore compound name is what keeps the taxonomy mapping explicit and avoids alias collisions with product and technology pages.

## Consequences

- Increment A shipped: the type, the seven seed pages, the alias revision (verified with no collisions against the obvious product/technology terms), a green test suite and 0 CRITICAL lint.
- Increment B is unresolved: with ten `used_in` trigger entries in place, a dry run yields **zero edges**, because key-extraction bullets rarely put a `used_in` trigger and an in-bullet market mention in the same bullet under a technology or product subject.
- The open decision is whether to keep trigger-based extraction and tune it, pivot to deriving `used_in` from a source's dominant market context (a source is *about* a market; the entities it touches are then used in it), or run a hybrid. This should be recorded as a follow-up ADR once decided.
