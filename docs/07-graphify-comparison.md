# 7. The graphify comparison

*Part 7 of 8 in the glassgraph journey.*

## Why benchmark, and why graphify

By month seven I had a working tool — glassgraph — that produced a deterministic entity graph from a personal wiki. But "deterministic" is only useful if the alternative is *worse*. Maybe an LLM-based extractor produced a better graph and I was wasting my time on Aho-Corasick and embedding manifests.

The natural benchmark target was [graphify](https://github.com/safishamsi/graphify) — a popular open-source LLM-based knowledge-graph extractor that, as of mid-2026, has 51k+ stars, integrates as a Claude Code skill, and produces an output format conceptually similar to my own (nodes + edges, with audit-trail fields like `confidence: EXTRACTED / INFERRED / AMBIGUOUS`).

The bet I wanted to test was specific: **does the LLM-based extractor produce a strictly better graph on my corpus, or is determinism + speed a worthwhile trade for some loss of recall?**

If graphify clearly won, I'd shelve glassgraph and adopt graphify. If glassgraph clearly won, I'd be more confident investing further in it. The interesting (and ultimately correct) answer turned out to be neither.

## Methodology — five axes, one corpus, one demo subset

I built a comparison framework — `.tools/comparison/` in the source wiki, also published in the glassgraph repo under `comparison/` — that loads both tools' outputs into networkx graphs and computes the same five axes against each.

The five axes:

1. **Determinism** — run each tool twice, compute Jaccard similarity between runs.
2. **Precision/Recall** vs. the wiki's existing `touches:` lists (the "ground truth" — but see below for why this framing is mostly wrong).
3. **Audit trail / explainability** — qualitative, three sourced examples.
4. **Speed and cost** — wall-clock, API cost, incremental-update behavior.
5. **Graph-structural metrics** — node/edge counts, density, top-N in-degree centrality.

The corpus: a curated **25-file demo subset** of the wiki's 502 raw clippings — 10 CN teardowns, 10 EN articles, 5 academic arXiv papers. Diverse enough to be representative; small enough that graphify could process it in a single Claude Code session without overwhelming the LLM budget.

Why a subset? Because graphify's LLM extraction at full corpus scale would have meant processing 502 markdown files plus 15,335 inlined images via vision — costing hours of subagent dispatch. The subset gives an apples-to-apples sample without that cost.

## What the framework does

Roughly 700 lines of Python across four modules:

- `load_ours.py` — parses every `wiki/sources/*.md` `touches:` frontmatter into a networkx DiGraph (source → entity edges).
- `load_graphify.py` — defensive parser for graphify's `graph.json`. Tolerates schema drift (graphify went through multiple schema versions during the comparison's development).
- `metrics.py` — precision/recall/F1, Jaccard similarity, graph-structural summaries, and an aggressive name normalizer (lowercase + drop parentheticals + collapse non-alphanumeric + strip corporate suffixes) for fair comparison.
- `compare.py` — CLI orchestrator that ties everything together and renders a markdown report with all five axes.

20 unit tests across three test files cover the modules, including a regression test for the name-normalizer's most important case: `SiC-MOSFET` and `SiC MOSFET` must collapse to the same string after normalization, since that exact difference shows up in dozens of entity labels between glassgraph and graphify.

## The numbers — and why the headline is misleading

The headline P/R on the demo subset, with aggressive slugify normalization and apples-to-apples source filtering:

| Metric | Graphify EXTRACTED-only vs. glassgraph `touches:` |
|---|---|
| Precision | 0.135 |
| Recall | 0.084 |
| F1 | 0.100 |
| Sources scored | 20 (of 25) |

Read literally, that says graphify recovers about 8% of what glassgraph thinks should be there, with about 14% precision. Numerically terrible.

This was the most important framing decision in the whole writeup: **these numbers do NOT mean graphify is doing badly**. They measure *vocabulary overlap* between two tools that produce graphs over different vocabularies:

- Glassgraph emits entities constrained to a **curated dictionary** of ~1400 canonical names. The wiki's `touches:` IS the output of glassgraph; using it as ground truth is asking "does graphify rediscover what glassgraph found?" — a tooling-mismatch question, not a quality question.
- Graphify emits **free-form entity labels** including specific part numbers (`Infineon IPW60R125CP`), topology variants (`Three-Phase Active PFC Topology`), and novel concepts (`DG Matrix (SST Startup)`) that glassgraph's curated dictionary doesn't carry.
- Even after aggressive name normalization, structurally distinct names like `Tesla Model 3 Inverter` (graphify) vs. `Tesla-Model-3-inverter` (glassgraph) will not collapse — and shouldn't, because the granularity is different.

The right reading of P=0.135 is **not** "graphify is bad." It's "the two tools cover overlapping-but-non-identical vocabularies." Each catches things the other doesn't.

## What each tool actually wins on

The five axes split:

| Axis | Glassgraph | Graphify | Verdict |
|---|---|---|---|
| Determinism | Jaccard = 1.0000 (byte-identical reruns) | Single-run only, but structurally LLM-bound → varies | **glassgraph** |
| Precision / Recall vs `touches:` | (we ARE the ground truth) | 0.140 / 0.092 | not meaningful (see above) |
| Audit trail | Per-hit `span + alias + canonical + context` | Per-edge `confidence: EXTRACTED/INFERRED/AMBIGUOUS`, no span | **glassgraph** for granularity; **graphify** for cross-document inference |
| Speed (25-file subset) | < 1 second | Several minutes of parallel subagent dispatch | **glassgraph** |
| Cost | $0 (CPU-only) | LLM tokens × rate | **glassgraph** |
| Communities | networkx post-hoc | First-class output | **graphify** |
| Surprising connections | Not yet implemented | Cross-document INFERRED edges | **graphify** |
| Suggested questions | Not yet implemented | High-betweenness bridge nodes | **graphify** |
| Cold-start coverage | Zero on novel material | Discovers `DG Matrix`, `Innoscience`, etc. | **graphify** |

That last row is the one that mattered most for my use case. On the cold-start academic arXiv paper (G8FHMRQC) in the demo subset, glassgraph returned **one hit** (`thermal management`) — because academic vocabulary mostly isn't in my curated wiki yet. Graphify returned three nodes plus two INFERRED cross-document edges connecting concepts from this paper to concepts from other papers in the corpus. A genuine cross-paper discovery that glassgraph cannot perform.

## The synthesis — neither wins, both belong

After staring at the report for an hour, the conclusion that survived was:

> **Use both. Glassgraph for the curated 80% of the corpus where entities are known and reproducibility matters. Graphify for the cold 20% — new academic material, novel topical clusters, cross-document semantic discovery.**

And a **promotion path** between them:

1. Run graphify on new material (especially academic).
2. When graphify surfaces a concept across ≥3 sources, promote it into the wiki as a new entity page with proper aliases.
3. Next glassgraph run picks it up deterministically.
4. The corpus that's "cold" for glassgraph shrinks over time as discoveries get absorbed.

This is the honest answer. Not a clean win for either side. A real trade-off, with a defined path to combine the strengths of both.

## What I learned about benchmarking AI tools

Three lessons that generalize beyond this specific comparison:

1. **Your ground truth is probably your other tool's output.** If you're comparing two systems and using your own curated data as truth, you're measuring vocabulary overlap, not quality. The framing has to make this explicit or the numbers mislead.
2. **The five-axis split was load-bearing.** A single P/R number would have hidden the real picture. Splitting determinism, audit trail, speed, cost, and discovery as separate axes forced the comparison to be honest about *which dimension* a tool wins on.
3. **The demo-subset matters more than the full corpus for getting started.** I'd been worried about whether 25 files was "enough." It was — for surfacing the trade-off structure. The full corpus would have given more decimal places of confidence but wouldn't have changed any conclusions.

The full report, including the three sourced audit-trail examples and the graphify GitHub roadmap snapshot, is the demo deliverable — kept locally for now since it contains specific entity findings from the private wiki.

What's left to do? That's Part 8.

---

← Previous: [Part 6 — Stage 2 — BGE-M3 dense retrieval](06-stage2-bge-m3.md)
→ Next: [Part 8 — What's next — RAG, DB, and beyond](08-whats-next.md)
