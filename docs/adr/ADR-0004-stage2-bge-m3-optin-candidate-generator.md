# ADR-0004: Stage 2 BGE-M3 dense retrieval is an opt-in, CPU-deterministic candidate generator

- Date: 2026-05-21
- Status: accepted

## Context

On 2026-05-21, testing showed that Stage 1 missed product-family neighbors and paraphrased concepts. A BGE-M3 proof of concept found related entities, but a transformer could weaken determinism and increase local cost.

## Decision

Promote the POC to `.tools/entity_linker/stage2.py` as an **opt-in** capability on the `extract` command only (`--vector`, `--top-k`, `--threshold`, `--rebuild-embeddings`). It runs CPU-only with seeds fixed and `model.eval()`, producing byte-identical embeddings across runs. Results land in a *separate* `vector_entities` list in the extraction cache with tri-state semantics (absent = not run, `[]` = no hits, non-empty = hits), alongside a pinned model-revision + page-SHA manifest. Stage 1 behaviour is unchanged; `backfill`, `suggest`, `explain` and `lint` do not gain vector results.

## Alternatives considered

- Merging vector hits into the existing `entities` list — rejected: Stage 1 hits carry span/literal data, Stage 2 hits carry cosine/rank; different shapes would need null padding.
- GPU inference — rejected: full determinism is not guaranteed on GPU even with the deterministic flags.
- BM25 + dense hybrid retrieval (recommended by the model authors) — deferred: dense-only is sufficient at a closed vocabulary under 5k entity pages.
- Incremental re-embedding on partial SHA mismatch — rejected: any page change triggers a full re-embed; acceptable at ~588 pages.
- A re-ranker layer over top-K — deferred: doubles inference cost.

## Consequences

- Adds `sentence-transformers` (~500 MB of packages plus a ~2 GB model download on first use); its absence degrades gracefully with an install hint while the rest of the linker keeps working.
- Whether the LLM ingest step actually consumes `vector_entities` was deliberately left to a future spec — Stage 2 only fills the cache.
- Explicit performance alarms: >3s per warm source extract, >10 MB embeddings matrix, >10 min full re-embed all signal a design problem.
