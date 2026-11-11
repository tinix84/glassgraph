# ADR-0010: Add a `market` node type and a `used_in` predicate mirroring the external BI taxonomy

- Date: 2026-07-03
- Status: accepted

## Context

On 2026-07-03, the typed graph could not state which market a technology or product served. The earlier `uses` predicate had 0% precision. A product-management vault already supplied a controlled market taxonomy across seven sectors.

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

- A 2026-07-03 dry run used ten `used_in` triggers and produced zero edges.
- Key-extraction bullets rarely contain both a trigger and a market mention under a technology or product subject.
- The open decision is whether to keep trigger-based extraction and tune it, pivot to deriving `used_in` from a source's dominant market context (a source is *about* a market; the entities it touches are then used in it), or run a hybrid. This should be recorded as a follow-up ADR once decided.
