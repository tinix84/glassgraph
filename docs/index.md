# glassgraph

> Deterministic entity linker and graph builder for personal research wikis. Aho-Corasick + BGE-M3 dense retrieval. CPU-only, byte-reproducible.

## What this site is

Two things, in one place:

1. **Tool docs** — how to install and use glassgraph (see the [README on GitHub](https://github.com/tinix84/glassgraph)).
2. **The journey** — an eight-part write-up of how this tool came to exist. Why a deterministic entity linker, starting from a pile of Chinese teardown clippings, ended up being the right answer to a personal-knowledge-management problem.

The journey series begins with the original pain (too much reading, no compounding knowledge) and ends with a head-to-head comparison against [graphify](https://github.com/safishamsi/graphify), the popular LLM-based knowledge-graph extractor. The findings might surprise you. They surprised me.

## Read the journey

| # | Part | What it covers |
|---|---|---|
| 1 | [Why a personal LLM wiki](01-origin.md) | The pain that started this. Information overload from power-electronics research; why search-and-summarize doesn't compound knowledge. |
| 2 | [Obsidian as substrate](02-obsidian-substrate.md) | Why a markdown vault and not a database. The `/raw` vs `/wiki` split. |
| 3 | [The wiki LLM](03-wiki-llm.md) | Letting Claude curate the wiki from raw clippings. Page types, the `touches:` field, the ingest workflow. |
| 4 | [When LLM curation fails — Python lint](04-python-lint.md) | The drift problem. Eight deterministic lints. LLM proposes, deterministic verifies. |
| 5 | [Stage 1 — Aho-Corasick entity linking](05-stage1-aho-corasick.md) | Dictionary-based extraction. CJK boundary handling. Audit trail per hit. |
| 6 | [Stage 2 — BGE-M3 dense retrieval](06-stage2-bge-m3.md) | Dense embeddings to solve the cold-start problem. Determinism in a sentence-transformer pipeline. |
| 7 | [The graphify comparison](07-graphify-comparison.md) | Five axes, two tools, one corpus. The trade-off is real and structural. |
| 8 | [What's next — RAG, DB, and beyond](08-whats-next.md) | RAG comparison, vector DB benchmarks, the promotion pipeline. |

## Why publish this?

Most of what I read about knowledge graphs, RAG, and personal AI is either marketing or surface-level demos. The actual decisions — what schema, when to use LLM, when not to, how to handle CJK without an LLM in the loop, what determinism costs and buys you — are buried in code or never written down.

This is my attempt to write down those decisions, for one specific personal corpus, in enough detail that someone else can replicate the reasoning if not the choices.

If you're building something similar, the [glassgraph repo](https://github.com/tinix84/glassgraph) is the artifact and [Issue #1](https://github.com/tinix84/glassgraph/issues/1) is the roadmap. Pull requests welcome.

## About the author

Riccardo Tinivella — power electronics & EV powertrain research. The wiki this tool serves is a personal research vault on inverters, chargers, SiC/GaN devices, and the supply chain around them. None of it is corporate output; all of it is personal.
