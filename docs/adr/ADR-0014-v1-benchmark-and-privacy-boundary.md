# ADR-0014: Freeze a private evidence benchmark with a synthetic public fixture

- Date: 2026-11-09
- Status: accepted

## Context

ADR-0011 requires an evidence-ID benchmark before Glassgraph selects a retrieval backend. The existing Graphify comparison measures entity-name overlap. It does not test ranked passage retrieval, negative queries, or exact evidence provenance.

The 2brain corpus contains private notes, licensed clippings, annotations, source paths, and URLs. Query text, evidence identifiers, hashes, and detailed results can also disclose private source material.

## Decision

Glassgraph v1 uses two benchmark partitions that share one record schema and one metric implementation.

The private benchmark contains 60 2brain queries:

- 45 positive queries have one or more adjudicated evidence passages.
- 15 negative queries require an empty result or an explicit abstention.
- The development split contains 40 queries: 30 positive and 10 negative.
- The frozen evaluation split contains 20 queries: 15 positive and 5 negative.

Each positive query has evidence judgments with three grades: direct, supporting, and irrelevant. Each judgment cites an evidence ID from ADR-0013. Negative queries have no relevant evidence ID.

A positive query defines one or more required evidence groups. IDs in one group are interchangeable alternatives. The result is complete only when the top results satisfy every required group. Thus, `{A, B}` in one group means A or B. Two groups `{A}` and `{B}` mean A and B. Group Recall at 5 is the number of satisfied groups divided by the number of required groups.

The public fixture benchmark contains 20 synthetic technical queries: 15 positive and 5 negative. Glassgraph authors all fixture text. The public fixture includes hard distractors, multilingual aliases, repeated passages, renamed headings, deleted documents, and no-answer cases.

M1 issue #18 must add the public fixture under `tests/fixtures/benchmark/v1/` before it claims public benchmark coverage. The private benchmark stays in the vault-side `.glassgraph/benchmarks/private/v1/` directory. The public repository and its build artifacts must not contain private:

- Markdown, assets, annotations, or source snippets.
- Paths, filenames, URLs, Zotero keys, or source identifiers.
- Query text, evidence IDs, content hashes, or relevance judgments.
- Per-query scores, backend logs, graph exports, or failure examples.

Private benchmark execution is local and offline. The runner must not send the corpus, queries, or results to an external API. Local models and local retrieval backends can process the private benchmark.

Public reports can contain only aggregate results. A category needs at least five queries before publication. Reports include:

- Group Recall at 5 for required direct and supporting evidence groups.
- Normalized discounted cumulative gain at 10 for graded relevance.
- False-positive rate at 5 for negative queries.
- Median and 95th-percentile query latency.
- Full build time and derived-index size.
- Peak working-set memory when the backend can report it.

The benchmark manifest records the schema version, corpus snapshot hash, query-set hash, judgment-set hash, split membership, and adjudication date. A judgment correction creates a new benchmark version. Tuning can use only the development split. The frozen evaluation split is run after backend settings are locked.

## Alternatives considered

- Publishing redacted private questions was rejected. Technical wording, paths, and hashes can identify private sources.
- Using only synthetic fixtures was rejected. Synthetic text cannot select a backend for the real corpus.
- Using an LLM to generate or grade the private benchmark was rejected. The benchmark must not inherit the tested system's errors.
- Publishing per-query results was rejected. Failure examples can disclose source content.
- Reusing entity-overlap precision and recall was rejected. These metrics do not measure ranked evidence retrieval.
- Allowing benchmark edits in place was rejected. A frozen version is necessary for comparable results.

## Consequences

- Public continuous integration can test the full benchmark schema after M1 adds the synthetic fixture.
- Backend selection uses the private evaluation split and aggregate local results.
- A public contributor cannot reproduce private scores without the owner's corpus and judgments.
- Glassgraph can compare zero-language-model and local-model paths with the same evidence-level measures.
- The owner must author and adjudicate the 60 private queries before the M1 backend benchmark can finish.
