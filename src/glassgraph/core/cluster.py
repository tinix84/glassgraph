"""Deterministic theme-candidate detection via entity co-occurrence.

Two entities co-occur when they appear together in the same source page's
`touches:`. A candidate cluster is a connected group of entities whose pairwise
links each rest on >= min_sources shared sources. Clusters already covered by an
existing theme (>= `coverage` fraction of their evidence sources cited by one
theme) are dropped. Pure measurement: no LLM, no writes. Uses shared touches parsing.
"""
from __future__ import annotations

import math
from datetime import date
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path


from glassgraph.config import ConfigError, ENTITY_TYPES, VaultConfig
from glassgraph.core import frontmatter
from glassgraph.core.source_metadata import parse_touches, string_entries


@dataclass
class Candidate:
    entities: list[str]
    sources: list[str]
    pair_strength: int
    source_count: int = field(init=False)

    def __post_init__(self):
        self.source_count = len(self.sources)


def _per_source_entities(sources_dir: Path, config: VaultConfig | None = None) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    if config is None and not sources_dir.exists():
        return out
    pages = config.markdown_files(sources_dir) if config else sorted(sources_dir.glob("*.md"))
    for page in pages:
        if ".archive" in page.parts:
            continue
        ents = {e for e in parse_touches(page, strict=config is not None) if e}
        if len(ents) >= 2:
            out[page.stem] = ents
    return out


def _pair_source_map(sources_dir: Path, config: VaultConfig | None = None) -> dict[frozenset, set[str]]:
    pair_sources: dict[frozenset, set[str]] = {}
    for stem, ents in _per_source_entities(sources_dir, config).items():
        for a, b in combinations(sorted(ents), 2):
            pair_sources.setdefault(frozenset({a, b}), set()).add(stem)
    return pair_sources


def cooccurrence(sources_dir: Path, *, config: VaultConfig | None = None) -> dict[frozenset, int]:
    """{frozenset({A, B}): number of sources citing both}."""
    return {pair: len(srcs) for pair, srcs in _pair_source_map(sources_dir, config).items()}


def candidate_groups(sources_dir: Path, min_sources: int = 5, *, config: VaultConfig | None = None) -> list[Candidate]:
    """Connected groups of entities linked by pairs with >= min_sources shared sources."""
    pair_sources = _pair_source_map(sources_dir, config)
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


def _theme_source_stems(themes_dir: Path, config: VaultConfig | None = None,
                        *, declared_only: bool = False) -> list[set[str]]:
    out: list[set[str]] = []
    if config is None and not themes_dir.exists():
        return out
    pages = config.markdown_files(themes_dir) if config else sorted(themes_dir.glob("*.md"))
    for page in pages:
        parsed = frontmatter.parse_file(page)
        if config and parsed.error:
            raise ConfigError("Read valid theme frontmatter before clustering")
        meta = parsed.metadata or {}
        if declared_only and meta.get("type") != "theme":
            continue
        srcs = string_entries(meta.get("sources"), strict=config is not None, field="sources")
        stems = {str(s)[:-3] if str(s).endswith(".md") else str(s) for s in srcs}
        out.append(stems)
    return out


def uncovered_candidates(wiki_root: Path, min_sources: int = 5,
                         coverage: float = 0.6, *, config: VaultConfig | None = None) -> list[Candidate]:
    cands = candidate_groups(wiki_root / "sources", min_sources=min_sources, config=config)
    if config is None:
        theme_srcs = _theme_source_stems(wiki_root / "themes")
    else:
        theme_srcs = []
        for directory in config.entity_dirs:
            builtin = ENTITY_TYPES.get(directory.casefold())
            if builtin is not None and builtin != "theme":
                continue
            theme_srcs.extend(_theme_source_stems(wiki_root / directory, config, declared_only=builtin is None))
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
                  date_str: str = "", top_n: int = 3, *, config: VaultConfig | None = None) -> str:
    cands = uncovered_candidates(wiki_root, min_sources=min_sources, coverage=coverage, config=config)
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


def preview(config: VaultConfig, *, min_sources: int = 5, coverage: float = 0.6,
            date_str: str | None = None) -> str:
    """Render a current configured report without writing derived state."""
    if not config.wiki.is_dir():
        raise ConfigError("Select an existing configured wiki directory")
    if min_sources < 1 or not math.isfinite(coverage) or not 0 <= coverage <= 1:
        raise ConfigError("Use a positive source threshold and finite coverage from 0 to 1")
    selected_date = date.today().isoformat() if date_str is None else date_str
    try:
        parsed_date = date.fromisoformat(selected_date)
    except (TypeError, ValueError):
        raise ConfigError("Use a valid YYYY-MM-DD report date") from None
    if parsed_date.isoformat() != selected_date:
        raise ConfigError("Use a valid YYYY-MM-DD report date")
    return render_report(config.wiki, min_sources, coverage, selected_date, config=config)
