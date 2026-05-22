# 1. Why a personal LLM wiki

*Part 1 of 8 in the glassgraph journey.*

## The reading problem

For the past two years I've been reading constantly about power electronics — specifically the EV powertrain stack: SiC and GaN devices, inverter topologies, on-board chargers, DC fast chargers, AI datacenter power, the supply chain around them. The material is split across:

- **Bilibili teardowns**, mostly Chinese-language, often the *only* source for what's actually inside a given product
- **iCharger / ChargerLAB articles** — sometimes a mix of English and Chinese
- **arXiv papers** on solid-state transformers, vertical power delivery, soft-switching topologies
- **APEC and ECCE conference proceedings**
- **Industry analyst reports** (Yole, Omdia)
- **Manufacturer datasheets** when I can find them

The volume isn't the hardest part. The hardest part is that **none of it compounds**. Every time I want to answer a question — "which vendors are shipping SiC traction inverters in production this year?" — I'd have to re-derive the answer from scratch, by re-reading or re-searching across the same sources I'd already read.

That's the failure mode I wanted to fix.

## What "second brain" usually means, and why it didn't work for me

The dominant pattern in 2024-2025 personal-knowledge-management is "a second brain" — coined most prominently by Tiago Forte, but widely adapted. The idea: capture, organize, and link your reading so that you can retrieve it later.

The tools that own this space — Notion, Roam Research, Obsidian, Logseq — all share a common assumption: **you, the human, do the curation**. You read something, you write a note, you link it to other notes. The system stores and surfaces; it doesn't synthesize.

For my use case, that didn't scale. I was reading 30-50 Chinese teardowns a month. Even if I'd been disciplined enough to write a note per teardown, I wouldn't have been disciplined enough to identify and link every cross-reference between them — to notice, for example, that three different teardowns mentioned the same Infineon SiC MOSFET driver IC, or that two seemingly unrelated chargers used the same Texas Instruments controller.

I needed something that could do the cross-referencing for me — automatically, comprehensively, every time I added a new source.

## What "LLM-native" knowledge bases promised, and where they fall short

The other end of the spectrum is fully LLM-driven: feed everything to a RAG pipeline, ask questions, get cited answers. ChatGPT custom GPTs, NotebookLM, Perplexity's Spaces, and dozens of open-source RAG frameworks all sit here.

They have two problems for my use case:

1. **They re-derive on every query.** The knowledge is in the model's response context, not in a structured artifact I can browse, version, share, or audit. If I ask the same question tomorrow, the answer changes — sometimes subtly, sometimes badly.
2. **They are opaque to inspection.** I can't tell what the system "knows" without asking it questions. There's no map. There's no way to spot gaps.

For a personal research wiki where I might want to ask "what teardowns do I have on Huawei DriveONE?" three years from now and get the same answer — there had to be a **persistent, structured, inspectable** artifact in the middle.

## The shape of the answer

What I wanted, roughly:

- **Raw sources** stored verbatim, in a format I own, that I never modify.
- **A curated wiki layer** with one page per entity (companies, technologies, products, themes), built on top of the raw sources.
- **An LLM in the loop** for the curation — because hand-writing a wiki page for every Huawei product mentioned across 200 teardowns is a non-starter.
- **Deterministic guardrails** so the LLM doesn't silently corrupt the wiki over time.
- **A graph view** — because the value of a knowledge base isn't the pages, it's the *connections* between them.

That last part is what eventually became glassgraph. But the first four parts had to come first.

## The Karpathy push

If there's one thing that tipped me from "I should organize my reading" to "I should build a system for this," it was Andrej Karpathy's various 2024-2025 talks and posts about LLM-native software engineering. The line that stuck: **you don't refactor your codebase, you regenerate it from a higher-fidelity description**.

I wanted to apply that to my reading. The "higher-fidelity description" would be a markdown wiki — the regeneration target would be a graph that connects everything.

Two years later, this is what it looks like.

---

→ Next: [Part 2 — Obsidian as substrate](02-obsidian-substrate.md)
