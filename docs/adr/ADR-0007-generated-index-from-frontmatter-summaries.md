# ADR-0007: index.md is generated from frontmatter `summary:` fields and never hand-edited

- Date: 2026-06-11
- Status: accepted

## Context

On 2026-06-11, the hand-maintained catalog was 51 KB and its header counts were 40–60% stale. A resync found 86 uncataloged pages, mistagged stubs, double entries, and 14 duplicate-entity groups. The exercise showed that frontmatter could generate the catalog except for one-line summaries.

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
