# ADR-0017: Use GrooveSeek as the v1 default retrieval backend

- Date: 2026-11-11
- Status: accepted
- Author: Riccardo Tinivella and Codex
- Version: 1.0
- Audience: Glassgraph maintainers selecting and operating the v1 retrieval backend

## Decision

We use GrooveSeek as the default Glassgraph v1 retrieval backend.

## Context

Glassgraph needs local and offline retrieval for a 1,745-document Markdown corpus. The default must support short tuning cycles and cited research review. The comparison used the public fixture and the ADR-0016 private search lab. Private query text and results stayed local.

The v1 readiness gates are a full private build within 30 minutes and p95 query latency below 2 seconds. A challenger must also match or exceed GrooveSeek on locked private cited-document coverage.

## Options

| Option | Pros | Cons | Cost / effort |
|---|---|---|---|
| GrooveSeek | Full private build completed in 522.8 seconds [M]. Private development and holdout p95 latency was 869.5 ms and 575.7 ms [M]. Peak query memory was 218.6 MB [M]. | Locked holdout cited-document coverage was 0.50 [M]. Low-confidence results need an explicit review policy. | The local index and pinned embedding model are required. |
| QMD 2.8.3 | The public fixture had 0.70 Recall@10 and 0.765 evidence-span accuracy [M]. The adapter preserves hybrid score traces. | The private build produced 220 vectors in 30 minutes, with 1,562 pending [M]. Public p50/p95 query latency was 6.52/10.22 seconds [M]. | The observed CPU rate projects to about four hours for a full private build [E]. |
| No default | Avoids selecting an imperfect backend. | Every search needs manual backend selection. Reproducible settings and user expectations remain unclear. | The owner must compare backends for each research session. |

## Decision and rationale

GrooveSeek passes both v1 speed gates. QMD fails the private build-time gate and the public query-latency gate. QMD did not produce a ready private hybrid index, so no private QMD quality claim is made.

The locked GrooveSeek holdout coverage is not a quality ceiling. It is the baseline for later challengers. A future QMD Vulkan or integrated-GPU experiment can challenge this decision only after it produces a complete attested index.

## Consequences

- Glassgraph uses GrooveSeek for default local retrieval.
- Research sessions preserve low-confidence candidates only through an explicit policy and label them. The adapter default remains abstention.
- QMD remains an optional adapter and a future performance experiment.
- A QMD challenger must pass the same frozen-corpus, settings-lock, and holdout workflow.
- GPU acceleration cannot change the default without a new measured decision record.

## Status

Accepted. Riccardo Tinivella authorized continuation on 2026-11-11 after review of the measured results.
