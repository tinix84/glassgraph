# ADR-0015: Limit v1 canonical relations to evidence-qualified assertions

- Date: 2026-11-09
- Status: accepted
- Supersedes: ADR-0009 relation storage and automatic-promotion rules

## Context

ADR-0009 defines a ten-predicate ontology and a triple-level precision gate. The local relation experiment stores only subject, predicate, object, and extraction method. It does not retain the source passage or the evidence ID that ADR-0013 requires.

The experiment also accepts output from its only available lexicon voter. It does not apply the documented Wilson gate during extraction. `supplies` passed an earlier triple-level gate, but the gold data did not grade exact evidence passages. `used_in` produced no edges, and five other extracted predicates have no recorded passing result.

## Decision

Glassgraph v1 keeps the ten-predicate ontology from ADR-0009 and ADR-0010. Predicate recognition does not grant canonical status to an assertion.

V1 has four paths to a canonical assertion:

1. An authored assertion is valid when its typed endpoints exist and it cites at least one valid evidence ID.
2. An exact-derived assertion is valid when a deterministic join reads a typed Markdown field and cites that field value as evidence.
3. A human-adjudicated assertion is valid only after an affirmative verdict records the reviewer, date, exact typed tuple, and supporting evidence IDs.
4. A deterministic extractor can promote an assertion only after its qualification key passes the evidence-level gate.

The qualification key contains the predicate ID, extractor name and version, configuration hash, and gold-set version. Any change creates a new qualification key.

The evidence-level gate requires at least 20 predicted assertions in a frozen gold set. The 95% Wilson lower bound for precision must be at least 0.80. A prediction is correct only when both its typed tuple and required evidence groups match the gold judgment.

The v1 exact-derived predicates are:

- `vendor_of`, from a product's typed `vendor` field.
- `mentions`, from a source's typed `touches` entries.
- `evidence_for`, from a theme's typed `sources` entries.

The previous `supplies` result is evidence that the predicate is worth requalification. It is not an evidence-level pass. Until requalification, `supplies` output remains an assertion candidate.

The following extracted predicates also remain candidates: `used_in`, `implements`, `achieves_spec`, `succeeds`, `competes_with`, and `partners_with`. Model-generated relations always remain advisory candidates until a person records an affirmative adjudication in Markdown.

A rejected adjudication stays in the review record and never enters the canonical graph.

Legacy relation records that contain only `s`, `p`, `o`, and `by` are migration candidates. The compiler must not emit them as canonical assertions until it resolves their typed endpoints and evidence IDs.

Canonical assertions remain distinct when they cite different evidence sets. A graph projection can collapse repeated subject-predicate-object tuples, but it must retain every supporting assertion ID.

Symmetric predicates use one canonical endpoint order. A graph can show a reciprocal navigation edge, but that edge is a derived view, not a second assertion.

Contradictory assertions can coexist when each has valid evidence. The compiler must not choose one claim or delete the other.

Communities, cards, co-occurrence clusters, similarity edges, and generated reports are derived analysis. They are not canonical assertions. Graph query commands and active learning remain later work in issues #9 through #11.

## Alternatives considered

- Treating the ten-predicate ontology as shipped was rejected. Six extracted predicates lack an evidence-level pass.
- Grandfathering `supplies` was rejected. Its earlier gold set grades triples, not supporting passages.
- Storing generated relations back into Markdown was rejected. It conflicts with editor ownership and disposable compiler output.
- Using voter agreement as evidence was rejected. Agreement can repeat the same unsupported error.
- Collapsing equal triples in the canonical representation was rejected. Separate passages can support or contradict the same tuple.
- Promoting communities or similarity edges was rejected. Statistical association is not a typed factual assertion.

## Consequences

- V1 ships useful exact-derived relations without claiming that experimental extractors passed a stronger test than they did.
- The compiler needs one assertion-candidate representation and one qualification step.
- Existing relation experiments can supply candidates, but M2 must add evidence locators before promotion.
- The predicate ontology can grow independently from the set of qualified automatic extractors.
- Graph views stay useful while the evidence intermediate representation remains the audit source.
