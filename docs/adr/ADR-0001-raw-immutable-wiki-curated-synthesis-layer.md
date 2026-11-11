# ADR-0001: Immutable `raw/` corpus with an LLM-owned `wiki/` synthesis layer

- Date: 2026-05-03
- Status: accepted

## Context

On 2026-05-03, the corpus contained about 437 mixed CN/EN clippings on power electronics and EV powertrains. The wiki needed to compound reusable knowledge instead of repeating query-time retrieval-augmented generation. Obsidian and Claude Code also required plain Markdown and a full audit trail to each clipping.

## Decision

Adopt the Karpathy LLM-wiki pattern with two layers:

- `raw/` is canonical and immutable — never written, renamed or deleted by the LLM.
- `wiki/` is LLM-owned and holds five page types: `company`, `technology`, `product`, `theme`, `source`.
- `wiki/sources/` is a 1:1 mirror of `raw/` filenames (the only page type allowed non-ASCII names), providing the audit trail.
- Entity/theme/product bodies are English-only; Chinese is recoverable through `aliases_cn`, the union `aliases:` field, and links to source pages, which are the only place inline CN is kept.
- Wiki pages never embed images; visual references are non-embedding `[[wikilinks]]` into `raw/assets/`.
- Cross-references are always `[[wikilinks]]`, never raw paths. A theme requires >= 5 distinct source pages.
- `CLAUDE.md` at the workspace root is the schema contract.

## Alternatives considered

- Query-time RAG over `raw/` instead of a curated layer — rejected: the wiki must compound knowledge incrementally, not re-derive it per query.
- Two other architecture approaches evaluated in the design session ("Approach 3, hybrid hierarchical with sources mirror" was approved) — the flatter alternatives lost the audit trail / cross-source synthesis split.
- Incremental bootstrap instead of full backfill — rejected in favour of option B, a full backfill of all 437 clippings.

## Consequences

- Every claim in the curated layer must cite a source page; fabricated or unanchored data is banned by invariant.
- Duplicate prevention, renames, merges and splits become explicit LLM workflows with user approval.
- CN searchability depends entirely on alias discipline being maintained across three frontmatter fields.
- Deferred at this date: git versioning, external search engine, output formatting, MCP servers, Italian-language bodies.
