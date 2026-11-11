# glassgraph

Deterministic entity linker and graph builder for personal research wikis.

## What it does

Given a folder of markdown files and a wiki of entity pages (each carrying an `aliases:` frontmatter list), glassgraph extracts entity mentions and builds a source-to-entity graph with no LLM in the loop.

- **Stage 1** — Aho-Corasick literal matching against a dictionary of aliases. CJK-boundary aware. ~1s on 500 files.
- **Stage 2** *(opt-in)* — BGE-M3 dense semantic retrieval over entity page bodies. Surfaces candidate entities not in the alias dictionary. CPU-only, deterministic with `torch.manual_seed(0)` + `CUBLAS_WORKSPACE_CONFIG=:16:8`. ~3-5 min on 500 files first run, sub-second on cached reruns.

Every match is byte-reproducible: same inputs → byte-identical extraction cache and embedding manifest.

## Why this exists

LLM-based knowledge-graph extractors are powerful but expensive, non-deterministic, and produce edges of varying confidence that are hard to audit. glassgraph is the opposite trade-off: fully deterministic, free to run, with an explicit dictionary of aliases you control. Every hit has a span + alias + canonical trace; nothing is inferred.

It's not a replacement for tools like [graphify](https://github.com/safishamsi/graphify) — it's the right tool when:

- Your domain has a curated entity vocabulary (companies, products, technologies)
- You want byte-reproducible re-runs for diffing and version control
- You can't or don't want to pay LLM API costs at corpus scale
- Audit trail matters more than discovering novel inferred connections

If you want first-class community detection, INFERRED edges, or semantic clustering surfaced without an alias dictionary — use graphify or a similar LLM-based tool.

## Quick start

```bash
pip install pyahocorasick networkx pyyaml sentence-transformers torch
python link.py path/to/source.md
```

Outputs `.tools/extraction-cache/{stem}.json` with `entities` (Stage 1 hits) and optionally `vector_entities` (Stage 2 hits, with `--vector`).

See `python link.py --help` for the full command list (extract, backfill, lint, explain, suggest, history).

## Retrieval benchmark

`retrieval_benchmark_cli.py` measures GrooveSeek or QMD with the evidence-level metrics from ADR-0014. The command uses one metric implementation for the public fixture and the private benchmark.

Run the public fixture with GrooveSeek:

```powershell
python retrieval_benchmark_cli.py `
  --queries tests/fixtures/benchmark/v1/queries.json `
  --backend grooveseek `
  --groove-executable <groove-command> `
  --groove-config <frozen-groove.toml> `
  --knowledge-base <fixture-index> `
  --benchmark-corpus-root tests/fixtures/benchmark/v1/corpus `
  --tokenizer <pinned-tokenizer.json> `
  --retrieval-model-id <model-uri-or-version> `
  --retrieval-model-artifact <fastembed-cache-directory> `
  --privacy public `
  --setup-time-ms <milliseconds> `
  --full-build-time-ms <milliseconds> `
  --no-change-update-ms <milliseconds> `
  --one-file-update-ms <milliseconds> `
  --derived-index-size-bytes <bytes> `
  --offline-verified
```

Run a private split only on the local computer. The command rejects an incomplete or unadjudicated 60-record workbook.

```powershell
python retrieval_benchmark_cli.py `
  --queries <private-authoring-workbook.json> `
  --backend grooveseek `
  --groove-executable <groove-command> `
  --groove-config <frozen-groove.toml> `
  --knowledge-base <private-index> `
  --benchmark-corpus-root <frozen-private-corpus-copy> `
  --tokenizer <pinned-tokenizer.json> `
  --retrieval-model-id <model-uri-or-version> `
  --retrieval-model-artifact <fastembed-cache-directory> `
  --path-prefix wiki `
  --privacy private `
  --split development `
  --output <new-local-private-report.json> `
  --setup-time-ms <milliseconds> `
  --full-build-time-ms <milliseconds> `
  --no-change-update-ms <milliseconds> `
  --one-file-update-ms <milliseconds> `
  --derived-index-size-bytes <bytes> `
  --offline-verified
```

The query file contains the frozen manifest and ADR-0013 evidence IDs. Each positive record keeps required `direct` or `supporting` judgments separate from an explicit nonempty `irrelevant` list. The command derives every identity again from the frozen Markdown. It verifies the NFC- and LF-normalized corpus snapshot. It rejects stale manifest hashes or split maps. Line-ending-only and canonically equivalent Unicode changes do not change the corpus snapshot hash.

Benchmark versions are content-addressed as `public-v1-<identity-hash>` or `private-v1-<identity-hash>`. The identity covers the frozen corpus, query set, and judgment set. A corpus, query, split, or judgment correction therefore requires a new version. Result limits below 10 are rejected because the report publishes Recall@10 and nDCG@10.

Development runs can tune settings. Each report records a settings hash derived from the backend, result limit, path prefix, tokenizer reference, retrieval-model identity, and backend-specific index or executable arguments. The settings identity includes content hashes for the tokenizer, retrieval model, backend executable or package, and derived index. QMD settings also include the embed, generate, and rerank model hashes. Repeat `--backend-config-artifact` for extra model or backend configuration files. All runs reject unresolved artifact fingerprints. The report records all artifact hashes. Before a private evaluation run, store the selected development hash under `manifest.locked_backend_settings.<backend>`. Pass the same value with `--settings-lock`. The runner recomputes the hash. It rejects an evaluation when the lock is missing, different, or paired with changed settings.

GrooveSeek runs pass the pinned model with `--model`. They also set `FASTEMBED_CACHE_DIR` to the fingerprinted model-cache directory. This overrides an embedding provider in the GrooveSeek configuration.

The runner compares the GrooveSeek document roster and content hashes with the frozen corpus. It also requires one indexed chunk and vector for each document.

QMD runs require `--qmd-config <index-name>.yml`, `--qmd-index-db <index.sqlite>`, and `--qmd-build-receipt <receipt.json>`. The configuration must define `models.embed`, `models.generate`, and `models.rerank`.

The embed value and `--retrieval-model-id` must use the same literal absolute model-file value that QMD stored. The runner independently resolves that value to the pinned artifact. It uses QMD's installed YAML parser for the configuration hash, model checks, and model hashes. It also verifies the QMD 2.8.3 embedding fingerprint before retrieval.

Build QMD through `qmd_benchmark_build.py`. This command runs `qmd update` and forced `qmd embed -f` with the pinned literal model ID. It writes the receipt only after the completed index passes the frozen-corpus, chunk, vector, model, and formatter checks. The build proof compares each active chunk's embedding state before and after the forced embed. The write-once receipt binds the QMD package, all three model files, model ID, configuration, corpus documents, and SQLite snapshot. Replacing a GGUF file at the same path therefore invalidates the index.

```powershell
python qmd_benchmark_build.py `
  --privacy public `
  --node-executable <node> `
  --qmd-script <qmd-script> `
  --qmd-config <index-name>.yml `
  --qmd-index-db <index.sqlite> `
  --index <index-name> `
  --collection <collection-name> `
  --corpus-root <backend-corpus-copy> `
  --benchmark-corpus-root <frozen-corpus> `
  --retrieval-model-id <literal-absolute-model-path> `
  --retrieval-model-artifact <model.gguf> `
  --output <new-build-receipt.json>
```

Use `--privacy private --queries <private-workbook>` for the private partition. The builder applies the same effective Git-ignore, tracked-file, nested-checkout, and vault-containment checks before it opens the index. Benchmark configurations with collection update hooks are rejected; all three QMD model values must be absolute local files.

The selected QMD collection must contain the complete frozen document roster. Every indexed chunk must have its exact `hash_seq` vector key.

The runner pins `INDEX_PATH`, `QMD_CONFIG_DIR`, and `QMD_EMBED_MODEL`. It clears ambient QMD query settings. Each query must return a vector-score trace. This trace proves that hybrid retrieval ran.

The public command requires at least five positive and five negative queries. It prints aggregate metrics only.

The private workbook and report must stay under the vault-side `.glassgraph/benchmarks/private/v1/` directory on a local drive. If the vault has Git metadata, `/.glassgraph/benchmarks/private/` must be explicitly ignored. A private input, corpus, or report inside a nested Git checkout is rejected.

The private command writes its aggregate report to a new file in that directory. It prints no benchmark data. It never replaces an existing file.

Positive retrieval metrics use ranked raw hits. Negative false-positive metrics use accepted hits after backend confidence abstention. The report also keeps the raw negative false-positive rate so that confidence behavior is visible.

Explanation trace availability reports whether a backend returned a structurally valid trace. Explanation fidelity is stricter. It verifies that each GrooveSeek match span names text from the query. QMD score traces count as available, but not as independently verified fidelity.

## Architecture

```
link.py          CLI entry — extract / backfill / lint / explain / suggest / history
linker.py        Aho-Corasick scan + dedup + disambiguation (Stage 1)
stage2.py        BGE-M3 embedding + cosine retrieval (Stage 2, opt-in)
index.py         Build alias manifest + Aho-Corasick automaton from wiki/
graph.py         touches: → networkx DiGraph (source ↔ entity)
explain.py       Per-source debug view (every hit + span + context)
suggest.py       Alias candidate proposer (TF/DF on raw bodies)
lint.py          8 defensive lints on wiki YAML, alias collisions, broken wikilinks, etc.
history.py       Append-only backfill history with per-run deltas
retrieval_benchmark.py      Evidence-group metrics shared by all backends
retrieval_backends.py       GrooveSeek and QMD result adapters
retrieval_benchmark_cli.py  Local public/private benchmark command
qmd_benchmark_build.py      Controlled forced QMD build and receipt command

comparison/      Head-to-head comparison framework vs graphify
  load_graphify.py     Defensive parser for graphify graph.json
  load_ours.py         Parse wiki/sources/touches: into networkx DiGraph
  metrics.py           P/R/F1, Jaccard, graph summaries, name normalization
  compare.py           CLI orchestrator → markdown report

docs/            Long-form journey writeup (mkdocs Material site)
  01-origin.md         Part 1 — Why a personal LLM wiki
  02-obsidian-substrate.md   Part 2 — Obsidian as substrate
  03-wiki-llm.md             Part 3 — The wiki LLM
  04-python-lint.md          Part 4 — When LLM curation fails (lint)
  05-stage1-aho-corasick.md  Part 5 — Stage 1 entity linking
  06-stage2-bge-m3.md        Part 6 — Stage 2 dense retrieval
  07-graphify-comparison.md  Part 7 — The graphify comparison
  08-whats-next.md           Part 8 — RAG, DB, and beyond
```

## Documentation site

The `docs/` folder is an [mkdocs Material](https://squidfunk.github.io/mkdocs-material/) site. Preview locally:

```bash
pip install -r docs/requirements.txt
mkdocs serve   # → http://localhost:8000
```

It contains an eight-part journey article describing how this project came to exist, from the original personal-knowledge-management problem through the graphify head-to-head benchmark.

Wiki schema assumed: pages under `wiki/{companies,technologies,products,themes}/*.md` each with frontmatter:

```yaml
---
type: company | technology | product | theme
aliases: [...]      # union of aliases_en + aliases_cn
aliases_en: [...]
aliases_cn: [...]
---
```

Source pages under `wiki/sources/*.md` carry a `touches: ['[[Entity]]', ...]` frontmatter field that builds the graph.

## Status

**Experimental / personal-research origin.** Built for one corpus (power-electronics & EV powertrain research clippings). Battle-tested on ~500 sources with ~1400 entity pages. Not packaged, not pip-installable, no semver guarantees. The CLI surface is stable but the internal API is not.

## Inspiration & acknowledgements

The output structure (god nodes / surprising connections / suggested questions in `GRAPH_REPORT.md`) is borrowed from [graphify](https://github.com/safishamsi/graphify), which inspired the comparison this tool emerged from. graphify's LLM-based approach and glassgraph's deterministic approach are complementary, not adversarial — different points on the same trade-off curve.

## License

MIT — see [LICENSE](LICENSE).
