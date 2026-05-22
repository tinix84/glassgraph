# 2. Obsidian as substrate

*Part 2 of 8 in the glassgraph journey.*

## Why markdown, not a database

The first real choice was the storage substrate. The candidates:

| Substrate | Pros | Cons |
|---|---|---|
| Notion | Beautiful UI, embedded databases, multi-platform | Cloud-locked. Cannot batch-process pages with local tooling. Markdown export is lossy. |
| Roam Research / Logseq | Bidirectional links, query language | Subscription-based, ecosystem already declining as of 2025. |
| PostgreSQL + custom UI | Total control | I'd spend more time on the UI than on the research. Wrong leverage. |
| **Plain markdown files** | Editable in any editor, greppable, diffable, future-proof | No queries out of the box. UI is the editor. |

I went with plain markdown — for one specific reason: **markdown files survive the tool that created them**. Notion goes out of business, my notes are still readable. The LLM landscape changes in 18 months, my files don't need to migrate. The format is decades old and outlives every product built on top of it.

The decision is reversible too: if I later want to load everything into a graph DB or vector store, the markdown is a clean input. The reverse — extracting clean markdown from a proprietary DB — usually isn't.

## Why Obsidian on top of markdown

Obsidian is a free-as-in-beer markdown editor that does two specific things well:

1. **Wikilinks** — `[[Entity Name]]` syntax that resolves to a page or to nothing (with a "create new" affordance).
2. **Graph view** — a visualization of which pages link to which, with hubs and orphans visible at a glance.

It is *not* a SaaS. It is *not* a server. It's a desktop app reading markdown files from a folder of my choosing. I could uninstall it tomorrow and lose nothing.

The other thing Obsidian gave me, without me realizing it would matter, was the **Web Clipper** browser extension. One click on a Bilibili teardown page or an arXiv abstract saves the article as a markdown file with proper frontmatter (URL, capture date, source language) and inlined image references. That single workflow handles 95% of my ingestion.

## The `/raw` vs `/wiki` split

The most important architectural choice was the directory layout:

```
2brain/
├── raw/                  IMMUTABLE — never write, rename, delete
│   ├── *.md              Obsidian Web Clipper exports
│   └── assets/           Inlined images (~15,000 webp/png files)
└── wiki/                 LLM-owned (read/write)
    ├── companies/        One page per company
    ├── technologies/     One page per technology (SiC-MOSFET, LLC-resonant-converter, ...)
    ├── products/         One page per product (Tesla-Model-3-inverter, Huawei-DriveONE, ...)
    ├── themes/           Cross-source synthesis pages (the highest-value type)
    └── sources/          1:1 mirror of /raw filenames — the metadata layer
```

The rule that makes this work: **never modify `/raw`**. Not the LLM, not me, not any tool. It's the canonical immutable record. The LLM only ever reads from `/raw` and writes to `/wiki`.

This solves a problem that would have killed the project otherwise: when the LLM screws up — and it does, regularly — the consequences are contained to `/wiki`. I can delete a corrupted wiki page and regenerate it from `/raw`. I cannot recover lost raw clippings if they get modified or deleted.

The `/wiki/sources/` mirror is a clever-by-necessity trick: for every file in `/raw/X.md`, there's a `/wiki/sources/X.md` that contains the LLM's *metadata* about that source (its TL;DR, the entities it mentions, the themes it touches). The bodies of raw clippings stay verbatim in `/raw`; the LLM's interpretation lives in `/wiki/sources/`.

## Wikilinks as the universal primitive

Every cross-reference in the wiki uses `[[wikilink]]` syntax. Not URLs, not filesystem paths. Why?

- **Wikilinks resolve through aliases.** A page named `Texas-Instruments.md` with `aliases: ["TI", "Texas Instruments", "德州仪器"]` in its frontmatter is reachable by any of those names. The body text can say `[[TI]]` and Obsidian renders it as a link to the canonical page.
- **Broken wikilinks are visible.** If `[[Entity-That-Does-Not-Exist]]` appears in a page, Obsidian renders it with a "create new" affordance. The graph view shows orphans. The deterministic lint (see Part 4) flags them.
- **They survive file renames** — if you update aliases. Which is how the wiki absorbs organizational drift without breaking.

For Chinese content this is critical. A teardown might mention "华为" (Huawei) inline. The wiki page is `Huawei.md` with `aliases_cn: ["华为"]`. The wikilink `[[华为]]` resolves correctly because the alias is in the frontmatter. The body of the company page itself is English-only — but the connection to Chinese sources is preserved through aliases.

## The image policy that took two iterations to get right

Wiki bodies **never** embed images. They reference them as non-embedding wikilinks: `[[abc123_MD5.webp]]`, which Obsidian resolves to the image in `/raw/assets/`.

Why? Because embedding makes diffs unreadable and makes the wiki bloated. The image lives in `/raw/assets/`. The wiki page just points to it. If I later want to publish the wiki to the web (e.g., this very docs site), the publishing step is when embedding happens — not the curation step.

## What this gave me

By the time the directory layout was settled — about three months in — I had:

- A growing pile of `/raw/` clippings, mostly Chinese teardowns, accumulating at 30-50 per month
- An empty `/wiki/` folder that I knew I couldn't fill by hand
- A schema (in my head, not yet written down) for what a wiki page should look like
- A workflow (Web Clipper) that captured new material with one click

What I didn't have: the system that would actually fill `/wiki/`.

That's Part 3.

---

← Previous: [Part 1 — Why a personal LLM wiki](01-origin.md)
→ Next: [Part 3 — The wiki LLM](03-wiki-llm.md)
