# ADR-0007: index.md is generated from frontmatter `summary:` fields and never hand-edited

- Date: 2026-06-11
- Status: accepted

## Context

Source: `docs/superpowers/specs/2026-06-11-generated-index-design.md` (2026-06-11, Spec 2 of 3; depends on Spec 1). The hand-maintained catalog had grown to 51 KB with single lines up to 6,850 characters and header counts 40-60% stale. A resync exercise found 86 uncatalogued pages, mis-tagged stubs and double-listed entries. Worse, invariant #3 routed duplicate prevention through this least reliable artifact, directly producing 14 duplicate-entity merge groups. Parallel batch subagents all wrote the file concurrently under a merge rule that was unenforceable. The resync proved the catalog is fully derivable from page frontmatter — except the one-line summaries.

## Decision

- Add a `summary:` frontmatter field (required on entity pages, optional on sources) so the only non-derivable content survives regeneration, migrated once from the existing index lines through the validating writer.
- `.tools/wikilib/gen_index.py` walks the wiki, parses frontmatter with the shared parser, and emits index.md deterministically with true counts, alphabetical sections and a "do not hand-edit" banner. Stub classification comes from `tags: [stub]` only, retiring the substring heuristics.
- Remove index.md from every agent write path; the controller regenerates once per wave and subagents never touch it.
- Rewire invariant #3: duplicate checks move from "check index.md" to a new `link.py lookup <name-or-alias>` command that queries the same alias table the linker resolves against.
- The generator exits non-zero on any unparseable page (integrity gate side effect) and writes atomically to survive editor auto-sync.

## Alternatives considered

- Keeping summaries in index.md — rejected: they would not survive regeneration; frontmatter is the only durable home.
- Deriving stub status from name/content heuristics as the maintenance scripts did — rejected in favour of a single source of truth (`tags: [stub]`); those scripts are retired.
- Refreshing overview.md the same way — out of scope: it stays curated prose and gets only a staleness lint (INFO when `updated:` is older than 30 days).

## Consequences

- Drift becomes structurally impossible; counts always match the filesystem.
- A page with a name collision across types now errors the generator and must be merged or renamed first.
- Migration surfaced two manual-triage lists: dead index lines with no matching page, and pages with no summary.
- `index_counts.py` is superseded by the generator's header counts and retired.
