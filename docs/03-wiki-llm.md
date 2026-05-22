# 3. The wiki LLM

*Part 3 of 8 in the glassgraph journey.*

## The job description

Given:

- A growing folder of raw clippings, mostly Chinese teardowns
- An empty wiki with a defined directory structure (`/wiki/companies/`, `/wiki/technologies/`, `/wiki/products/`, `/wiki/themes/`, `/wiki/sources/`)
- A `CLAUDE.md` file describing the schema and conventions

I wanted: an LLM that, given a new clipping in `/raw/X.md`, would write `/wiki/sources/X.md` and update or create the entity pages that the clipping mentions.

This is what Claude Code (Anthropic's CLI) does for me. The reason it works specifically with Claude Code rather than a custom RAG pipeline is **persistent project context** — `CLAUDE.md` is read at the start of every session, so the LLM doesn't need to be told the schema each time.

## The schema, in detail

Every wiki page has YAML frontmatter:

```yaml
---
type: company | technology | product | theme | source
aliases: [union of aliases_en + aliases_cn]
aliases_en: [English aliases — semantic, for filtering]
aliases_cn: [Chinese aliases — semantic, for filtering]
tags: [...]
created: YYYY-MM-DD
updated: YYYY-MM-DD
sources: [filenames in wiki/sources/ that mention this entity]
---
```

Three separate alias fields. `aliases_en` and `aliases_cn` are semantic — they let you filter "show me all Chinese-named entities." `aliases` is the *union* of the two — this is what Obsidian's wikilink resolution actually uses. The LLM keeps all three in sync. The deterministic lint catches drift (see Part 4).

Per-type extras matter:

- **company**: `country`, `kind: oem|tier1|semi|foundry|startup|publication|lab|vc|government|consultancy|other`
- **technology**: `category: semiconductor|topology|control|system|infra|materials`
- **product**: `vendor: [[Company]]`, `category: inverter|charger|psu|optimizer|motor|...`, `released: YYYY-MM-DD`
- **theme**: `thesis: <one-liner>`, `status: open|consolidated|stale` — *and a theme requires ≥5 distinct sources as evidence before it can exist*
- **source**: `source_url`, `source_lang: cn|en|other`, `source_kind: teardown|market|technical|news|academic|other`, `touches: [wikilinks to entity pages updated]`

The body of each page follows a per-type skeleton:

- **company body**: identity (1 line) → snapshot → key technologies (`[[wikilinks]]`) → key products → notable mentions (cited) → open questions
- **technology body**: definition (1 line) → applications → key players → key products → trade-offs / state of the art → open questions
- **product body**: specs (V/A/W/η) → architecture → key components → teardown highlights → comparisons
- **theme body**: thesis → evidence (cited) → counter-evidence → implications → open questions / next sources to find
- **source body**: TL;DR (3-5 bullets) → key extractions (companies/technologies/products/themes mentioned) → wiki updates applied → quality verdict → notable quotes (the only place CN inline is allowed)

## The `touches:` field — the graph edge made explicit

This is the most important field in the source schema:

```yaml
touches:
  - "[[Tesla]]"
  - "[[Tesla-Model-3-inverter]]"
  - "[[SiC-MOSFET]]"
  - "[[STMicroelectronics]]"
  - "[[Texas-Instruments]]"
```

Every source page declares which entity pages it "touches" — i.e., which entities it provides evidence for. This is the **edge list** of the knowledge graph, written explicitly into the data layer.

Why is this so important? Because:

- The graph view in Obsidian renders from these edges. You can see which sources support which entities.
- Themes require ≥5 distinct sources. Counting `touches:` references is how you know if a theme is well-supported.
- When you delete a source, you know which entity pages to revisit.
- When you compare extraction tools (Part 7), this is your ground truth.

The `touches:` field is the workhorse that makes the rest possible.

## The ingest workflow

Triggered by typing `ingest raw/X.md` in a Claude Code session:

1. **Pre-check** — does `wiki/sources/X.md` already exist? If yes, skip (idempotent).
2. **Read** the raw file's frontmatter + body.
3. **Extract** source metadata (lang, url, created, kind).
4. **Internal TL;DR** — what is this clipping about, in 3-5 bullets?
5. **Entity matching** — for each entity candidate, check `index.md` for existing pages; classify as EXISTING vs NEW.
6. **Theme analysis** — does this clipping touch any existing themes? Are there ≥5 sources for any new pattern?
7. **Write** `wiki/sources/X.md` with the schema above.
8. **Apply entity updates** — every claim cites a source via `[[wikilink]]`.
9. **Update `index.md`** — new pages, updated dates, stub list.
10. **Append to `log.md`** — one line per ingest, op type, stats.
11. **End-of-run report** — pages created, pages updated, contradictions flagged, open questions, warnings.

For batches of clippings, the workflow dispatches parallel Sonnet subagents — 2-4 for small batches, up to 8 for batches of 50+. Each subagent processes its slice with the same schema; results are merged at the index/log step.

## The hard part — language

By far the hardest discipline is keeping CN and EN in sync. The rules:

1. **Entity/theme/product page bodies are EN-only.** No inline CN, no exceptions.
2. **CN preservation goes through three explicit paths:** `aliases_cn` in frontmatter (filterable), `[[wikilinks]]` to source pages (whose filenames preserve original CN), and source page bodies (the *only* place CN inline is allowed, in the "notable quotes" section).
3. **Numerical claims from CN sources preserve original units verbatim** with citation: kW/L, A, V, ¥, etc.

Why EN-only bodies? Because consistency. Once you allow inline CN in entity bodies, every reviewer has to context-switch. And themes — the highest-value pages — need to read as fluent English synthesis, not as bilingual notes.

## What I gave up vs. what I gained

What I gave up:

- The wiki cannot be edited offline by hand at the rate I'd want. Without the LLM I'd be too slow.
- I trust an LLM to summarize Chinese-language content I cannot fully verify myself in real time. (Mitigation: the source page always includes raw quotes, and I spot-check.)
- I burn Claude Code Max subscription minutes on every ingest. Not free.

What I gained:

- 500+ source pages curated, ~1400 entity pages, ~50 themes — far beyond what I could maintain by hand.
- Every claim in the wiki cites a source via `[[wikilink]]`. No floating assertions.
- I can ask "what do I have on Huawei DriveONE?" and get a coherent answer because the wiki page exists.

But three months in, I started noticing the LLM was making mistakes — silently, accumulating. Aliases drifting out of sync, broken wikilinks creeping in, contradictions on entity pages that I missed.

The LLM curation worked. It also needed guardrails.

That's Part 4.

---

← Previous: [Part 2 — Obsidian as substrate](02-obsidian-substrate.md)
→ Next: [Part 4 — When LLM curation fails — Python lint](04-python-lint.md)
