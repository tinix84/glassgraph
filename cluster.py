"""Deterministic theme-candidate detection via entity co-occurrence.

Two entities co-occur when they appear together in the same source page's
`touches:`. A candidate cluster is a connected group of entities whose pairwise
links each rest on >= min_sources shared sources. Clusters already covered by an
existing theme (>= `coverage` fraction of their evidence sources cited by one
theme) are dropped. Pure measurement: no LLM, no writes. Reuses graph.py parsing.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path


def _load_sibling(name: str):
    if name in sys.modules:
        return sys.modules[name]
    src = Path(__file__).resolve().parent / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


graph = _load_sibling("graph")
frontmatter = _load_sibling("frontmatter")


@dataclass
class Candidate:
    entities: list[str]
    sources: list[str]
    pair_strength: int
    source_count: int = field(init=False)

    def __post_init__(self):
        self.source_count = len(self.sources)


def _per_source_entities(sources_dir: Path) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    if not sources_dir.exists():
        return out
    for page in sorted(sources_dir.glob("*.md")):
        if ".archive" in page.parts:
            continue
        ents = {e for e in graph._parse_touches(page) if e}
        if len(ents) >= 2:
            out[page.stem] = ents
    return out


def _pair_source_map(sources_dir: Path) -> dict[frozenset, set[str]]:
    pair_sources: dict[frozenset, set[str]] = {}
    for stem, ents in _per_source_entities(sources_dir).items():
        for a, b in combinations(sorted(ents), 2):
            pair_sources.setdefault(frozenset({a, b}), set()).add(stem)
    return pair_sources


def cooccurrence(sources_dir: Path) -> dict[frozenset, int]:
    """{frozenset({A, B}): number of sources citing both}."""
    return {pair: len(srcs) for pair, srcs in _pair_source_map(sources_dir).items()}


def candidate_groups(sources_dir: Path, min_sources: int = 5) -> list[Candidate]:
    """Connected groups of entities linked by pairs with >= min_sources shared sources."""
    pair_sources = _pair_source_map(sources_dir)
    strong = {pair: srcs for pair, srcs in pair_sources.items() if len(srcs) >= min_sources}

    parent: dict[str, str] = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(x, y):
        parent[find(x)] = find(y)

    for pair in strong:
        a, b = tuple(pair)
        union(a, b)

    groups: dict[str, set[str]] = {}
    for pair in strong:
        for e in pair:
            groups.setdefault(find(e), set()).add(e)

    out: list[Candidate] = []
    for members in groups.values():
        srcs: set[str] = set()
        strength = 0
        for pair, s in strong.items():
            if pair <= members:
                srcs |= s
                strength += len(s)
        out.append(Candidate(entities=sorted(members), sources=sorted(srcs),
                              pair_strength=strength))
    out.sort(key=lambda c: -c.pair_strength)
    return out


def _theme_source_stems(themes_dir: Path) -> list[set[str]]:
    out: list[set[str]] = []
    if not themes_dir.exists():
        return out
    for page in sorted(themes_dir.glob("*.md")):
        meta = frontmatter.parse_file(page).metadata or {}
        srcs = meta.get("sources") or []
        if isinstance(srcs, str):
            srcs = [srcs]
        stems = {str(s)[:-3] if str(s).endswith(".md") else str(s) for s in srcs}
        out.append(stems)
    return out


def uncovered_candidates(wiki_root: Path, min_sources: int = 5,
                         coverage: float = 0.6) -> list[Candidate]:
    cands = candidate_groups(wiki_root / "sources", min_sources=min_sources)
    theme_srcs = _theme_source_stems(wiki_root / "themes")
    out = []
    for c in cands:
        cset = set(c.sources)
        covered = any(
            len(cset & tsrc) / len(cset) >= coverage
            for tsrc in theme_srcs if cset
        )
        if not covered:
            out.append(c)
    return out


def render_report(wiki_root: Path, min_sources: int = 5, coverage: float = 0.6,
                  date_str: str = "", top_n: int = 3) -> str:
    cands = uncovered_candidates(wiki_root, min_sources=min_sources, coverage=coverage)
    lines = [
        f"# Theme Cluster Report — {date_str}",
        "",
        f"Co-occurrence threshold: >= {min_sources} shared sources. "
        f"Coverage filter: dropped clusters >= {coverage:.0%} cited by an existing theme.",
        f"Uncovered candidate clusters: {len(cands)}",
        "",
    ]
    for i, c in enumerate(cands, 1):
        marker = "  <-- TOP CANDIDATE (draft a thesis)" if i <= top_n else ""
        lines.append(f"## Candidate {i}{marker}")
        lines.append(f"- Entities: {', '.join('[[' + e + ']]' for e in c.entities)}")
        lines.append(f"- Co-citation strength: {c.pair_strength} | evidence sources: {c.source_count}")
        lines.append(f"- Evidence: {', '.join('[[' + s + '.md]]' for s in c.sources[:12])}"
                     + (" …" if c.source_count > 12 else ""))
        lines.append("")
    if not cands:
        lines.append("(No uncovered candidate clusters — theme layer is current.)")
    return "\n".join(lines) + "\n"
