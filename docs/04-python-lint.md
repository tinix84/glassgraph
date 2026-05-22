# 4. When LLM curation fails — Python lint

*Part 4 of 8 in the glassgraph journey.*

## The drift problem

After three months and ~300 source pages of LLM-curated wiki content, I started running into recurring issues:

- A page's `aliases:` field would say `["Tesla", "TSLA", "特斯拉"]` but `aliases_cn` would only list `[]`. The union-of-EN-and-CN invariant had silently broken.
- A source page would `touches: '[[Texas-Instuments]]'` (typo). Obsidian renders this as a broken wikilink, but it doesn't fail the ingest. I'd only notice when I happened to click the link.
- Two entity pages would exist for the same thing: `Wolfspeed.md` and `Wolfspeed-Inc.md`, each with a few sources, neither linked to the other.
- A theme page would assert "Huawei uses SiC across its inverter line" and a different theme page would assert "Huawei still ships IGBT in its DriveONE traction inverter," both citing the same teardown. Real contradiction, no resolution.
- A new source clipping would mention "BYD" in its body 17 times but the source page's `touches:` field would have no `[[BYD]]` entry.

None of these are LLM hallucinations. They're entropic drift — small inconsistencies that accumulate when the curator is fast and patternless. Every individual error is forgivable; the aggregate is wiki rot.

The shift in my thinking, around month four: **let the LLM curate, but make a deterministic process verify**.

## The eight lints

I wrote a Python module (`lint.py`) that runs eight checks across the whole wiki. None of them auto-fix; they report.

| # | Check | What it catches |
|---|---|---|
| 1 | **Contradictions** | Scans entity pages for `## Contradictions to resolve` sections (the LLM writes these when it detects conflict) — surfaces them in one report |
| 2 | **Orphan pages** | Pages with zero inbound `[[wikilinks]]` (excluding index/log/overview) — usually means a stub never got expanded or a renamed page left an orphan |
| 3 | **Stale stubs** | Pages tagged `[stub]` for >30 days — the expansion queue is failing |
| 4 | **Uncited entities** | Entities mentioned in source pages but with no entity page of their own — extraction candidates |
| 5 | **Index sync** | Every page should appear in `index.md`; no dead index entries |
| 6 | **Alias coverage** | Entities with a non-EN canonical name but empty `aliases_cn` (and vice versa) |
| 7 | **Theme health** | Themes with `status: open` and no update for >60 days — going stale |
| 8 | **Data gaps** | Open-questions sections in themes that haven't been filled — sources to find |

Later I added a ninth — `check_aliases_drift` — after a one-day incident where 161 alias terms appeared in pages' `aliases:` union field but were missing from either `aliases_en` or `aliases_cn`. The lint catches the invariant violation. I auto-promoted the 161 invisible terms into the right per-language fields once, then let the lint guard against future drift.

## The pattern: LLM proposes, deterministic verifies

This is the model I converged on, and it's the model I'd recommend to anyone building LLM-curated content systems:

```
+----------+        +------------+         +----------+
|   LLM    |        |  Wiki      |         |  Lint    |
|  curates | -----> |  storage   | <------ |  checks  |
|          |        |            |         |          |
+----------+        +------------+         +----------+
                                                 |
                                                 v
                                          Report (no auto-fix)
                                                 |
                                                 v
                                          Human reviews, decides
                                                 |
                                                 v
                                        Next LLM curation pass
```

The lint never auto-fixes. Auto-fixing means trusting a regex against a hard problem (alias drift, contradictions) and that trust is unwarranted. The lint is a report. I read it weekly. Sometimes I run a targeted ingest to fix something. Sometimes I let the LLM batch-fix a category in its next session. The point is: **the human stays in the verification loop, but the work of verification is automated**.

## A concrete example — alias collision

The lint flags this:

```
CRITICAL — alias collision: 'StarCharge 7kW AC charging pile' resolves to
both 'StarCharge-7kW-AC-Charging-Pile' and 'StarCharge-Chenxing-7kW'.
Keeping first; second is shadowed.
```

What happened: two product pages were ingested from two separate teardowns. Both share an alias because that's how the product is referred to in Chinese-language sources. The wiki has two pages, both legitimate, both reachable by a name that now resolves ambiguously.

The deterministic fix is *not* automatic. It requires me to decide:

- Are these the same product, just renamed? (merge)
- Are they distinct products with overlapping marketing names? (rename one, narrow the alias)
- Did the LLM make a mistake? (delete one)

Only I can answer that. But I only have to answer it *after the lint surfaces the conflict*. Without the lint, I'd never know.

## What the lint can't catch

Two failure modes are out of reach for deterministic checks:

1. **Hallucinated facts.** The lint can't verify that "Huawei DriveONE uses Onsemi NVG450A120L5DSC IGBT" is true — only that the claim is properly cited to a source. If the LLM misread the source and the source actually says it's a different part number, the lint won't catch it. Spot-checks against the raw source page (which the LLM cites) are the mitigation.
2. **Missed extractions.** If the LLM ingests a clipping and forgets to add `[[BYD]]` to `touches:` even though BYD is mentioned 17 times in the body, the lint can't catch that. The source page looks structurally fine; the entity page just doesn't get the citation it deserves.

The second one — **missed extractions** — is what eventually drove me to write a deterministic entity linker. That's Part 5.

## What I learned from writing the lint

A few specific things stuck:

- **Reports are more powerful than auto-fixes.** Auto-fixing creates a dependency chain you can't audit; reports let you see the whole problem before deciding.
- **Severity matters.** I tag lint findings CRITICAL / WARN / INFO. CRITICAL blocks downstream tooling (e.g., extraction backfill aborts if any CRITICAL lints fire). WARN is reported but not blocking. INFO is for trend tracking.
- **Lint is the right place to invest engineering time.** Every lint I write is a class of LLM drift permanently removed from my attention.

The lint took about a day to write originally, and grew over six months as new drift patterns surfaced. It's now ~600 lines of Python — the most defensively-coded piece of the whole 2brain stack.

This was the first real piece of deterministic infrastructure I added on top of the LLM. It wouldn't be the last.

---

← Previous: [Part 3 — The wiki LLM](03-wiki-llm.md)
→ Next: [Part 5 — Stage 1 — Aho-Corasick entity linking](05-stage1-aho-corasick.md)
