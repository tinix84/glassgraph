"""NetworkX-backed graph metrics for backfill audit. Pattern from tinix84_twin/graph_analysis.py."""
from __future__ import annotations

import re
from pathlib import Path

import networkx as nx


def _load_frontmatter():
    import importlib.util, sys
    from pathlib import Path
    if "frontmatter" in sys.modules:
        return sys.modules["frontmatter"]
    src = Path(__file__).resolve().parent / "frontmatter.py"
    spec = importlib.util.spec_from_file_location("frontmatter", src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["frontmatter"] = mod
    spec.loader.exec_module(mod)
    return mod


frontmatter = _load_frontmatter()

_ENTITY_DIRS = ("companies", "technologies", "products", "themes")
_WIKILINK_RE = re.compile(r"^\[\[(.+?)(\|.+?)?\]\]$")


def _strip_wikilink(entry: str) -> str:
    """'[[Tesla|alias]]' → 'Tesla'. Bare 'Tesla' passes through."""
    m = _WIKILINK_RE.match(entry.strip())
    return m.group(1) if m else entry.strip()


def _parse_touches(source_page: Path) -> list[str]:
    """Return list of bare canonical names from touches: frontmatter."""
    fm = frontmatter.parse_file(source_page).metadata
    if not fm:
        return []
    raw = fm.get("touches") or []
    if isinstance(raw, str):
        raw = [raw]
    return [_strip_wikilink(str(t)) for t in raw if t]


def build_current_graph(sources_dir: Path) -> nx.DiGraph:
    """Build G_current: source → entity edges from existing touches: frontmatter."""
    G = nx.DiGraph()
    if not sources_dir.exists():
        return G
    for page in sorted(sources_dir.glob("*.md")):
        source_stem = page.stem
        for canonical in _parse_touches(page):
            if canonical:
                if G.has_edge(source_stem, canonical):
                    G[source_stem][canonical]["weight"] += 1
                else:
                    G.add_edge(source_stem, canonical, weight=1)
    return G


def build_stage1_graph(results: dict[str, list[str]]) -> nx.DiGraph:
    """Build G_stage1: source → entity edges from Stage 1 extraction results.

    Args:
        results: {source_stem: [canonical, ...]}
    """
    G = nx.DiGraph()
    for source_stem, canonicals in results.items():
        for canonical in canonicals:
            if G.has_edge(source_stem, canonical):
                G[source_stem][canonical]["weight"] += 1
            else:
                G.add_edge(source_stem, canonical, weight=1)
    return G


def compute_match_rate(
    G_current: nx.DiGraph,
    G_stage1: nx.DiGraph,
    sources: list[str],
) -> float:
    """Average per-source match rate: len(current ∩ stage1) / len(current)."""
    rates = []
    for src in sources:
        current_entities = {v for _, v in G_current.out_edges(src)} if G_current.has_node(src) else set()
        stage1_entities = {v for _, v in G_stage1.out_edges(src)} if G_stage1.has_node(src) else set()
        if not current_entities:
            rates.append(1.0)
            continue
        rates.append(len(current_entities & stage1_entities) / len(current_entities))
    return sum(rates) / len(rates) if rates else 1.0


def get_orphan_entities(G: nx.DiGraph, entity_nodes: set[str]) -> list[str]:
    """Entity nodes with in-degree 0 in G."""
    return sorted(n for n in entity_nodes if G.in_degree(n) == 0)


def get_phantoms(stage1_canonicals: set[str], wiki_dir: Path | None) -> set[str]:
    """Canonicals found by Stage 1 that have no matching wiki page."""
    if wiki_dir is None:
        return set()
    known: set[str] = set()
    for d_name in _ENTITY_DIRS:
        d = wiki_dir / d_name
        if d.exists():
            known.update(p.stem for p in d.glob("*.md"))
    return stage1_canonicals - known


def get_in_degree_delta(
    G_current: nx.DiGraph,
    G_stage1: nx.DiGraph,
    entity_nodes: set[str],
) -> list[tuple[str, int]]:
    """List of (canonical, delta) sorted by delta descending."""
    deltas = []
    for node in entity_nodes:
        s1 = G_stage1.in_degree(node) if G_stage1.has_node(node) else 0
        cur = G_current.in_degree(node) if G_current.has_node(node) else 0
        delta = s1 - cur
        deltas.append((node, delta))
    deltas.sort(key=lambda x: -x[1])
    return deltas


def _entity_nodes_from_wiki(wiki_dir: Path) -> set[str]:
    nodes: set[str] = set()
    for d_name in _ENTITY_DIRS:
        d = wiki_dir / d_name
        if d.exists():
            nodes.update(p.stem for p in d.glob("*.md"))
    return nodes


def render_report(
    sources: list[str],
    G_current: nx.DiGraph,
    G_stage1: nx.DiGraph,
    entity_nodes: set[str],
    wiki_dir: Path | None,
    phantom_canonicals: set[str],
    date_str: str,
    top_n: int = 20,
) -> str:
    match_rate = compute_match_rate(G_current, G_stage1, sources)
    orphans = get_orphan_entities(G_stage1, entity_nodes)
    delta = get_in_degree_delta(G_current, G_stage1, entity_nodes)
    gainers = [(n, d) for n, d in delta if d > 0][:top_n]
    losers = [(n, d) for n, d in delta if d < 0][-top_n:]

    lines = [
        f"# Backfill Audit — Stage 1 vs Current touches: — {date_str}",
        "",
        "## Summary",
        f"- Sources scanned: {len(sources)}",
        f"- Overall match rate: {match_rate:.1%}",
        f"- Orphan entities (Stage 1 never touches): {len(orphans)}",
        f"- Phantom canonicals (no wiki page): {len(phantom_canonicals)}",
        "",
        "## Top gainers (Stage 1 > current)",
    ]
    def _in(G, n):
        return G.in_degree(n) if G.has_node(n) else 0

    for n, d in gainers:
        lines.append(
            f"- [[{n}]] | current in-degree: {_in(G_current, n)} "
            f"→ Stage 1: {_in(G_stage1, n)} | +{d}"
        )
    if not gainers:
        lines.append("- (none)")

    lines += ["", "## Top losers (current > Stage 1)"]
    for n, d in sorted(losers, key=lambda x: x[1]):
        lines.append(
            f"- [[{n}]] | current in-degree: {_in(G_current, n)} "
            f"→ Stage 1: {_in(G_stage1, n)} | {d}"
        )
    if not losers:
        lines.append("- (none)")

    lines += ["", "## Orphan entities (in-degree = 0 in Stage 1 graph)"]
    for n in orphans[:top_n]:
        lines.append(f"- [[{n}]] — never touched by any source in Stage 1")
    if not orphans:
        lines.append("- (none)")

    lines += ["", "## Phantoms (Stage 1 found, no wiki page)"]
    for n in sorted(phantom_canonicals)[:top_n]:
        lines.append(f"- \"{n}\" — no wiki page; candidate for stub")
    if not phantom_canonicals:
        lines.append("- (none)")

    lines += ["", "## Per-source delta (bottom 20 by match rate)"]
    lines.append("| Source | Current touches | Stage 1 hits | Match rate |")
    lines.append("|---|---|---|---|")
    per_source = []
    for src in sources:
        cur_set = {v for _, v in G_current.out_edges(src)} if G_current.has_node(src) else set()
        s1_set = {v for _, v in G_stage1.out_edges(src)} if G_stage1.has_node(src) else set()
        cur = len(cur_set)
        s1 = len(s1_set)
        rate = len(cur_set & s1_set) / cur if cur else 1.0
        per_source.append((src, cur, s1, rate))
    per_source.sort(key=lambda x: x[3])
    for src, cur, s1, rate in per_source[:top_n]:
        lines.append(f"| {src} | {cur} | {s1} | {rate:.0%} |")

    return "\n".join(lines) + "\n"
