# Glassgraph domain glossary

## Assertion

A typed statement that connects a subject, a predicate, and an object. An assertion cites one or more evidence passages.

## Build manifest

A derived record of the source documents, compiler version, configuration, and artifacts in one compiler build.

## Benchmark query

A frozen question that tests whether a retrieval backend returns the adjudicated evidence passages or correctly abstains.

## Canonical build

The complete derived output from a clean compiler run over the current Markdown corpus.

## Determinism tier

The reproducibility class of an artifact or operation.

- **Exact**: The same canonical inputs produce byte-identical output.
- **Environment-pinned**: The same pinned runtime and model environment produce equivalent output.
- **Advisory**: The output can change between runs and cannot enter the canonical build without deterministic validation.

## Document

An editor-owned Markdown file that Glassgraph reads as canonical input.

## Document ID

A deterministic identifier for one document path in a corpus.

## Evidence passage

A contiguous passage in a document that supports an assertion or a retrieval result.

## Evidence ID

A deterministic identifier for one evidence passage within one document and heading path.

## Evidence locator

The document path, heading path, line span, and UTF-8 byte span that locate an evidence passage for a reader.

## Evidence judgment

A human decision that grades an evidence passage as direct, supporting, or irrelevant for one benchmark query.

## Evidence intermediate representation

The typed, derived representation of documents, evidence passages, entities, predicates, and assertions.

## Markdown authority

The rule that editor-owned Markdown is canonical and all Glassgraph artifacts are disposable derived data.

## Negative query

A benchmark query for which the corpus contains no evidence that answers the question.

## Private benchmark

The local benchmark that uses private corpus questions and evidence judgments. Its query-level data cannot enter the public repository.

## Public fixture benchmark

A redistributable synthetic benchmark that tests the same schemas and metrics without private corpus data.

## Retrieval backend

A replaceable system that returns document or passage candidates. A retrieval backend does not create canonical assertions.

## Stable identifier

An identifier that the compiler derives from canonical inputs without stored random state.
