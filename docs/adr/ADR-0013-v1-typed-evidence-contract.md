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
2. The compiler makes `document_id` from the domain tag `glassgraph:document:v1` and a payload that contains the canonical document path.
3. The compiler normalizes the complete file, including frontmatter, to Unicode NFC and LF line endings. It preserves all other whitespace.
4. Each document has a root heading instance for frontmatter, preamble text, and headingless content.
5. The root heading payload uses level 0, a null parent, an empty title, and `same_name_ordinal` 0.
6. The root owns unheaded content but is not the parent of top-level ATX headings. Their parent ID is null.
7. The compiler makes each other `heading_id` from its document ID, parent heading ID, level, normalized title, and equal-sibling ordinal.
8. The equal-sibling ordinal counts earlier sibling headings with the same level and normalized title under the same parent.
9. An evidence passage is a contiguous range in one normalized document and one heading instance.
10. The compiler makes `evidence_id` from its document ID, heading ID, normalized passage hash, and passage ordinal.
11. The passage ordinal counts earlier identical normalized passages within that heading instance.
12. An evidence locator stores the canonical path, heading path, one-based inclusive line span, and original-file UTF-8 byte span. The byte end is exclusive.
13. Each evidence record stores the normalized passage hash and the exact source-document byte hash. These hashes make stale locators detectable.
14. The compiler makes `entity_id` from the domain tag `glassgraph:entity:v1`, document ID, page type, and canonical entity name.
15. The compiler makes `predicate_id` from the domain tag `glassgraph:predicate:v1`, ontology version, and predicate key.
16. An assertion stores its subject ID, predicate ID, typed object, evidence IDs, extraction method, compiler version, and determinism tier.
17. An entity object uses `{kind: entity, id: <entity_id>}`. A scalar object records `kind`, `type`, and a canonical string value.
18. A string uses NFC without other changes. An integer has an optional minus, no plus, and no leading zeros. Signed zero becomes `0`.
19. A decimal has an optional minus and no plus or exponent. Its integer part has one or more digits and no redundant leading zeros.
20. A decimal strips trailing fractional zeros and a trailing decimal point. Values below one use `0` before the point. Signed zero becomes `0`.
21. A boolean is `true` or `false`. A date is a valid `YYYY-MM-DD` calendar date.
22. The compiler makes `assertion_id` from the domain tag `glassgraph:assertion:v1`, typed tuple, and sorted evidence IDs.
23. Compiler versions and extraction methods do not change assertion identity.
24. A canonical assertion must cite at least one valid evidence ID. A retrieval hit or advisory model output is not a canonical assertion.
25. Exact operations use tier A. Pinned embedding or reranking operations use tier B. Language-model output uses tier C.
26. Structural validation can accept tier-C output as a review candidate. Only human adjudication recorded in Markdown can promote it.
27. The build manifest records each document hash, emitted artifact IDs, referenced IDs, and every resolved or unresolved lookup key.
28. For each resolved key, the manifest records the selected owner ID and every colliding owner ID.
29. An incremental rebuild removes the prior artifact set before it compiles a changed document. It removes that set when a document disappears.
30. A change or deletion invalidates every dependent assertion and join. The compiler recompiles the dependent source or recomputes the global join.
31. After a document or alias change, the compiler rebuilds the lookup ownership map.
32. The compiler invalidates dependents for each key whose selected owner or collision set changed.
33. `verify-build` compares canonical serialized output from an incremental build with a clean rebuild. Any difference is a verification failure.

Every ID has the form `sha256:<lowercase hex>`. The hash preimage is the UTF-8 domain tag, one NUL byte, and a canonical JSON payload. After NFC normalization, payload serialization follows RFC 8785 JSON Canonicalization Scheme. Non-ASCII characters use their UTF-8 bytes and never use optional `\u` escapes. Payloads do not contain floating-point numbers. Lists keep their stated semantic order unless this ADR requires sorting. The compiler must reject invalid UTF-8 instead of replacing bytes.

The canonical payload keys are:

```json
{"document":{"path":"<canonical-path>"}}
{"heading":{"document_id":"<document-id>","level":0,"parent_id":null,"same_name_ordinal":0,"title":""}}
{"heading":{"document_id":"<document-id>","level":2,"parent_id":null,"same_name_ordinal":0,"title":"<normalized-title>"}}
{"evidence":{"document_id":"<document-id>","heading_id":"<heading-id>","passage_hash":"<sha256>","passage_ordinal":0}}
{"entity":{"canonical_name":"<name>","document_id":"<document-id>","page_type":"<type>"}}
{"predicate":{"ontology_version":"v1","predicate_key":"<key>"}}
{"assertion":{"evidence_ids":["<sorted-evidence-id>"],"object":{"id":"<entity-id>","kind":"entity"},"predicate_id":"<predicate-id>","subject_id":"<entity-id>"}}
```

The outer labels in this example name each payload. They are not part of the hashed JSON. The hashed document payload is `{"path":"<canonical-path>"}`, for example.

### Golden duplicate-heading vector

This vector uses `wiki/example.md`. The file contains two sibling `## Results` headings. Each heading contains `Efficiency is 98%.` followed by LF.

The first and second heading payloads use `same_name_ordinal` values 0 and 1. Both evidence payloads use `passage_ordinal` 0.

| Value | Expected identifier |
|---|---|
| `document_id` | `sha256:cc13d6bd4ca7fbd5f442e43d56db96ea81a020c4c99000ba6079e0692527514a` |
| First `Results` heading | `sha256:3d768983e310325af1ccd94415b2b086c54d668520c1d8c0d834c712d70435c3` |
| Second `Results` heading | `sha256:01176993cc71b8ae7cabc4065ace70fa1db8478973460144a4894e3dc16fd95b` |
| Normalized passage hash | `sha256:a3bc8d367d1b3e130e32585a94d6866abc5c2703c5c9a68a8f6873f6116943bf` |
| First evidence ID | `sha256:4b7cfa3b09c93f27bbb18d7fdf420a7d052f1c61be08fc51f798ce72d348d34c` |
| Second evidence ID | `sha256:5192b389efc2c82bcad2e8424cbb2332a165eb8f9fbd0916409bae10ce56f407` |

The public M1 fixture must implement this vector and fail if the two evidence IDs become equal.

### Golden root, Unicode, and scalar vectors

The document-root heading ID is `sha256:d36672cf3e74830675315cc12fb5d766a21bcf62ce684d6389ef575b9082d5ac`.

The heading title `Résultats` produces `sha256:11eb73914fe301626e12029a304457803a1a4b284c09b052fbcdf23a15665b56`. The serializer hashes the literal UTF-8 bytes for `é`, not a `\u00e9` escape.

The frontmatter line `vendor: "[[Tesla]]"` followed by LF has passage hash `sha256:d65882cdd00d8b32fb6fb11986abb3ce87fd2ec55120732ebff113ebc9e7e2bd`. Under the root heading, its evidence ID is `sha256:adf446220c2e9d5e8457c465958106fc45bd6fb537bbfde287f3f263a9938e63`.

The product entity `Example` has ID `sha256:005978a8226640847ab6bc98006031511f54b2970455fba0531147565bec1f33`. Predicate `achieves_spec` has ID `sha256:c4fe157c9cd173e63c5e0f92ca20e8094a133e170cd385fd86263a3bac6bd9b6`.

The decimal inputs `0.980`, `+0.98`, `00.9800`, and `.98` normalize to scalar value `0.98`. Integer inputs `+001`, `01`, and `1` normalize to `1`. With evidence ID `sha256:4b7cfa3b09c93f27bbb18d7fdf420a7d052f1c61be08fc51f798ce72d348d34c`, the decimal assertion ID is `sha256:4661ffcdae95024490714d5f3b9d18435d0689166bf767e59ea5061b89c6e626`.

The public M1 fixture must implement all golden vectors in this ADR.

## Alternatives considered

- Random UUIDs in Markdown were rejected. They require source mutation and stored state.
- A hidden database identity was rejected. It would become a second source of truth.
- File content alone was rejected for `document_id`. Two files can contain identical bytes.
- A byte or line offset was rejected as passage identity. An unrelated insertion would change every later identifier.
- Compiler version was rejected as part of `assertion_id`. A compiler upgrade must not change an otherwise identical assertion.
- Incremental deletion by query was rejected. A per-document manifest gives an exact removal set.
- Path-only invalidation was rejected. Cross-document joins require reverse-dependency invalidation.

## Consequences

- A document rename changes its document ID and all evidence IDs below it.
- An evidence-text edit changes its evidence ID. An edit elsewhere in the same heading does not change the ID unless it changes the passage ordinal.
- Coordinates can change while an evidence ID stays stable. The document and passage hashes detect stale locators.
- Every canonical graph edge and retrieval result can resolve to editor-owned Markdown.
- A clean rebuild can recover all derived state without a database backup.
