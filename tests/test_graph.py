"""Tests for graph.py — DiGraph construction, match rate, orphans, phantoms."""
from __future__ import annotations

import textwrap
from pathlib import Path


def _make_source(tmp_path: Path, name: str, touches: list[str]) -> Path:
    """Create a minimal wiki/sources/*.md with touches: frontmatter."""
    sources = tmp_path / "wiki" / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    page = sources / name
    fm_touches = "\n".join(f"  - '[[{t}]]'" for t in touches)
    page.write_text(
        f"---\ntouches:\n{fm_touches}\n---\nBody text.\n",
        encoding="utf-8",
    )
    return page


def _make_entity(wiki_dir: Path, subdir: str, name: str):
    d = wiki_dir / subdir
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(f"---\ntype: company\n---\n{name} stub.\n", encoding="utf-8")


def test_strip_touches_wikilinks(graph_mod):
    raw = ["[[Tesla]]", "[[BYD]]", "[[SiC-MOSFET|SiC]]"]
    result = [graph_mod._strip_wikilink(t) for t in raw]
    assert result == ["Tesla", "BYD", "SiC-MOSFET"]


def test_build_current_graph_from_touches(tmp_path, graph_mod):
    wiki = tmp_path / "wiki"
    _make_source(tmp_path, "source_a.md", ["Tesla", "BYD"])
    _make_source(tmp_path, "source_b.md", ["Tesla"])
    G = graph_mod.build_current_graph(wiki / "sources")
    assert G.has_edge("source_a", "Tesla")
    assert G.has_edge("source_a", "BYD")
    assert G.has_edge("source_b", "Tesla")
    assert G.in_degree("Tesla") == 2
    assert G.in_degree("BYD") == 1


def test_build_stage1_graph_from_results(tmp_path, graph_mod, linker_mod):
    from dataclasses import dataclass, field

    results = {
        "source_a": ["Tesla", "BYD"],
        "source_b": ["Tesla"],
    }
    G = graph_mod.build_stage1_graph(results)
    assert G.in_degree("Tesla") == 2
    assert G.in_degree("BYD") == 1
    assert not G.has_node("source_c")


def test_match_rate_perfect(graph_mod):
    import networkx as nx
    G_c = nx.DiGraph()
    G_s = nx.DiGraph()
    for g in (G_c, G_s):
        g.add_edge("s1", "Tesla")
        g.add_edge("s1", "BYD")
    rate = graph_mod.compute_match_rate(G_c, G_s, sources=["s1"])
    assert rate == 1.0


def test_match_rate_partial(graph_mod):
    import networkx as nx
    G_c = nx.DiGraph()
    G_c.add_edge("s1", "Tesla")
    G_c.add_edge("s1", "BYD")
    G_s = nx.DiGraph()
    G_s.add_edge("s1", "Tesla")   # BYD missing from Stage 1
    rate = graph_mod.compute_match_rate(G_c, G_s, sources=["s1"])
    assert rate == 0.5


def test_match_rate_empty_source(graph_mod):
    import networkx as nx
    G_c = nx.DiGraph()  # source has no touches
    G_s = nx.DiGraph()
    rate = graph_mod.compute_match_rate(G_c, G_s, sources=["s1"])
    assert rate == 1.0  # vacuously true


def test_get_orphan_entities(graph_mod):
    import networkx as nx
    G = nx.DiGraph()
    G.add_edge("source_a", "Tesla")
    G.add_node("Lonely")  # no incoming edges
    orphans = graph_mod.get_orphan_entities(G, entity_nodes={"Tesla", "Lonely"})
    assert "Lonely" in orphans
    assert "Tesla" not in orphans


def test_get_phantoms(tmp_path, graph_mod):
    wiki = tmp_path / "wiki"
    _make_entity(wiki, "companies", "Tesla")
    # "Ghost" has no page in wiki
    phantoms = graph_mod.get_phantoms({"Tesla", "Ghost"}, wiki)
    assert "Ghost" in phantoms
    assert "Tesla" not in phantoms


def test_in_degree_delta(graph_mod):
    import networkx as nx
    G_c = nx.DiGraph()
    G_c.add_edge("s1", "Tesla")
    G_s = nx.DiGraph()
    G_s.add_edge("s1", "Tesla")
    G_s.add_edge("s2", "Tesla")  # Tesla gains 1
    delta = graph_mod.get_in_degree_delta(G_c, G_s, entity_nodes={"Tesla"})
    assert delta[0] == ("Tesla", 1)


def test_render_report_contains_sections(graph_mod):
    import networkx as nx
    G_c = nx.DiGraph()
    G_s = nx.DiGraph()
    G_c.add_edge("s1", "Tesla")
    G_s.add_edge("s1", "Tesla")
    report = graph_mod.render_report(
        sources=["s1"],
        G_current=G_c,
        G_stage1=G_s,
        entity_nodes={"Tesla"},
        wiki_dir=None,
        phantom_canonicals=set(),
        date_str="2026-05-20",
    )
    assert "# Backfill Audit" in report
    assert "Match rate" in report
    assert "Orphan entities" in report
