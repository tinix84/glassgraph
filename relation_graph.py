"""Build + export the typed relation graph from source-page relations:."""
from __future__ import annotations

import importlib.util, json, re, sys
from pathlib import Path

import networkx as nx

_HERE = Path(__file__).resolve().parent


def _load(name):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


frontmatter = _load("frontmatter")
relations = _load("relations")
_LINK_RE = re.compile(r"^\[\[([^\[\]\|]+?)(?:\|[^\[\]]+)?\]\]$")


def _bare(v: str) -> str:
    m = _LINK_RE.match(str(v).strip())
    return m.group(1).strip() if m else str(v).strip()


def build_relation_graph(sources_dir: Path) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    for page in sorted(Path(sources_dir).glob("*.md")):
        meta = frontmatter.parse_file(page).metadata or {}
        for r in meta.get("relations") or []:
            if not isinstance(r, dict):
                continue
            s, p, o, by = _bare(r.get("s", "")), r.get("p"), _bare(r.get("o", "")), r.get("by")
            if not s or not o or p not in relations.PREDICATES:
                continue
            g.add_edge(s, o, key=p, predicate=p, by=by)
            if p in relations.SYMMETRIC:
                g.add_edge(o, s, key=p, predicate=p, by=by)
    return g


def export_json(g: nx.MultiDiGraph, out: Path) -> None:
    data = {
        "nodes": [{"id": n} for n in g.nodes()],
        "edges": [{"s": u, "o": v, "p": k, **d} for u, v, k, d in g.edges(keys=True, data=True)],
    }
    Path(out).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def export_graphml(g: nx.MultiDiGraph, out: Path) -> None:
    nx.write_graphml(g, str(out))
