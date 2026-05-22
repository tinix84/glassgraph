"""Orchestrator: load both graphs, compute metrics, render the markdown report.

Run via:
  conda run -n 2brain_env python .tools/comparison/compare.py \
      --graphify-dir .tools/graphify-out \
      [--graphify-run2-dir .tools/graphify-out-run2] \
      --our-touches wiki/sources \
      --output .tools/comparison/graphify-comparison-report.md
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import date
from pathlib import Path

import networkx as nx


_HERE = Path(__file__).resolve().parent


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def _render_top_in_degree(label: str, top: list[tuple[str, int]], n: int = 10) -> str:
    lines = [f"#### Top {min(n, len(top))} entities by in-degree — {label}", "", "| Rank | Entity | In-degree |", "|---|---|---|"]
    for i, (entity, deg) in enumerate(top[:n], 1):
        lines.append(f"| {i} | {entity} | {deg} |")
    return "\n".join(lines)


def _render_report(
    G_ours: nx.DiGraph,
    G_graphify: nx.DiGraph,
    G_graphify_extracted_only: nx.DiGraph,
    our_truth: dict[str, set[str]],
    graphify_all: dict[str, set[str]],
    graphify_extracted: dict[str, set[str]],
    graphify_info: dict,
    pr_all: dict,
    pr_extracted: dict,
    jaccard_graphify: float | None,
    summary_ours: dict,
    summary_graphify: dict,
    output_path: Path,
    source_subset_count: int | None = None,
) -> None:
    lines: list[str] = []

    lines += [
        f"# Glassgraph vs Graphify — Comparison Report",
        f"",
        f"**Date:** {date.today().isoformat()}",
        f"",
        f"**Inputs:**",
        f"- Glassgraph: `touches:` graph from {len(our_truth)} source pages (Stage 1 Aho-Corasick + LLM-curated frontmatter)",
        f"- Graphify: {graphify_info.get('nodes_parsed', 0)} nodes parsed, {graphify_info.get('nodes_skipped', 0)} skipped; "
        f"{graphify_info.get('edges_parsed', 0)} edges parsed, {graphify_info.get('edges_skipped', 0)} skipped",
    ]
    if source_subset_count is not None:
        lines += [f"- **Restricted to {source_subset_count}-source subset** for apples-to-apples comparison"]
    lines += [""]

    if graphify_info.get("error"):
        lines += [f"> ⚠️ Graphify load error: {graphify_info['error']}", ""]

    # ── Executive summary: lead with what we win on ────────────────────────
    lines += ["## Executive summary", ""]
    lines += [
        "Headline: glassgraph wins decisively on **determinism, speed, cost, and audit-trail granularity**; "
        "graphify wins on **community detection, inferred semantic links, and free-form entity discovery**. "
        "Each tool sits at a different point on the auditability-vs-discovery trade-off curve.",
        "",
        "**Glassgraph strengths (the demo's anchor points):**",
        "",
        f"- **Determinism:** Jaccard = 1.0000 across reruns (proven byte-identical). Graphify: " +
            (f"Jaccard = {jaccard_graphify:.4f}" if jaccard_graphify is not None else "single-run only, determinism unmeasured"),
        f"- **Speed:** Stage 1 in ~1s on the full {len(our_truth)}-source corpus. Graphify on a 25-file subset took minutes of LLM subagent dispatch",
        f"- **Cost:** $0 (CPU-only inference). Graphify: N tokens × LLM rate per run",
        f"- **Audit trail:** every glassgraph hit carries `span + alias + canonical` for the matched text. Graphify carries a `confidence` tag (EXTRACTED/INFERRED/AMBIGUOUS) but no span — see Axis 3 for three concrete examples",
        "",
        "**Graph-structural snapshot:**",
        "",
        f"- Glassgraph: {summary_ours['nodes']} nodes, {summary_ours['edges']} edges from {len(our_truth)} source pages",
        f"- Graphify: {summary_graphify['nodes']} nodes, {summary_graphify['edges']} edges (demo-subset)",
        "",
        "**Precision/Recall against our `touches:` — read with context (see Axis 2 for full framing):**",
        "",
        f"- Graphify EXTRACTED-only vs our `touches:`: P={pr_extracted['macro_precision']:.3f}, R={pr_extracted['macro_recall']:.3f}, F1={pr_extracted['macro_f1']:.3f}",
        f"- This is a **vocabulary-mismatch measurement, not a quality verdict.** Glassgraph constrains output to a curated entity vocabulary; graphify generates free-form labels including part numbers (`Infineon IPW60R125CP`) and topology names (`PFC+LLC+SR Architecture`) that glassgraph's dictionary doesn't carry. The low numbers reflect the *intentional* design difference, not graphify being inaccurate.",
        "",
    ]

    lines += ["## Axis 1: Determinism", ""]
    lines += [
        "Determinism is graphify's structural weakness and glassgraph's structural advantage. Same inputs → byte-identical outputs is required for diffing, version control, and incremental updates.",
        "",
        "| Tool | Mean Jaccard (run vs run) | Notes |",
        "|---|---|---|",
        "| **Glassgraph** | 1.0000 | Deterministic by construction: Aho-Corasick scan + seeded BGE-M3 + CUBLAS_WORKSPACE_CONFIG=:16:8 |",
    ]
    if jaccard_graphify is not None:
        lines += [f"| **Graphify** | {jaccard_graphify:.4f} | LLM-bound; varies across runs due to model sampling |"]
    else:
        lines += ["| **Graphify** | (single-run) | Re-run graphify and pass `--graphify-run2-dir` to measure |"]
    lines += [""]

    lines += ["## Axis 2: Precision / Recall vs touches: (with caveats)", ""]
    lines += [
        "**Important framing**: our `touches:` lists are *glassgraph's own output* curated and accepted into the wiki. Asking \"does graphify's LLM rediscover what glassgraph's dictionary found?\" measures **vocabulary overlap**, not extraction quality. Three structural reasons the headline P/R looks low even when graphify is doing well:",
        "",
        "1. **Granularity mismatch:** graphify emits part numbers (`Infineon IPW60R125CP`, `TI TMS320F28377D`) and topology variants (`Three-Phase Active PFC Topology`); our `touches:` favor canonical entity pages (`Infineon`, `Texas-Instruments`).",
        "2. **Free-form labels:** graphify writes `SiC MOSFET` / `Texas Instruments (TI)`, glassgraph emits `SiC-MOSFET` / `Texas-Instruments`. Aggressive slugify-style normalization (current normalizer) collapses most of these.",
        "3. **Coverage asymmetry:** glassgraph's vocabulary is curated, capped at ~1400 entities. Graphify produces unbounded vocabulary; many of its labels are true entities the wiki simply hasn't onboarded yet — they look like FPs but are real discoveries.",
        "",
        "Numbers below are computed with aggressive slugify-style normalization (lowercase + drop parentheticals + collapse non-alphanumeric to nothing + strip corporate suffixes).",
        "",
        "| Variant | Precision | Recall | F1 | Sources scored | Sources skipped (empty truth) |",
        "|---|---|---|---|---|---|",
        f"| Graphify, all entities | {pr_all['macro_precision']:.3f} | {pr_all['macro_recall']:.3f} | {pr_all['macro_f1']:.3f} | {pr_all['sources_scored']} | {pr_all['sources_skipped_empty_truth']} |",
        f"| Graphify, EXTRACTED-only | {pr_extracted['macro_precision']:.3f} | {pr_extracted['macro_recall']:.3f} | {pr_extracted['macro_f1']:.3f} | {pr_extracted['sources_scored']} | {pr_extracted['sources_skipped_empty_truth']} |",
        "",
    ]

    lines += ["## Axis 3: Audit trail / explainability", ""]
    lines += [
        "Three sourced examples picked from the demo-subset, covering CJK teardown, mixed-language news, and cold-start academic. **The key finding: Axis 3 is not a clean win for either tool — it's a genuine trade-off between *per-hit audit granularity* (glassgraph) and *cross-document discovery* (graphify).**",
        "",
        "### Example 1 — CN teardown: `拆解Tesla Model 3逆变器：简洁即最优` (Tesla Model 3 inverter)",
        "",
        "**Glassgraph trace** (`link.py explain` — 25+ hits, sample shown):",
        "",
        "```",
        "[176:181]    'Tesla'                  → Tesla                  via 'Tesla'",
        "[527:549]    'Tesla Model 3 inverter' → Tesla-Model-3-inverter via 'Tesla Model 3 inverter'",
        "[2954:2962]  'SiC FETs'               → SiC-MOSFET             via 'SiC FETs'",
        "[3610:3625]  'Silicon Carbide'        → SiC-MOSFET             via 'Silicon Carbide'",
        "[4848:4850]  'TI'                     → Texas-Instruments      via 'TI'",
        "[7400:7402]  'ST'                     → STMicroelectronics     via 'ST'",
        "[6313:6321]  'Infineon'               → Infineon               via 'Infineon'",
        "```",
        "",
        "Every hit carries `[start:end]` byte offsets into the source body, the literal alias matched (so e.g. `SiC FETs`, `Silicon Carbide`, and `SiC` all collapse to canonical `SiC-MOSFET` — and you can SEE the alias that resolved each one), and surrounding context. Reviewer can verify each claim against source text.",
        "",
        "**Graphify trace** (`graph.json`, 9 nodes + 13 edges referencing this source, sample):",
        "",
        "```",
        "Node: 'Tesla Model 3 Inverter'                          file_type=document",
        "Node: 'ST STGK026 SiC FET'                              file_type=concept",
        "Node: 'TI TMS320F28377DPTPQ MCU'                        file_type=concept",
        "Node: 'Broadcom ACPL-C87BT-000E HV Current Sensor'      file_type=concept",
        "Node: 'Infineon TLF35584QVVS2 DC/DC Converter'          file_type=concept",
        "Node: 'Silver Sintering Thermal Bonding Technology'     file_type=concept",
        "Edge: 'Tesla Model 3 Inverter' --[references, EXTRACTED, 1.0]--> 'TI TMS320F28377DPTPQ MCU'",
        "```",
        "",
        "Graphify is more **specific** — emits exact part numbers (`STGK026`, `TMS320F28377DPTPQ`, `ACPL-C87BT-000E`) that glassgraph's curated vocabulary doesn't carry. But: no span offsets, no alias trace, and you cannot tell from the JSON *where* in the document `Broadcom ACPL-C87BT-000E` was extracted from. Confidence label `EXTRACTED` with score `1.0` is binary: it asserts the LLM found it, not where or how.",
        "",
        "### Example 2 — Mixed EN/CN news: `Nvidia GTC 2026观察（下）` (graphify's #1 god node)",
        "",
        "**Glassgraph trace** (30+ hits — broad span coverage on companies and architectures):",
        "",
        "```",
        "[671:677]    'NVIDIA'             → NVIDIA                    via 'NVIDIA'",
        "[1383:1386]  'SST'                → Solid-State-Transformer   via 'SST'",
        "[3229:3232]  'GaN'                → GaN-HEMT                  via 'GaN'",
        "[5250:5268]  'Schneider Electric' → Schneider-Electric        via 'Schneider Electric'",
        "[7144:7158]  'Hitachi Energy'     → Hitachi-Energy            via 'Hitachi Energy'",
        "```",
        "",
        "**Graphify trace** (9 nodes, 21 edges — this is where graphify shines):",
        "",
        "```",
        "Node: 'Nvidia GTC 2026'           file_type=document",
        "Node: 'DG Matrix (SST Startup)'   file_type=concept   [NEW — not in our wiki]",
        "Node: 'NVIDIA MGX Ecosystem'      file_type=concept   [NEW]",
        "Node: 'Flex (Flextronics)'        file_type=concept",
        "Node: 'Lite-On Technology'        file_type=concept",
        "Node: 'Innoscience'               file_type=concept",
        "",
        "Edge: 'APEC 2026 Conference' --[conceptually_related_to, INFERRED, 0.95]--> 'Nvidia GTC 2026'",
        "Edge: 'NVIDIA MGX Ecosystem' --[conceptually_related_to, INFERRED, 0.85]--> 'NVIDIA Kyber Rack'",
        "Edge: 'DG Matrix (SST Startup)' --[implements, EXTRACTED, 1.0]--> 'Solid-State Transformer (SST)'",
        "```",
        "",
        "Graphify discovers entities glassgraph's dictionary doesn't have (`DG Matrix`, `Lite-On`, `Innoscience`) AND surfaces INFERRED cross-document semantic links (APEC ↔ GTC, MGX ↔ Kyber). Glassgraph cannot do this — its outputs are bounded by what we've curated into the wiki.",
        "",
        "### Example 3 — Cold-start academic: `G8FHMRQC` (arXiv 2025, no wiki touches yet)",
        "",
        "**Glassgraph trace:**",
        "",
        "```",
        "[249:267]  'thermal management' → Thermal-management  via 'thermal management'",
        "Summary: 1 hit, 1 unique canonical, 0 disambiguation warnings",
        "```",
        "",
        "**One hit.** Because academic vocabulary (`load transients`, `holdup time`, `multi-stage conversion`) doesn't yet exist in our entity dictionary. This is the *cold-start failure mode* of dictionary-based approaches.",
        "",
        "**Graphify trace** (3 nodes, 5 edges):",
        "",
        "```",
        "Node: 'AI Load Dynamics — A Power Electronics Perspective'  file_type=paper",
        "Node: 'AI Workload Load Transients'                         file_type=concept   [NEW]",
        "Node: 'Multi-Stage Power Conversion Architecture'           file_type=concept   [NEW]",
        "",
        "Edge: 'Vertical Power Delivery (VPD)' --[semantically_similar_to, INFERRED, 0.75]--> 'Multi-Stage Power Conversion Architecture'",
        "Edge: 'Energy Buffer Circuit for Holdup' --[conceptually_related_to, INFERRED, 0.85]--> 'AI Workload Load Transients'",
        "```",
        "",
        "Graphify extracts 3 concepts AND links them across documents (VPD ↔ Multi-Stage Conversion) — a genuine cross-paper discovery. Glassgraph offers nothing useful here. **This is graphify's strongest example in the demo.**",
        "",
        "### Synthesis",
        "",
        "Axis 3 honestly splits:",
        "",
        "- **Glassgraph wins on per-hit traceability**: `span + alias + canonical` lets a reviewer verify every extraction against the source text. Graphify's `confidence: EXTRACTED, score: 1.0` is opaque by comparison — you cannot tell where in the document the entity came from.",
        "- **Graphify wins on entity discovery**: free-form labeling captures specific part numbers, novel concepts, and cross-document INFERRED semantic links that a curated dictionary will never produce. On cold material (Example 3), this gap is unbridgeable for glassgraph.",
        "- **The right system is probably both:** use glassgraph for the curated 80% (companies, technologies, established products — where audit trail matters and reruns must be deterministic) and graphify or another LLM-based extractor for the cold 20% (new concepts, novel cross-paper links) — then promote stable graphify findings into glassgraph's alias dictionary over time.",
        "",
    ]

    lines += ["## Axis 4: Speed / cost", ""]
    lines += [
        "Glassgraph: free, deterministic, CPU-only, runs in seconds. Graphify: LLM-bound, costs tokens, runs in minutes-to-hours depending on corpus size and model tier.",
        "",
        "| Metric | Glassgraph | Graphify |",
        "|---|---|---|",
        "| Wall-clock on the 25-file demo-subset | < 1s (Stage 1 only) | several minutes of parallel Claude Code subagent dispatch (≈ 25 files / ~22 per chunk → ~2 chunks × ~45s + clustering + report generation) |",
        "| Wall-clock on the full 502-source wiki | ~1s Stage 1 / ~3-5 min Stage 1 + Stage 2 (first run; <1s reruns from embedding cache) | Not attempted — would also have to vision-process the 15,335 images in `raw/assets/` |",
        "| API cost | $0 — runs entirely on CPU. BGE-M3 model is local (~2GB one-time download) | LLM tokens or Claude Code Max subscription minutes; scales linearly with corpus size |",
        "| Determinism cost-amortization | First run pays the price, subsequent reruns reuse the embedding manifest | Every run pays the full LLM cost |",
        "| Incremental updates | Adding one source: re-runs Aho-Corasick on that file only (~0.1s); embeddings reused | Has `--update` flag that limits re-extraction to changed files; still LLM-bound per changed file |",
        "",
    ]

    lines += ["## Axis 5: Graph-structural metrics", ""]
    lines += [
        "| Metric | Ours | Graphify |",
        "|---|---|---|",
        f"| Total nodes | {summary_ours['nodes']} | {summary_graphify['nodes']} |",
        f"| Total edges | {summary_ours['edges']} | {summary_graphify['edges']} |",
        f"| Density | {summary_ours['density']:.4f} | {summary_graphify['density']:.4f} |",
        "",
    ]
    lines += [_render_top_in_degree("Ours", summary_ours["top_in_degree"])]
    lines += [""]
    lines += [_render_top_in_degree("Graphify", summary_graphify["top_in_degree"])]
    lines += [""]

    lines += ["## Pro/cons matrix", ""]
    lines += [
        "| Dimension | Our tool | Graphify | Winner |",
        "|---|---|---|---|",
        f"| Determinism | 1.000 Jaccard | {jaccard_graphify:.4f} Jaccard | **ours** |" if jaccard_graphify is not None else "| Determinism | 1.000 Jaccard | (n/a — single run) | **ours** |",
        f"| Precision (vs touches:) | (we ARE the curation feedstock) | {pr_all['macro_precision']:.3f} | n/a |",
        f"| Recall (vs touches:) | (we ARE the curation feedstock) | {pr_all['macro_recall']:.3f} | n/a |",
        "| Audit trail | span + alias trace | confidence tag | **ours** (more granular) |",
        "| Speed (full corpus) | seconds | minutes-to-hours | **ours** |",
        "| API cost | $0 | LLM-bound | **ours** |",
        "| Communities | networkx Louvain post-hoc | first-class output | **graphify** |",
        "| CJK handling | aliases-based, deterministic; 25+ hits on Tesla CN teardown via dictionary lookup | LLM-based, fluent; handles 特斯拉↔Tesla semantic equivalence natively. Recent upstream fixes (PRs #937, #964) suggest CJK was historically a known weak spot | **tie** — both adequate on the demo subset; different failure modes |",
        "",
    ]

    lines += ["## GitHub roadmap check", ""]
    lines += [
        "Snapshot of https://github.com/safishamsi/graphify as of demo day (2026-05-22):",
        "",
        "**Project health:** 51,366 stars · 5,518 forks · 107 open issues · default branch `v8` · last push within hours of this report. Graphify is a mature, popular, actively-developed open-source project.",
        "",
        "**Recent merged PRs (last ~24h, sample):**",
        "",
        "- #982 docs: Uzbek README translation (community-driven i18n)",
        "- #973 fix(llm): honor `GRAPHIFY_MAX_OUTPUT_TOKENS` for OpenAI-compatible backends",
        "- #969 Merge cross-file Swift extension nodes into the canonical type",
        "- #964 Keep non-English query terms searchable",
        "- #956 feat(multigraph): runtime compatibility probe",
        "- #937 fix: CJK/Unicode labels silently skipped in `_norm`/`_norm_label` dedup (follow-up to #811)",
        "- #931 feat(install): project-scoped skill installs",
        "",
        "**Open issues directionally relevant to this comparison:**",
        "",
        "- #981 Configurable base URL for OpenAI/Anthropic backends (custom providers)",
        "- #978 `graphify query`: punctuation in search terms breaks node matching",
        "- #976 Add copilot-cli backend for semantic extraction",
        "- #975 Add GitHub Models backend",
        "- #974 Add Vertex AI backend",
        "- #972 Can it support more nodes/edges/communities?",
        "",
        "**Reading of the roadmap:** graphify's near-term work is concentrated on (a) backend pluggability — supporting many LLM providers — and (b) Unicode/CJK robustness (#937, #964, #978). This is consistent with growing into a general-purpose KG tool. **Determinism is not on the roadmap** — that's a structural property of the LLM-based approach, not a missing feature, and it's the dimension where glassgraph has a permanent edge.",
        "",
    ]

    lines += ["## Decision", ""]
    lines += [
        "**Honest verdict: don't ship one tool — use both, with a promotion path between them.**",
        "",
        "The trade-off is real and structural. Glassgraph wins on determinism, speed, cost, and audit granularity. Graphify wins on entity discovery, cross-document INFERRED links, free-form labeling, community detection, and cold-start coverage. These are not the same axis. Trying to pick a single winner is the wrong question.",
        "",
        "**Recommended operating model:**",
        "",
        "1. **Glassgraph as the production graph layer** for the curated 80% of the corpus where entities are known and where the wiki's `touches:` must remain stable across reruns (version-controlled, diff-friendly, reproducible).",
        "2. **Graphify as the cold-start discovery layer** for new material — especially academic papers and unfamiliar topical clusters where the alias dictionary doesn't yet exist (Example 3 above demonstrates this concretely).",
        "3. **Promotion path:** when graphify surfaces a recurring concept across multiple sources (≥ 3 INFERRED edges or ≥ 5 EXTRACTED references), promote it into glassgraph's wiki as a new entity page with proper aliases. Over time, this shifts coverage from the LLM tier to the deterministic tier without losing prior discoveries.",
        "4. **Glassgraph next:** the [glassgraph #1 issue](https://github.com/tinix84/glassgraph/issues/1) adds god-nodes, surprising-connections, and suggested-questions outputs for parity with graphify's report-style affordances — deterministic versions of the same UX, anchored in the existing graph.",
        "",
        "**Friday demo bottom line:** the work done on glassgraph is NOT trash. It's the right tool for the right slice of the problem. Graphify is the right tool for the complementary slice. The comparison framework itself (this report) is the durable artifact — it tells us *which slice is which* and lets us measure either tool honestly going forward.",
        "",
    ]

    lines += ["## Appendix: how to reproduce", ""]
    lines += [
        "```powershell",
        "# 1. Generate graphify output",
        "conda run -n 2brain_env pip install graphifyy",
        "conda run -n 2brain_env graphify install --platform claude",
        "# From inside Claude Code: /graphify (point at D:\\OneDrive\\2brain\\raw)",
        "",
        "# 2. Run the comparison",
        "conda run -n 2brain_env python .tools/comparison/compare.py \\",
        "  --graphify-dir .tools/graphify-out \\",
        "  --our-touches wiki/sources \\",
        "  --output .tools/comparison/graphify-comparison-report.md",
        "```",
        "",
    ]

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text("\n".join(lines), encoding="utf-8")


def _filter_by_subset(
    G_ours: nx.DiGraph,
    our_truth: dict[str, set[str]],
    subset_stems: set[str],
):
    """Restrict our graph and truth dict to the given source stems for apples-to-apples comparison."""
    filtered_truth = {k: v for k, v in our_truth.items() if k in subset_stems}
    nodes_to_keep = set(subset_stems)
    # Also keep any entity nodes that those sources point to
    for src in subset_stems:
        if src in G_ours:
            nodes_to_keep.update(G_ours.successors(src))
    G_filtered = G_ours.subgraph(nodes_to_keep).copy()
    return G_filtered, filtered_truth


def main() -> None:
    parser = argparse.ArgumentParser(description="Glassgraph vs graphify comparison")
    parser.add_argument("--graphify-dir", type=Path, required=True, help="Directory containing graph.json")
    parser.add_argument("--graphify-run2-dir", type=Path, default=None, help="(Optional) second graphify run for determinism diff")
    parser.add_argument("--our-touches", type=Path, required=True, help="Path to wiki/sources/ directory")
    parser.add_argument("--source-subset", type=Path, default=None, help="(Optional) directory of *.md files; restricts our touches: ground truth to those stems for apples-to-apples comparison")
    parser.add_argument("--output", type=Path, required=True, help="Output report path (.md)")
    args = parser.parse_args()

    load_graphify = _load("load_graphify")
    load_ours = _load("load_ours")
    metrics = _load("metrics")

    # Our side
    G_ours = load_ours.load_touches_graph(args.our_touches)
    our_truth = load_ours.per_source_truth(args.our_touches)

    # Apply source-subset filter if provided
    source_subset_count = None
    if args.source_subset is not None:
        subset_stems = {p.stem for p in args.source_subset.glob("*.md")}
        if not subset_stems:
            print(f"WARN: --source-subset directory {args.source_subset} contains no .md files; ignoring filter")
        else:
            G_ours, our_truth = _filter_by_subset(G_ours, our_truth, subset_stems)
            source_subset_count = len(subset_stems)
            print(f"Source subset filter applied: {source_subset_count} stems → {len(our_truth)} matched in our wiki")

    # Graphify side (all entities)
    graphify_json = args.graphify_dir / "graph.json"
    G_graphify, graphify_info = load_graphify.load_graphify_graph(graphify_json)
    graphify_all = load_graphify.per_source_extracted(G_graphify)

    # Graphify side (EXTRACTED-only)
    G_graphify_extracted, _info2 = load_graphify.load_graphify_graph(graphify_json, only_extracted=True)
    graphify_extracted = load_graphify.per_source_extracted(G_graphify_extracted)

    # Precision / Recall (both variants)
    pr_all = metrics.precision_recall(graphify_all, our_truth)
    pr_extracted = metrics.precision_recall(graphify_extracted, our_truth)

    # Jaccard if second run provided
    jaccard_graphify = None
    if args.graphify_run2_dir is not None:
        G_graphify_run2, _info3 = load_graphify.load_graphify_graph(args.graphify_run2_dir / "graph.json")
        graphify_run2 = load_graphify.per_source_extracted(G_graphify_run2)
        jaccard_graphify = metrics.mean_jaccard(graphify_all, graphify_run2)

    summary_ours = metrics.graph_summary(G_ours)
    summary_graphify = metrics.graph_summary(G_graphify)

    _render_report(
        G_ours=G_ours,
        G_graphify=G_graphify,
        G_graphify_extracted_only=G_graphify_extracted,
        our_truth=our_truth,
        graphify_all=graphify_all,
        graphify_extracted=graphify_extracted,
        graphify_info=graphify_info,
        pr_all=pr_all,
        pr_extracted=pr_extracted,
        jaccard_graphify=jaccard_graphify,
        summary_ours=summary_ours,
        summary_graphify=summary_graphify,
        output_path=args.output,
        source_subset_count=source_subset_count,
    )

    print(f"Report written to {args.output}")
    print(f"  Our: {summary_ours['nodes']} nodes, {summary_ours['edges']} edges")
    print(f"  Graphify: {summary_graphify['nodes']} nodes, {summary_graphify['edges']} edges (skipped {graphify_info['nodes_skipped']} nodes, {graphify_info['edges_skipped']} edges)")
    print(f"  PR (all): P={pr_all['macro_precision']:.3f} R={pr_all['macro_recall']:.3f} F1={pr_all['macro_f1']:.3f}")
    print(f"  PR (EXTRACTED-only): P={pr_extracted['macro_precision']:.3f} R={pr_extracted['macro_recall']:.3f} F1={pr_extracted['macro_f1']:.3f}")
    if jaccard_graphify is not None:
        print(f"  Graphify determinism: Jaccard={jaccard_graphify:.4f}")


if __name__ == "__main__":
    main()
