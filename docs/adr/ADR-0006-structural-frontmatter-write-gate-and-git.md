# ADR-0006: Machine-parsed frontmatter must be machine-written — validating writer, PreToolUse hook, and git

- Date: 2026-06-11
- Status: accepted

## Context

A 2026-06-11 architecture review linked repeated incidents to unvalidated machine-parsed fields. The review found 242 invalid product pages, 33 critical parse errors, 14 duplicate alias keys, and 20 duplicate update keys. It also found 36 byte-order-marked source pages whose `touches:` entries disappeared from the graph. Git did not provide a timely diff or rollback path.

## Decision

- `git init` at the repo root, with the first commit as an as-is baseline; one commit per ingest wave / repair / merge / rename, message mirroring the log entry; weekly `git gc` and a bare backup clone outside the sync folder. This reverses the original "no git, OneDrive versions everything" decision.
- One shared BOM/CRLF-safe frontmatter parser used by all six parse sites, which also surfaces duplicate top-level keys instead of silently keeping the last.
- A validating writer (`.tools/wikilib/write_page.py`) becomes the sanctioned page-write path: metadata in as JSON, the tool serializes the YAML itself, computes the `aliases:` union, and refuses to write on any schema violation — the LLM never emits frontmatter text.
- A PreToolUse hook on `Write|Edit` targeting wiki pages as an enforcement backstop, denying invalid frontmatter with the specific error so the agent can self-correct. Body-only edits still pass through; the index and log files are exempt.
- Fix the two verified linker bugs (CJK word-boundary, cache staleness) with regression tests; add CRITICAL lint checks for BOM and duplicate keys; repair the affected pages. Exit criterion: 0 CRITICAL across the wiki.

## Alternatives considered

- Keeping OneDrive as the only versioning mechanism — rejected: no diff review, no rollback, breakage discovered weeks late.
- Lint-only enforcement (detect after the fact) — rejected: lint had already failed to catch the sibling failure classes; the gate must be structural.
- A second validation implementation in the hook — rejected: it validates with the exact parser the linker uses, so there is no second opinion to disagree.

## Consequences

- Malformed frontmatter can no longer land in the wiki; the generated index (ADR-0007) can therefore abort loudly rather than silently drop pages.
- Hook false-positives are the accepted risk, mitigated by exempting non-frontmatter files.
- The CJK boundary fix raises match counts; a before/after `backfill --history` run quantifies it so it lands as measured change, not silent drift.
- Git inside the sync folder is a known low-probability corruption vector, mitigated by the external bare backup.
- Zotero extractor fixes were explicitly held out of scope and must be done before any academic backfill.
