# Architecture Decision Records

Decisions for glassgraph and the 2brain vault it serves. Specs live as GitHub issues; plans are temporary; the code describes current behaviour. One row per ADR.

| ADR | Date | Decision |
|---|---|---|
| [ADR-0001-raw-immutable-wiki-curated-synthesis-layer](ADR-0001-raw-immutable-wiki-curated-synthesis-layer.md) | 2026-05-03 | Immutable `raw/` corpus with an LLM-owned `wiki/` synthesis layer |
| [ADR-0002-zotero-direct-sqlite-extractor](ADR-0002-zotero-direct-sqlite-extractor.md) | 2026-05-16 | Ingest Zotero via a first-party read-only SQLite extractor |
| [ADR-0003-deterministic-aho-corasick-entity-linking](ADR-0003-deterministic-aho-corasick-entity-linking.md) | 2026-05-19 | Deterministic Aho-Corasick alias linking replaces LLM entity matching |
| [ADR-0004-stage2-bge-m3-optin-candidate-generator](ADR-0004-stage2-bge-m3-optin-candidate-generator.md) | 2026-05-21 | Stage 2 BGE-M3 dense retrieval is an opt-in, CPU-deterministic candidate generator |
| [ADR-0005-graphify-head-to-head-comparison](ADR-0005-graphify-head-to-head-comparison.md) | 2026-05-22 | Justify the deterministic linker against graphify with a measured head-to-head, not assertion |
| [ADR-0006-structural-frontmatter-write-gate-and-git](ADR-0006-structural-frontmatter-write-gate-and-git.md) | 2026-06-11 | Machine-parsed frontmatter must be machine-written — validating writer, PreToolUse hook, and git |
| [ADR-0007-generated-index-from-frontmatter-summaries](ADR-0007-generated-index-from-frontmatter-summaries.md) | 2026-06-11 | index.md is generated from frontmatter `summary:` fields and never hand-edited |
| [ADR-0008-theme-synthesis-via-deterministic-clustering](ADR-0008-theme-synthesis-via-deterministic-clustering.md) | 2026-06-11 | Theme candidates are detected by deterministic co-occurrence clustering, owned by the controller, created only on user approval |
| [ADR-0009-typed-relation-graph-with-wilson-gate](ADR-0009-typed-relation-graph-with-wilson-gate.md) | 2026-06-30 | Typed semantic relations extracted from key-extraction bullets, gated per predicate on a Wilson lower bound |
| [ADR-0010-market-node-type-and-used-in-predicate](ADR-0010-market-node-type-and-used-in-predicate.md) | 2026-07-03 | Add a `market` node type and a `used_in` predicate mirroring the external BI taxonomy |
| [ADR-0011-glassgraph-deterministic-evidence-compiler-positioning](ADR-0011-glassgraph-deterministic-evidence-compiler-positioning.md) | 2026-08-29 | Position glassgraph as a deterministic typed-evidence and ontology compiler, not a second-brain app |
| [ADR-0012-optional-local-semantic-assist-lane](ADR-0012-optional-local-semantic-assist-lane.md) | 2026-08-29 | Optional private local semantic-assist lane behind a model-free deterministic core |
| [ADR-0013-v1-typed-evidence-contract](ADR-0013-v1-typed-evidence-contract.md) | 2026-11-09 | Define stable evidence, assertion, provenance, determinism, and deletion semantics for v1 |
