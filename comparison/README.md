# Graphify vs Deterministic Entity Linker — Comparison Framework

One-off eval module. Compares graphify's output against our entity linker's `touches:` graph on the same `/raw/` corpus.

## How to run

1. Run graphify on `/raw/`:
   ```
   /graphify   # invoke the graphify skill from inside Claude Code
   ```
   Output lands in `.tools/graphify-out/`.

2. Run the comparison:
   ```powershell
   conda run -n 2brain_env python .tools/comparison/compare.py \
     --graphify-dir .tools/graphify-out \
     --our-touches wiki/sources \
     --output .tools/comparison/graphify-comparison-report.md
   ```

3. Open `graphify-comparison-report.md`.

## Files

- `load_graphify.py` — parse graphify's `graph.json` into a networkx DiGraph
- `load_ours.py` — parse `wiki/sources/*.md` touches: into a networkx DiGraph
- `metrics.py` — precision/recall, Jaccard, graph-structural metrics, name normalization
- `compare.py` — orchestrator: load both, compute, render the markdown report

## Design

See `docs/superpowers/specs/2026-05-22-graphify-comparison-framework-design.md`.
