"""Tests for load_ours.py — touches: → DiGraph."""
from __future__ import annotations

from pathlib import Path


def _make_source(tmp_path, name: str, touches: list[str]) -> Path:
    sources = tmp_path / "wiki" / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    page = sources / name
    fm_t = "\n".join(f"  - '[[{t}]]'" for t in touches)
    page.write_text(
        f"---\ntype: source\nsource_url: http://example.com\ntouches:\n{fm_t}\n---\nBody.\n",
        encoding="utf-8",
    )
    return page


def test_load_touches_basic(tmp_path, load_ours_mod):
    _make_source(tmp_path, "source_a.md", ["Tesla", "BYD"])
    _make_source(tmp_path, "source_b.md", ["Tesla"])
    G = load_ours_mod.load_touches_graph(tmp_path / "wiki" / "sources")
    assert G.has_edge("source_a", "Tesla")
    assert G.has_edge("source_a", "BYD")
    assert G.has_edge("source_b", "Tesla")
    assert G.in_degree("Tesla") == 2


def test_load_touches_strips_wikilink_brackets(tmp_path, load_ours_mod):
    _make_source(tmp_path, "src.md", ["Tesla|alias"])
    G = load_ours_mod.load_touches_graph(tmp_path / "wiki" / "sources")
    assert G.has_edge("src", "Tesla")


def test_load_touches_empty_sources_dir(tmp_path, load_ours_mod):
    (tmp_path / "wiki" / "sources").mkdir(parents=True)
    G = load_ours_mod.load_touches_graph(tmp_path / "wiki" / "sources")
    assert G.number_of_nodes() == 0


def test_per_source_truth(tmp_path, load_ours_mod):
    _make_source(tmp_path, "a.md", ["Tesla", "BYD"])
    _make_source(tmp_path, "b.md", ["Huawei"])
    truth = load_ours_mod.per_source_truth(tmp_path / "wiki" / "sources")
    assert truth == {"a": {"Tesla", "BYD"}, "b": {"Huawei"}}
