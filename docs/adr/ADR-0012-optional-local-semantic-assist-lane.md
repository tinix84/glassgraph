# ADR-0012: Optional private local semantic-assist lane behind a model-free deterministic core

- Date: 2026-08-29
- Status: accepted

## Context

A local-model review completed on 2026-08-29. Local inference keeps evidence packets on the machine, removes per-token cloud charges, and works offline. The model must not become the source of truth. The target is a 16 GB Windows computer with an editor and normal background services.

## Decision

Add an optional local semantic-assist lane while keeping the compiler, canonical graph, first-pass retrieval, citations and deterministic mode entirely model-free.

- Use Qwen3-4B GGUF Q4_K_M on a pinned llama.cpp build as the reproducibility baseline.
- Run the baseline CPU-first with an 8,192-token context.
- Restrict the Qwen3-1.7B Q8_0 fallback to narrow structured tasks.
- Admit a newer pinned 4B model only after it beats the baseline on the same machine.
- A deterministic mode must bypass the model entirely; an assist mode opts into it. If the local runtime is unavailable or fails validation, return the deterministic result — never silently call a cloud service. No cloud URL is accepted in the initial release.
- The model may do query rewriting, CN/EN normalization suggestions, bounded disambiguation among supplied candidates, evidence compression and cited synthesis — each with a stated guardrail. It may never invent a canonical ID, edit the corpus, the graph or the index, or auto-promote prose into the wiki.
- Pin everything in a run manifest: model repo/file/SHA-256, runtime release and binary hash, chat template, prompt/schema version, context size, output cap, seed, samplers, threads, backend, and the evidence-packet checksum.
- Go/no-go gates on a real 16 GB machine over a frozen 200-task corpus suite, covering privacy/offline, peak working set at 8K context, 500-request stability, same-machine repeatability, retrieval value, disambiguation accuracy, compression fidelity, synthesis grounding, CPU latency and token advantage. 16K context is unlocked only if the memory gates pass again.
- Enable rewrite and disambiguation first, compression second, synthesis only after the grounding gate passes.

## Alternatives considered

- A larger 9B-class quantized model — rejected as the supported minimum-hardware default: too little predictable headroom on 16 GB; treat as a quality experiment.
- Making the newest model the reproducibility baseline — rejected: open runtime conversion and Windows backend issues make runtime maturity a release gate.
- Ministral 3 3B and Phi-4-mini — kept as benchmark challengers, not defaults; the latter has less broad multilingual evidence, and a Gemma-class model brings gated custom terms with no clear advantage.
- Advertising the models' nominal 128K-256K context as a 16 GB capability — explicitly rejected; the intended advantage is a compact evidence-complete packet that makes a short context sufficient.
- Generative reranking in the default path — rejected: deterministic hybrid/RRF plus a small cross-encoder stays the baseline unless held-out gains justify it.

## Consequences

- "Deterministic" is defined as the model-free path, never as a property of generation; assist output is cached by model/runtime/prompt/schema/input hash and structurally validated.
- KV-cache memory is planned explicitly (~1.1 GiB at 8K, ~2.25 GiB at 16K for the baseline architecture, before weights) and must be measured as real working set, not asserted.
- If the low-resource fallback fails its quality gates, there is no generative fallback and the product degrades to the deterministic path — an accepted outcome.
