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

### Install shared validation

Install the validation package from this checkout:

```bash
python -m pip install -e .
```

```python
from glassgraph.core.frontmatter import parse, validate_metadata
from glassgraph.wiki.schema import validate_meta

page = parse("---\ntype: company\n---\nBody.\n")
errors = validate_metadata(page.metadata, "company")
errors, warnings = validate_meta(page.metadata, "company")
```

The package supplies parsing, structural validation, and writer policy.
The legacy `frontmatter.py` delegates to the same implementation, including in an uninstalled source checkout.
Existing scripts retain their commands and dependencies below.
The package exposes portable lint and Stage 1 extraction. Other scripts retain their entry points during incremental migration.
See [ADR-0018](docs/adr/ADR-0018-incremental-package-consolidation.md) for the consolidation decision.

### Run portable lint

```powershell
glassgraph --root 'D:\vault' lint
glassgraph lint --root 'D:\vault' --severity WARN
python -m glassgraph lint
```

Root resolution uses this order:

1. Use the `--root` directory.
2. Use `GLASSGRAPH_ROOT` when no flag is supplied.
3. Search upward from the current directory for the nearest `.glassgraph/` directory.

An invalid explicit or environment root is an error. Discovery never uses the code checkout's location.
The shared `discover_root(start=...)` interface also accepts a target file's parent directory for hook integration.

The optional `<vault>/.glassgraph/config.toml` file supports:

```toml
[paths]
wiki = "wiki"
raw = "raw"
entity_dirs = ["companies", "technologies", "products", "markets", "themes"]
exclude = [".temp"]
```

These defaults preserve existing lint directory order and first-owner alias resolution.
`sources/` is always a source directory. Additional entity directories use each page's declared type.
Directory names must be unique single path components, ignoring case. `sources` is reserved in every letter case.
Exclusions are file or directory paths relative to the vault root, not glob patterns.
Configured wiki, raw, and excluded paths must stay inside the vault. Scanned links that leave the vault are configuration errors.
When the raw path is the default `raw`, lint also resolves legacy `raw-CN` citation targets.

The optional `[zotero].db` field accepts an explicit database path, relative to the vault or absolute.
Its default is unset. Lint does not open a Zotero database.
Unknown fields and malformed configuration are errors.

Lint reads the configured corpus and prints its existing report format. It does not create caches, reports, or migrated state.
Exit codes are `0` for no critical findings, `1` for critical findings, and `2` for configuration or read errors.
The severity filter changes displayed findings only. It cannot hide a failing exit code.
The legacy `lint.py` import delegates to the same implementation.
The remaining commands and state migration are covered by [issue #4](https://github.com/tinix84/glassgraph/issues/4).

### Run portable Stage 1 extraction

```powershell
glassgraph --root 'D:\vault' extract raw/example.md
glassgraph extract raw/example.md --dry-run
python -m glassgraph extract wiki/sources/example.md
```

Extraction uses the same root discovery and configuration as lint.
Relative source paths start at the vault root, including when the current directory is nested.
Sources must be Markdown files inside configured raw or wiki/sources directories.
Configured entity directory order and exclusions apply to the alias dictionary.
Candidates require review before wiki changes.

The command prints result JSON. Normal execution also writes these derived files:

- `.glassgraph/index/manifest.json` and `.glassgraph/index/aliases.json`
- `.glassgraph/cache/extraction/<vault-relative-source-path>.json`, retaining the complete source filename

For example, `raw/folder/example.md` uses `.glassgraph/cache/extraction/raw/folder/example.md.json`.
Different source folders retain separate cache files.
Optional disambiguation rules use `.glassgraph/index/disambiguation.yaml`, with the existing list-of-patterns format.
The command does not copy legacy rules or migrate legacy state.

Each run reads current source text, aliases, and disambiguation rules.
`--dry-run` prints JSON without writing files or creating directories.
Result fields match legacy Stage 1 output. Runtime timestamps vary between runs.
Exit codes are `0` for success and `2` for configuration or read errors.
Derived paths must remain inside the vault, outside canonical input directories, and free of redirected output links.
Canonical Markdown and legacy `.tools` state remain unchanged.
Stage 2 and backfill continue through the legacy commands below.

### Run the existing linker

```bash
pip install pyahocorasick networkx pyyaml sentence-transformers torch
python link.py path/to/source.md
```

Outputs `.tools/extraction-cache/{stem}.json` with `entities` (Stage 1 hits) and optionally `vector_entities` (Stage 2 hits, with `--vector`).

See `python link.py --help` for the full command list (extract, backfill, lint, explain, suggest, history).

Run `python link.py lint` before ingestion or backfill. It reports malformed
metadata as CRITICAL and exits with code 1. Checks include list types, quoted
wikilinks in `touches`, vendor strings, source fields, page types, and calendar
dates. Dates must be `YYYY-MM-DD` or `"?"`; partial dates are reported without
changing them. Source citations can use `.md`, vault folder paths, headings,
block references, and display text. A missing folder path remains unresolved
even when another folder contains the same filename. Lint never changes pages.

## Private semantic-assist prototype

`glassgraph.assist` validates evidence packets and supplied advisory output.
It does not execute a model or contact a runtime.

```python
from glassgraph.assist import build_packet, apply_advice
from glassgraph.core.retrieval_benchmark import derive_evidence_records

records = derive_evidence_records(corpus_root, {"path": "example.md", "text": "Exact passage."})
packet = build_packet(corpus_root, "Research question?", records)
deterministic = apply_advice(corpus_root, packet)
review_candidate = apply_advice(corpus_root, packet, enabled=True, response=local_output_json)
```

Each evidence record is verified against current Markdown, including its source hash and exact locator.
Packets preserve evidence order and reject oversized input without truncation.
Limits are 20 records and 32,768 UTF-8 bytes per packet, and 8,192 UTF-8 bytes per output.
These limits are byte budgets, not tokenizer counts.

Supplied output has this envelope:

```json
{"schema_version":"glassgraph.assist-output.v1","packet_hash":"<packet checksum>","task":"rewrite","payload":{"query":"Suggested research query"}}
```

The supported tasks are:

| Task | Payload | Validation |
|---|---|---|
| `rewrite` | `{"query": "..."}` | Nonempty suggestion, at most 1,024 UTF-8 bytes; never applied automatically |
| `disambiguate` | `{"evidence_ids": ["..."]}` | Unique IDs from the packet; an empty selection is allowed |
| `compress` | `{"extracts": [{"evidence_id": "...", "quote": "..."}]}` | Each quote occurs contiguously in its cited packet passage |

Unknown fields, duplicate JSON keys, stale packets, invented IDs, and unsupported tasks are rejected.
Accepted advice requires review. Exact quotation does not establish semantic support or relevance.
Free-form synthesis remains disabled under [ADR-0019](docs/adr/ADR-0019-private-assist-output-replay.md).
Issue #6 owns local runtime execution and measured model admission.

Disabled assist returns the complete validated packet. Missing or invalid output falls back to that packet.
A stale packet raises `AssistError`; stale evidence is not a valid fallback.
The module performs no writes or network calls and labels supplied output as runtime-unattested.
Callers must keep private packets and output local.

Run the read-only synthetic replay after installation:

```bash
python prototypes/semantic_assist_replay.py
```

This demonstrates deterministic output, advisory extraction, and invalid-output fallback. It is not an inference benchmark.

## Retrieval benchmark

`retrieval_benchmark_cli.py` measures GrooveSeek or QMD with the evidence-level metrics from ADR-0014. The command uses one metric implementation for the public fixture and the private benchmark.

### Topic-driven private search lab

`search_lab.py` implements the ADR-0016 research loop. A development brief contains a topic or an argument. It also contains exact Sol reference citations and development questions. `run_trials()` sends the same ordered questions to each configured retrieval adapter. `compare_trial()` reports:

- Exact-passage coverage.
- Cited-document coverage.
- Ranks and non-reference documents.
- Abstention behavior.
- Latency and context tokens.
- Untouched backend scores.

Record one settings change per development iteration. Lock the selected settings before a separate holdout brief is loaded or executed. The API rejects holdout execution before the lock. It also rejects development execution or tuning after the lock.

`search_lab_cli.py` creates a private offline report from local brief, run, lock, and holdout files:

```powershell
python search_lab_cli.py `
  --brief <private-development-brief.json> `
  --holdout-brief <private-holdout-brief.json> `
  --runs <private-backend-runs.json> `
  --tuning <private-tuning-history.json> `
  --corpus-root <frozen-private-corpus-copy> `
  --settings-lock <private-settings-lock.json> `
  --output <new-private-report.json> `
  --offline-verified
```

All five private JSON inputs and the report must stay in `.glassgraph/benchmarks/private/v1/`. The report preserves private query-level material. Do not publish it. Publish only aggregate measurements and decisions.

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
lint.py          14 defensive lints on wiki YAML, metadata, aliases, wikilinks, etc.
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

## Release qualification and delivery

The normative [release gates](https://github.com/tinix84/glassgraph/issues/23) distinguish core release requirements from optional local-model admission.
An unmeasured gate does not pass. Contract prototypes and passing synthetic tests do not establish release readiness.
The [implementation route](https://github.com/tinix84/glassgraph/issues/24) sequences portable integration, compiler lifecycle, retrieval integration, and qualification.
Existing graph, relation, local-model, and editorial issues retain their own scope.
See [ADR-0020](docs/adr/ADR-0020-v1-release-gate-profiles.md) and [ADR-0021](docs/adr/ADR-0021-v1-delivery-sequencing.md) for the decisions.

## Status

**Experimental / personal-research origin.** Built for a power-electronics and EV-powertrain research corpus. Shared validation supports an editable installation. Existing CLI scripts require a source checkout and their listed dependencies. The internal interfaces have no compatibility guarantee.

## Inspiration & acknowledgements

The output structure (god nodes / surprising connections / suggested questions in `GRAPH_REPORT.md`) is borrowed from [graphify](https://github.com/safishamsi/graphify), which inspired the comparison this tool emerged from. graphify's LLM-based approach and glassgraph's deterministic approach are complementary, not adversarial — different points on the same trade-off curve.

## License

MIT — see [LICENSE](LICENSE).
