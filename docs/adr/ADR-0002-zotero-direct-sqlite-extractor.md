# ADR-0002: Ingest Zotero via a first-party read-only SQLite extractor

- Date: 2026-05-16
- Status: accepted

## Context

Source: `docs/superpowers/specs/2026-05-16-zotero-integration-design.md` (2026-05-16). A 500+ paper Zotero library (1,720 items, 59 annotations at design time) had to feed the wiki as academic source pages, with the user's highlights surfacing as cited `Evidence` and with a re-ingest trigger that fires when new annotations appear. Existing Obsidian/Zotero bridge plugins were broken on the installed Zotero major version, and the library contains orphan attachments with no bibliographic parent.

## Decision

Write a single-file, stdlib-only Python extractor (`.tools/zotero/extract.py`) that reads `zotero.sqlite` in read-only immutable URI mode and emits immutable Markdown into `raw/zotero/`. Add a `source_kind: academic` schema extension (Zotero key, `zotero_modified`, DOI/authors/journal/year, `metadata_complete`) and an `Evidence` body section that maps Zotero's 8 highlight colours to 7 evidence categories; magenta is treated as a structural marker and excluded. `zotero_modified` is the canonical re-ingest trigger; incremental state lives in `.tools/zotero/state.json`.

## Alternatives considered

- ZotLit Obsidian plugin — its Zotero-side companion supports only older Zotero majors; import failures reported; orphan attachments invisible; the version-bump PR is unmerged.
- Zotero Integration (mgmeyers) — stale since Aug 2024, known breakage for recently added references.
- Zotero native Markdown export — manual, per-note, no metadata, no batch; unusable at 500+ papers.
- BetterBibTeX JSON export — possible but redundant; adds a plugin dependency while SQLite already holds the same data and more.

## Consequences

- Plugin-independent and resilient across Zotero versions, since the SQLite schema is the stable integration point.
- Two new invariants: never write to the Zotero data directory, never hand-write `raw/zotero/`.
- Orphan attachments are ingested with `metadata_complete: false` and surfaced by lint for user enrichment rather than skipped.
- `ingest new` deliberately keeps scanning only `raw/*.md` so a 500-paper batch cannot start accidentally.
- Image annotations, PDF full-text and citekey source resolution remained open at the time of writing.
