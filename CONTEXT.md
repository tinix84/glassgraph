# Glassgraph domain glossary

## Assertion

A typed statement that connects a subject, a predicate, and an object. An assertion cites one or more evidence passages.

## Assertion candidate

An evidence-linked relation proposal that has not passed the rule for canonical assertions.

## Authored assertion

An assertion that a person writes explicitly in editor-owned Markdown and links to supporting evidence.

## Build manifest

A derived record of the source documents, compiler version, configuration, and artifacts in one compiler build.

## Benchmark query

A frozen question that tests whether a retrieval backend returns the adjudicated evidence passages or correctly abstains.

## Canonical build

The complete derived output from a clean compiler run over the current Markdown corpus.

## Canonical assertion

An authored, exact-derived, adjudicated, or qualified deterministic assertion that satisfies the evidence contract.

## Determinism tier

The reproducibility class of an artifact or operation.

- **Exact**: The same canonical inputs produce byte-identical output.
- **Environment-pinned**: The same pinned runtime and model environment produce equivalent output.
- **Advisory**: The output can change between runs and cannot enter the canonical build without human adjudication recorded in Markdown.

## Document

An editor-owned Markdown file that Glassgraph reads as canonical input.

## Document ID

A deterministic identifier for one document path in a corpus.

## Evidence passage

A contiguous passage in a document that supports an assertion or a retrieval result.

## Evidence ID

A deterministic identifier for one evidence passage within one document and heading path.

## Entity ID

A deterministic identifier for one typed wiki page.

## Evidence locator

The document path, heading path, line span, and UTF-8 byte span that locate an evidence passage for a reader.

## Evidence judgment

A human decision that grades an evidence passage as direct, supporting, or irrelevant for one benchmark query.

## Heading ID

A deterministic identifier for one heading instance, including its position among equal sibling headings.

## Human adjudication

An affirmative human judgment that binds one typed assertion tuple to its supporting evidence passages.

## Exact-derived assertion

An assertion that the compiler derives from a typed Markdown field through a deterministic join without semantic inference.

## Evidence intermediate representation

The typed, derived representation of documents, evidence passages, entities, predicates, and assertions.

## Markdown authority

The rule that editor-owned Markdown is canonical and all Glassgraph artifacts are disposable derived data.

## Negative query

A benchmark query for which the corpus contains no evidence that answers the question.

## Private benchmark

The local holdout evaluation derived from completed private search trials. Its query-level data cannot enter the public repository.

## Research brief

A private statement of the topic, argument, questions, and constraints that make one research session useful to the owner.

## Reference search

An evidence-seeking search of the canonical Markdown corpus that is independent of the Glassgraph retrieval run being evaluated.

## Search trial

One research question, its reference citations, and the retrieval results produced from one locked research brief.

## Retrieval disagreement

A material difference between a reference search and a Glassgraph run, such as a missing citation, noisy hit, unsupported answer, or ranking difference.

## Tuning iteration

One recorded change to retrieval settings followed by a repeat of the development search trials.

## Qualified predicate

A predicate whose deterministic extractor passes its evidence-level precision gate on the frozen gold set.

## Predicate ID

A deterministic identifier for one predicate key in one ontology version.

## Public fixture benchmark

A redistributable synthetic benchmark that tests the same schemas and metrics without private corpus data.

## Retrieval backend

A replaceable system that returns document or passage candidates. A retrieval backend does not create canonical assertions.

## Stable identifier

An identifier that the compiler derives from canonical inputs without stored random state.
