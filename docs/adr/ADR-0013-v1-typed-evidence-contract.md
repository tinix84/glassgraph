# ADR-0013: Define the Glassgraph v1 typed-evidence contract

- Date: 2026-11-09
- Status: accepted

## Context

ADR-0011 positions Glassgraph as a deterministic typed-evidence compiler for editor-owned Markdown. The existing graph records entity names and relation provenance, but it does not define a stable passage identity. It also does not define how a reader verifies a derived assertion against the source text.

The contract must support clean and incremental builds. It must detect stale coordinates after an edit. It must also remove artifacts after a document changes or disappears.

## Decision

Markdown is the only authority. The evidence intermediate representation, indexes, manifests, assertions, and graph exports are disposable derived data.

Glassgraph v1 uses the following canonical forms:

1. The compiler makes a canonical document path from the vault-relative path. It uses `/` separators, removes `.` segments, applies Unicode NFC, and preserves case.
2. The compiler makes `document_id` with SHA-256 over the domain tag `glassgraph:document:v1` and the canonical document path.
3. The compiler normalizes parsed text to Unicode NFC and LF line endings. It preserves all other whitespace.
4. An evidence passage is a contiguous range in one normalized document. Its heading path contains the ordered ATX heading levels and normalized heading text.
5. The compiler makes `evidence_id` with SHA-256 over the domain tag `glassgraph:evidence:v1`, `document_id`, the heading path, the normalized passage hash, and the zero-based occurrence among identical passages in that heading.
6. An evidence locator stores the canonical path, heading path, one-based inclusive line span, and an original-file UTF-8 byte span. The byte end is exclusive.
7. Each evidence record stores the normalized passage hash and the exact source-document byte hash. These hashes make stale locators detectable.
8. An assertion stores its subject ID, predicate ID, object ID or scalar value, one or more evidence IDs, extraction method, compiler version, and determinism tier.
9. The compiler makes `assertion_id` with SHA-256 over the domain tag `glassgraph:assertion:v1`, the typed subject-predicate-object tuple, and the sorted evidence IDs. Compiler versions and extraction methods do not change semantic identity.
10. A canonical assertion must cite at least one valid evidence ID. A retrieval hit or advisory model output is not a canonical assertion.
11. Exact operations use determinism tier A. Pinned embedding or reranking operations use tier B. Language-model output uses tier C and stays advisory until deterministic validation accepts it.
12. The build manifest records each document hash and every artifact ID emitted for that document. An incremental rebuild removes the prior artifact set before it compiles a changed document. It removes the prior artifact set when a document disappears.
13. `verify-build` compares canonical serialized output from an incremental build with a clean rebuild. Any difference is a verification failure.

Canonical serialization uses UTF-8, LF line endings, sorted object keys, and deterministic list ordering. The compiler must reject invalid UTF-8 instead of replacing bytes.

## Alternatives considered

- Random UUIDs in Markdown were rejected. They require source mutation and stored state.
- A hidden database identity was rejected. It would become a second source of truth.
- File content alone was rejected for `document_id`. Two files can contain identical bytes.
- A byte or line offset was rejected as passage identity. An unrelated insertion would change every later identifier.
- Compiler version was rejected as part of `assertion_id`. A compiler upgrade must not change an otherwise identical assertion.
- Incremental deletion by query was rejected. A per-document manifest gives an exact removal set.

## Consequences

- A document rename changes its document ID and all evidence IDs below it.
- An evidence-text edit changes its evidence ID. An edit elsewhere in the same heading does not change the ID unless it changes the identical-passage occurrence.
- Coordinates can change while an evidence ID stays stable. The document and passage hashes detect stale locators.
- Every canonical graph edge and retrieval result can resolve to editor-owned Markdown.
- A clean rebuild can recover all derived state without a database backup.
