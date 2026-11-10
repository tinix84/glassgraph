# Glassgraph v1 public benchmark fixture

This synthetic fixture contains no private 2brain data. It tests retrieval adapters, evidence-group scoring, abstention, and the identifier vectors in ADR-0013.

- `corpus/` contains invented technical Markdown documents for backend measurements.
- `queries.json` contains 15 positive queries and five negative queries. Its manifest freezes the corpus, queries, judgments, split, and adjudication date.
- `qmd-fixture.json` contains the positive document-level subset for `qmd bench`.
- `identity-cases/` contains duplicate-heading, Unicode, rename, and deletion cases.
- `golden-identifiers.json` contains the expected identifiers from ADR-0013.

Each positive record cites its required ADR-0013 evidence IDs and at least one explicit `irrelevant` judgment. Exact text must match one contiguous passage in the named corpus document. The content-addressed benchmark version changes whenever a judgment changes.
