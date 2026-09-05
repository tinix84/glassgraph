# ADR-0009: Typed semantic relations extracted from key-extraction bullets, gated per predicate on a Wilson lower bound

- Date: 2026-06-30
- Status: accepted

## Context

Source: `docs/superpowers/specs/2026-06-30-semantic-relation-graph-design.md` (2026-06-30, revised 2026-07-01 after a full design grill). The graph was flat and untyped: `touches:` records only "source X mentions entity Y", which yields a co-occurrence web rather than answers to relational questions, and gives content generation no synthesized understanding. Corpus at design time: 917 source pages, 817 entity pages. The founding constraint was that ingest token cost must not rise.

## Decision

Add Stage 3 to the entity linker:

- Extract from the **EN curated source-page bodies**, specifically the structured `## Key extractions` bullets — not raw CN clippings and not free prose. The bullet's entity gives the subject for free, so the task reduces to predicate classification plus object resolution.
- Lock a 10-predicate ontology v1: three *derived* predicates (`vendor_of`, `mentions`, `evidence_for`) joined deterministically from existing frontmatter at 100% precision and outside the metric gate, and seven *extracted* predicates that must pass the gate. Symmetric predicates are stored once with canonical ordering. Ternary facts are decomposed into binaries and reconstructed by path queries.
- Use a 3-voter deterministic ensemble in distinct modalities (Aho-Corasick predicate lexicon, dependency path, zero-shot classifier). `>= 2/3` agreement auto-accepts inside the ingest fleet at zero LLM tokens; only the disagreement tail is parked for a separate, batched LLM verifier. The LLM is a tie-breaker, never the extractor.
- Store relations in source frontmatter (with `by:` provenance and a whole-body `relations_src_md5` for skip/refresh and a drift lint); confidence stays ephemeral in the cache because it is model-version-bound. Markdown remains the single source of truth; graph exports and cards are derived and regenerable.
- **Ship gate: Wilson lower bound >= 0.80 on per-predicate precision**, measured against a frozen human-adjudicated gold set of ~20-40 held-out pages, sampled to reach ~20 instances per predicate. Predicates that cannot reach the instance minimum ship `provisional` at a conservative threshold rather than faking a pass. Precision is prioritized over recall throughout.
- Phase D tunes deterministic knobs (lexicon, thresholds, label phrasing) from an adjudication pool with a hard split from the frozen gold. No model weights are ever updated.

## Alternatives considered

- Neo4j / ChromaDB — rejected at this scale: a server graph DB or ANN store becomes a second source of truth that drifts from the Markdown; NetworkX and brute-force cosine are fast enough. Tripwires recorded (>~10^4 vectors, always-on multi-client service).
- Reusing an existing generic code-symbol/agent-memory graph implementation — rejected: domain-tuned linker is strictly better here, and its lossy text compression cannot synthesize and must never touch canonical claims.
- Open information extraction over raw prose — rejected as intractable; the bullet reframing is what makes the task gold-labelable.
- LLM-per-source extraction — rejected: violates the token-cost constraint.
- Auto-extracting `contradicts` — rejected: it stays the human-curated prose mechanism.
- Weight-level RL / fine-tuning — rejected: wrong scale, no training infra.
- Precision-weighted voting in v1 — deferred to Phase D.

## Consequences

- Obsidian navigation continues to ride on `touches:`; the nested relations block is preserved-but-ignored by Obsidian and must not be edited via its Properties UI. Typed-edge views come from GraphML exports and a CLI-JSON query interface.
- Voter availability is a real risk on the current Python version, so implementation task #0 is a feasibility spike; the lexicon voter plus LLM verifier is the guaranteed shippable floor.
- Measured outcome of the first gold loop: `supplies` passed (Wilson lower bound 0.851, ~50 verified relations across 27 sources) while `uses` was dropped at 0% precision for conflating use with development.
- Phases B (communities and cards), C (query interface) and D (active learning) are sequenced behind Phase A's gate.
