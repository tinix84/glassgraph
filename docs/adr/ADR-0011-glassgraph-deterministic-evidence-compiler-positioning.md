# ADR-0011: Position glassgraph as a deterministic typed-evidence and ontology compiler, not a second-brain app

- Date: 2026-08-29
- Status: accepted

## Context

Source: `docs/research/2026-08-29-memory-second-brain-landscape.md` (2026-08-29), an architecture-level review of official repositories, source code and published papers. The finding: Markdown-first storage, BM25 + vector hybrid search with reciprocal-rank fusion, byte-span citations, local embeddings, MCP surfaces, similarity graphs, schema validation and golden-query evaluation are all already shipped by competitors — GBrain treats Markdown/Git as system of record with a rebuildable DB projection and public regression gates; GrooveSeek and QMD each own a complete local retrieval stack. Rebuilding any of that would be waste. glassgraph today is an experimental deterministic entity linker and graph builder, not a retrieval engine.

## Decision

Narrow the product to: **a deterministic typed-evidence and ontology compiler for editor-owned Markdown research wikis** — it turns files into reproducible entity, relation and evidence artifacts, joins them to a replaceable retrieval backend, and leaves generic search infrastructure and answer generation to downstream tools.

- Build: a typed evidence IR with stable content-addressed IDs for files, headings, spans, entities, predicates and assertions; a reproducible compiler with a build manifest and `verify-build`; an evidence-aware retrieval join; compiler-specific evaluation.
- Reuse: GrooveSeek as the preferred first retrieval backend, QMD as second backend and independent benchmark, NetworkX at current graph scale, existing editors and chat clients.
- Do not build: a note editor, a chat app, agent memory, accounts/cloud sync, a pluggable vector/graph database zoo, server infrastructure before scale tripwires, LLM-generated community reports as canonical knowledge, or another native FTS/BGE/RRF stack before an adapter benchmark proves a concrete unmet requirement.
- Replace the blanket "byte deterministic" claim with three honest tiers: A exact (parsing, chunk IDs, Aho-Corasick spans, derived edges, exports), B environment-pinned (dense embeddings, cross-encoders), C advisory (anything LLM-generated, outside the canonical build).
- No native retrieval work begins before a frozen 50-100 question, evidence-ID-level benchmark names the backend with evidence.

## Alternatives considered

- Becoming a general AI second brain / chat-with-documents / agent-memory / GraphRAG product — rejected: crowded categories whose headline features are no longer differentiated.
- Building a native FTS5 + BGE-M3 + RRF + reranker stack — rejected up front: commodity, and QMD's own issue tracker shows full CPU reranking can take tens of seconds while generic expansion can *reduce* precision on tightly structured technical notes.
- Copying an existing Obsidian similarity plugin's code — rejected: it is source-available with restrictions on competing offerings; use only public ideas and independent code.
- Adding Neo4j/Chroma — rejected before scale tripwires are met.

## Consequences

- The moat is execution on five inseparable properties: Markdown-only authority with disposable content-addressed indexes, deterministic multilingual CPU-first extraction, exact-passage plus content-hash provenance for every edge and result, a genuine zero-LLM retrieval path, and a committed corpus-specific benchmark.
- The graph must never be the only retrieval route; graph boosts stay optional and evidence-gated, because recorded relation yield from prose bullets is weak.
- Known threats to manage: GBrain absorbing the wedge, QMD winning the retrieval layer, the determinism claim backfiring, a second source of truth appearing accidentally, "less token" becoming "more local compute", private-corpus overfitting, and graph theater.
- Editor independence becomes a tested contract: deleting glassgraph must leave a complete, useful wiki.
