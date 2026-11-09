# ADR-0003: Deterministic Aho-Corasick alias linking replaces LLM entity matching

- Date: 2026-05-19
- Status: accepted

## Context

Design reviews on 2026-05-19 and 2026-05-20 found that language-model entity matching produced different `touches:` lists for the same clipping. This made ingest untestable and the graph irreproducible. Each entity page already supplied a controlled vocabulary through `aliases_en` and `aliases_cn`.

## Decision

Build `.tools/entity_linker/`: an Aho-Corasick scan over the alias dictionary (`aliases_en` union `aliases_cn` union page stem), O(N) in document length and 100% deterministic, as Stage 1 of ingest. It emits *candidates only*; the LLM's role narrows to disambiguation warnings and NEW_FULL vs NEW_STUB judgement. Longest-match-wins is implemented as an explicit greedy sweep; a `disambiguation.yaml` blocklist suppresses known false spans; a SHA-manifest triggers index rebuilds. Backfill across all source pages is audit-only and never writes `touches:` back. Phase 1 (2026-05-20) extends the same module rather than a sibling one, adding `lint` (defensive checks, CRITICAL aborts backfill), `explain` (span-level tracing), `suggest` (TF/DF alias candidates, manual triage only) and `backfill --history`.

## Alternatives considered

- Keep LLM-driven entity matching — rejected: non-reproducible, untestable, corrupts graph metrics.
- Use the `aliases:` union field as vocabulary — rejected: empirically inconsistent across pages; the semantic fields are read directly instead.
- `pyahocorasick.iter_long` for longest match — rejected: not a documented API on the installed version.
- `obsidiantools` for vault parsing — rejected: the wiki is not a full Obsidian vault; frontmatter is parsed directly.
- A separate `wiki_lint/` module for Phase 1 — rejected: would force cross-module dependencies for no isolation gain.
- Auto-applying suggested aliases and auto-writing backfill results — rejected as explicit non-goals.

## Consequences

- New dependencies limited to `pyahocorasick` and `networkx`; no FAISS, no transformer models in the MVP.
- Stage 1 recall is bounded by alias coverage; residual recall is deferred to Stage 2 (see ADR-0004).
- Case-sensitive matching stays (defensible for SiC/GaN) and becomes a documented, tested contract.
- Compound-vs-general entity overlap needs an explicit rule (Appendix B, 2026-05-21): a specific entity wins only on literal compound phrases; bare generic terms must never be added to a specific entity's aliases; topically valid LLM tags Stage 1 cannot reproduce are kept, not stripped.
