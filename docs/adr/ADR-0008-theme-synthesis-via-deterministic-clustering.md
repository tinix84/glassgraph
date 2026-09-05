# ADR-0008: Theme candidates are detected by deterministic co-occurrence clustering, owned by the controller, created only on user approval

- Date: 2026-06-11
- Status: accepted

## Context

Source: `docs/superpowers/specs/2026-06-11-theme-synthesis-process-design.md` (2026-06-11, Spec 3 of 3). Themes are the declared highest-value layer, but the count sat at 14 from bootstrap while sources grew from 535 to 838 — one theme per 60 sources against one entity page per 1.1 sources. All three designed creation paths were structurally dead: slice-local batch subagents cannot see the global >= 5-source threshold and their evidence notes evaporated in transcripts; the `cluster` command had zero runs in the entire log; `query` auto-file had zero entries. The layer was becoming vestigial.

## Decision

- Add `link.py cluster`: deterministic entity-entity co-occurrence over source `touches:` lists, growing connected groups of entities sharing >= 5 distinct sources, then dropping groups already covered by an existing theme (covered = >= 60% of the group's evidence sources appear in some theme's `sources:`). Pure measurement — no LLM calls, no wiki writes.
- Run it automatically on the same cadence as lint (every 25 ingests) and on demand.
- The **controller**, never slice subagents, reads the report, drafts a one-line thesis for the top 3 uncovered candidates, and appends them to a proposals file that remembers rejected candidates so they are never re-surfaced.
- Subagent end-of-slice reports gain a structured `theme-evidence:` line that the controller aggregates into the same file.
- Theme creation stays user-approved; approval runs the existing `theme new` workflow.
- Stale themes (lint check 7) are surfaced in the same report so missing and aging themes appear side by side.

## Alternatives considered

- Auto-creating theme pages from clusters — rejected: co-occurrence is a hint, not a thesis; the LLM drafting step and the user gate stay between measurement and page creation by design.
- Changing the theme page schema or the >= 5-source threshold — explicitly out of scope.
- Leaving detection to ingest-time subagent judgement — rejected: the threshold needs a global view slices lack.

## Consequences

- The 60% coverage filter is a calibration constant, not architecture; the first real run is explicitly a calibration run.
- Proposal fatigue is capped at three per run.
- Later calibration on this corpus found union-find surfaces one dominant themed region plus a short tail of coherent clusters — the tail is the signal, and controller judgement on it is the lever rather than the threshold. A max-clique variant was trialed and rejected for fragmenting the dominant region into 100+ overlapping cliques.
