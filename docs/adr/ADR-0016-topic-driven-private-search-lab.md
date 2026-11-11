# ADR-0016: Use a topic-driven private search lab for retrieval selection

- Date: 2026-11-11
- Status: accepted
- Supersedes: ADR-0014

## Context

ADR-0014 required the owner to author and adjudicate 60 private benchmark records before retrieval work could continue. That workflow starts with benchmark bookkeeping instead of the owner's research need. It also prevents the research agent from doing the corpus search, comparison, and tuning work that Glassgraph exists to improve.

## Decision

Glassgraph uses a topic-driven private search lab for retrieval tuning and backend selection.

The owner starts with a research brief: a topic or argument, the questions that matter, and any scope constraints. Sol performs a reference search over the canonical 2brain Markdown corpus and records exact citation hypotheses. Glassgraph runs the same search trials through its backend-neutral query contract. The lab compares the two result sets and surfaces retrieval disagreements: missing citations, noisy hits, unsupported answers, ranking differences, latency, and context cost.

Tuning can use only development research briefs. Each tuning iteration records the settings change, rationale, results, and whether the change improved the brief. Settings are then locked before untouched holdout briefs run. Backend selection uses the public synthetic fixture, several private research topics, the locked holdout results, and explicit limitations.

Sol can generate search questions and propose evidence grades. Those outputs are advisory. Exact citations must resolve against the frozen corpus before they can score as evidence. A negative no-answer claim is not gold unless the owner accepts it or an exhaustive recorded search supports it. The owner reviews the research brief, representative conclusions, and material disagreements instead of manually authoring every query and judgment.

Private query text, citations, paths, results, and tuning history remain local and offline. Public issues and reports contain aggregate measurements and non-sensitive decisions only.

## Alternatives considered

- Keeping the 60-record owner-authored gate was rejected because it blocks the real research workflow and creates high manual effort before search can improve.
- Treating Sol's own grades as independent gold was rejected because one model can repeat its own errors. Exact citation checks and disagreement review remain required.
- Tuning from unrecorded ad hoc searches was rejected because it hides overfitting and makes backend comparisons irreproducible.

## Consequences

- M1 can iterate on real 2brain topics without a 60-record manual authoring gate.
- The evaluation measures research utility and citation quality, not only a fixed statistical benchmark.
- The public fixture remains the reproducible schema and regression test.
- Private holdout topics and settings locks remain necessary to detect overfitting.
