"""Parse wiki/sources/*.md touches: frontmatter into a networkx DiGraph.

Mirrors `.tools/entity_linker/graph.py:build_current_graph` but exposes a
cleaner per-source dict for the comparison framework's needs.
"""
from __future__ import annotations

import re
from pathlib import Path

import networkx as nx


def _load_frontmatter():
    import importlib.util, sys
    from pathlib import Path
    if "frontmatter" in sys.modules:
        return sys.modules["frontmatter"]
    src = Path(__file__).resolve().parents[1] / "frontmatter.py"
    spec = importlib.util.spec_from_file_location("frontmatter", src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["frontmatter"] = mod
    spec.loader.exec_module(mod)
    return mod


frontmatter = _load_frontmatter()


_WIKILINK_RE = re.compile(r"^\[\[(.+?)(\|.+?)?\]\]$")


def _strip_wikilink(s: str) -> str:
    """'[[Tesla|alias]]' → 'Tesla'. Bare 'Tesla' passes through."""
    m = _WIKILINK_RE.match(s.strip())
    return m.group(1) if m else s.strip()


def _parse_touches(source_page: Path) -> list[str]:
    fm = frontmatter.parse_file(source_page).metadata
    if not fm:
        return []
    raw = fm.get("touches") or []
    if isinstance(raw, str):
        raw = [raw]
    return [_strip_wikilink(str(t)) for t in raw if t]


def load_touches_graph(sources_dir: Path) -> nx.DiGraph:
    """Build a DiGraph with source_stem → entity edges from wiki/sources/*.md touches:."""
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


def per_source_truth(sources_dir: Path) -> dict[str, set[str]]:
    """Return {source_stem: {entity_canonical, ...}} — convenient for precision/recall."""
    out: dict[str, set[str]] = {}
    if not sources_dir.exists():
        return out
    for page in sorted(sources_dir.glob("*.md")):
        out[page.stem] = set(_parse_touches(page))
    return out
