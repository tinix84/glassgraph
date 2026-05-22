# 8. What's next — RAG, DB, and beyond

*Part 8 of 8 in the glassgraph journey.*

## Where this leaves things

Seven months in, the 2brain stack looks like this:

```
+----------------+
|  /raw/         |  IMMUTABLE — 716 clippings + 15k images
+----------------+
        |
        v
+----------------+
|  Wiki LLM      |  Claude Code ingests /raw, writes /wiki
|  (Claude Code) |
+----------------+
        |
        v
+----------------+
|  /wiki/        |  502 source pages, ~1400 entity pages, ~50 themes
+----------------+
        |
        +--> [lint.py]         Deterministic verification, 8 checks
        |
        +--> [glassgraph]      Deterministic entity linker
        |     ├── Stage 1     Aho-Corasick on alias dictionary
        |     └── Stage 2     BGE-M3 dense retrieval (opt-in)
        |
        +--> [graphify]        LLM-based extractor (cold-start, discovery)
        |
        +--> [comparison]      Framework comparing the two
```

Everything above this paragraph is built. Everything below is the work I haven't done yet.

## RAG comparison — the next natural benchmark

If knowledge-graph extraction is one half of the picture, **retrieval-augmented generation** is the other. The next benchmark I want to run is: given the same wiki, how do different RAG pipelines compare at *answering* questions over it?

The candidates I want to compare:

| RAG approach | What it does | Hypothesis |
|---|---|---|
| **Vanilla embedding RAG** (e.g., FAISS over chunked wiki bodies) | Retrieve top-K chunks, stuff into context, generate answer | Baseline. Should work but lose graph context. |
| **GraphRAG** (Microsoft's variant) | Build community-level summaries during indexing, retrieve summaries + entities | Should do better on broad questions ("what are the SiC vendors?"), worse on specific ones. |
| **glassgraph + naive LLM** | Use the deterministic graph for retrieval; LLM only for generation | Should be more reproducible. Possibly worse at synthesis. |
| **LightRAG / nano-graphrag** | Lightweight graph-aware retrieval | Open question — these are very new. |

The interesting metrics aren't BLEU or ROUGE — they're **citation correctness** (does the answer cite the right sources?) and **reproducibility** (does the same question on the same corpus produce the same answer next week?).

I don't have this built yet. It's the obvious next chapter.

## Vector DB benchmarks — once the corpus grows past 5,000 pages

Right now, my embedding store is a folder of `.npy` files plus a manifest JSON. That works fine at 1,400 entity pages. It will break somewhere between 5,000 and 50,000.

The candidates to migrate to:

- **Qdrant** — Rust-based, embedded mode is local, deterministic with right config. My current favorite hypothesis.
- **Weaviate** — Java/Go, more complex, more features (hybrid search built-in).
- **LanceDB** — disk-first, sister to DuckDB, very promising for local use.
- **pgvector** on Postgres — least exciting, most boring, probably correct long-term.

The deciding criterion will likely be the same as the rest of the stack: which of these can produce **byte-reproducible** retrievals given the same inputs and the same model state? That's a much narrower question than which of them is fastest or has the most features.

If I were betting today: pgvector for the long term, LanceDB if I want zero-ops, Qdrant if I want fastest-while-still-local. I won't know until I benchmark.

## The promotion pipeline — graphify discovers, glassgraph absorbs

The most interesting near-term project is the **promotion path** I sketched in Part 7. Concretely:

1. Run graphify on new material (especially academic papers).
2. Diff graphify's output against glassgraph's alias dictionary.
3. Surface entities where graphify has ≥3 references but glassgraph has zero hits.
4. Propose them as new wiki entity pages (with type, aliases, initial body skeleton).
5. Human (me) reviews, accepts/rejects, edits.
6. New entity pages flow into the next glassgraph rebuild deterministically.

This makes graphify the **discovery surface** and glassgraph the **production surface**. Over time, the deterministic system absorbs the discoveries, and the LLM tier only has to focus on *new* material.

The bigger structural point: most wiki content stabilizes. After six months, 80% of my source pages haven't changed; the entities they touch don't change either. Running an LLM extraction on stable content is pure waste. Running it on the 20% of new material per month is exactly the right scope.

## The glassgraph #1 issue — graph-analysis features

Already filed: [glassgraph#1 — god nodes, surprising connections, suggested questions](https://github.com/tinix84/glassgraph/issues/1).

These are the three terminal outputs graphify produces that glassgraph currently doesn't:

- **God nodes** — top-N entities by in-degree (the "core abstractions" of the corpus).
- **Surprising connections** — entity pairs that cross community boundaries or have unusually high cosine similarity without a direct edge.
- **Suggested questions** — high-betweenness bridge nodes phrased as questions.

All three are computable from the existing graph + Stage 2 embeddings. None require an LLM. Implementing them gives glassgraph the same *navigation affordances* as graphify, deterministically.

This is probably the next chunk of code I write on glassgraph itself.

## Some open questions I genuinely don't know the answer to

A few honest unknowns:

1. **How do you evaluate a personal-research RAG without a ground-truth Q&A set?** Industry RAG benchmarks use curated Q&A. I don't have that for my domain. Generating one with an LLM and grading another LLM against it has obvious problems. There may not be a good answer here.
2. **At what corpus size does the markdown-files-as-database approach break?** 1,400 entity pages is fine. 50,000 would not be. The transition point depends on how often I rebuild indices vs. how often I query. I don't have hard numbers yet.
3. **Does this approach generalize beyond power electronics?** The corpus has very specific properties — heavy CJK content, dense in named entities (companies, part numbers), low in narrative prose. A research wiki for, say, economic history would look quite different. I don't know whether the same tools would work there.
4. **What's the half-life of an entity page?** Companies pivot. Products get discontinued. Technologies become obsolete. The wiki currently has no notion of "this fact was true as of 2024." How do I encode temporal decay without making every page a maintenance nightmare?

## What this whole journey has taught me

If I had to compress seven months of work into three takeaways:

1. **LLMs are fast curators and bad janitors.** Use them to do the initial work; use deterministic infrastructure to keep that work clean over time. The lint module is the unsung hero of this whole stack.
2. **Determinism is a feature, not a default.** Most of the AI tooling ecosystem assumes you don't care about reproducibility. For personal knowledge bases that compound over years, you do. Pinning seeds, caching embeddings, manifesting outputs — none of these are exciting work, but they're the work that makes the rest matter.
3. **Build the comparison framework before you commit to a tool.** I almost shelved glassgraph in favor of graphify before I built the comparison. Building it surfaced the trade-off structure and led to the (better) "use both" answer. The most durable artifact from this whole journey isn't the wiki, isn't glassgraph, isn't even the comparison report — it's the *framework* that lets me re-evaluate next year when the tooling lands differently.

The system isn't done. I doubt it ever will be. But it compounds now, and the deterministic guardrails mean it doesn't rot. That's enough to keep building on.

---

← Previous: [Part 7 — The graphify comparison](07-graphify-comparison.md)

← Back to [the home page](index.md)

---

*If you're building something similar, the [glassgraph repo](https://github.com/tinix84/glassgraph) is the artifact, and [Issue #1](https://github.com/tinix84/glassgraph/issues/1) is the roadmap for the graph-analysis features that come next.*

*If you read this on Substack — thanks for reading. The series will continue with the RAG comparison in [your next episode]. Subscribe if you want to know when the benchmarks land.*

*If you're considering a similar journey: start with the wiki, build the lint before the linker, build the comparison before you pick a tool.*
