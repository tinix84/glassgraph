# ADR-0019: Validate advisory output through private evidence packets

- Date: 2026-11-12
- Author: Codex
- Version: 1.0
- Audience: Glassgraph maintainers

## Decision

We prototype semantic assist through bounded evidence packets and strict replay of supplied advisory output.

## Context

Issue #22 needs a contract before local model execution can be evaluated.
ADR-0012 requires an optional, private assist lane and a complete model-free path.
ADR-0013 makes Markdown authoritative and requires current evidence identities and locators.
Structural validation alone cannot establish the truth or relevance of generated prose.

## Options

| Option | Pros | Cons | Cost / effort |
|---|---|---|---|
| Strict output replay | Tests evidence integrity and fallback without an inference dependency | Does not measure model quality or speed | Small contract prototype |
| Local model execution first | Gives immediate model samples | Couples runtime setup and evaluation to contract design | Pinned runtime and model deployment |
| Free-form cited synthesis | Flexible drafts | Valid citation IDs cannot prove claim support | Requires a separate grounding gate |

## Decision and rationale

Build packets from exact, current evidence records through the existing ADR-0013 implementation.
Include source hashes, locators, and passages. Bind each packet to its query with a checksum.
Preserve passage order and deduplicate repeated evidence IDs.
Limit packets to 20 records and 32,768 UTF-8 bytes. Reject oversized inputs without truncation.

Accept only versioned JSON bound to the packet checksum. Limit output to 8,192 UTF-8 bytes.
Reject duplicate or unknown fields and unsupported tasks.
Allow query suggestions, selection among supplied evidence IDs, and contiguous exact quotes.
Keep every accepted result advisory and require review. Never execute a rewrite or modify canonical data.
Exact quotation proves text fidelity; it does not prove relevance, preserve every qualification, or establish semantic entailment.

Keep free-form synthesis disabled. Runtime execution and quality admission remain under issue #6 and ADR-0012.
Replay has no transport, model loader, persistence, or automatic promotion.
Label supplied output as runtime-unattested and record its byte hash.
Do not describe synthetic replay as local-model inference or a benchmark.

## Consequences

The deterministic path validates and returns the complete packet without consulting output.
Missing or invalid output returns the same packet with a bounded fallback reason.
A stale or invalid packet raises an error; stale evidence must not appear as a valid deterministic fallback.
Private input and rejected output are not logged or written by this module.
Local runtime manifests, semantic quality, latency, memory, and token savings require separate measured evaluation.
The byte budgets are transport limits, not tokenizer counts or measured context savings.

## Status

Proposed for the issue #22 integration on 2026-11-12.
