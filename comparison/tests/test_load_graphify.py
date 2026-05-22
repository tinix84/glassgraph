"""Tests for load_graphify.py — graph.json → DiGraph with confidence stratification."""
from __future__ import annotations

import json
from pathlib import Path


def _make_graph_json(tmp_path: Path, nodes: list[dict], edges: list[dict]) -> Path:
    out = tmp_path / "graph.json"
    out.write_text(json.dumps({"nodes": nodes, "edges": edges}), encoding="utf-8")
    return out


def test_load_well_formed(tmp_path, load_graphify_mod):
    path = _make_graph_json(
        tmp_path,
        nodes=[
            {"id": "src_001", "type": "source", "label": "raw/A.md"},
            {"id": "ent_001", "type": "entity", "label": "Tesla", "confidence": "EXTRACTED"},
            {"id": "ent_002", "type": "entity", "label": "BYD", "confidence": "INFERRED"},
        ],
        edges=[
            {"source": "src_001", "target": "ent_001", "type": "mentions"},
            {"source": "src_001", "target": "ent_002", "type": "mentions"},
        ],
    )
    G, info = load_graphify_mod.load_graphify_graph(path)
    assert G.has_edge("A", "Tesla")
    assert G.has_edge("A", "BYD")
    assert info["nodes_parsed"] == 3
    assert info["edges_parsed"] == 2


def test_filter_to_extracted_only(tmp_path, load_graphify_mod):
    path = _make_graph_json(
        tmp_path,
        nodes=[
            {"id": "src_001", "type": "source", "label": "raw/A.md"},
            {"id": "ent_001", "type": "entity", "label": "Tesla", "confidence": "EXTRACTED"},
            {"id": "ent_002", "type": "entity", "label": "BYD", "confidence": "INFERRED"},
        ],
        edges=[
            {"source": "src_001", "target": "ent_001", "type": "mentions"},
            {"source": "src_001", "target": "ent_002", "type": "mentions"},
        ],
    )
    G, info = load_graphify_mod.load_graphify_graph(path, only_extracted=True)
    assert G.has_edge("A", "Tesla")
    assert not G.has_edge("A", "BYD")  # filtered out (INFERRED)


def test_skips_missing_fields(tmp_path, load_graphify_mod):
    """Nodes missing 'type' or 'label' are skipped (logged), don't crash."""
    path = _make_graph_json(
        tmp_path,
        nodes=[
            {"id": "src_001", "type": "source", "label": "raw/A.md"},
            {"id": "bad_001"},  # missing type + label
            {"id": "ent_001", "type": "entity", "label": "Tesla"},
        ],
        edges=[
            {"source": "src_001", "target": "ent_001"},
            {"source": "src_001", "target": "bad_001"},  # references skipped node
        ],
    )
    G, info = load_graphify_mod.load_graphify_graph(path)
    assert G.has_edge("A", "Tesla")
    assert info["nodes_skipped"] == 1
    assert info["edges_skipped"] >= 1


def test_source_id_to_filename_mapping(tmp_path, load_graphify_mod):
    """Source nodes use filename-derived stems as graph node IDs."""
    path = _make_graph_json(
        tmp_path,
        nodes=[
            {"id": "src_001", "type": "source", "label": "拆解Tesla.md"},
            {"id": "ent_001", "type": "entity", "label": "Tesla"},
        ],
        edges=[{"source": "src_001", "target": "ent_001"}],
    )
    G, info = load_graphify_mod.load_graphify_graph(path)
    assert G.has_edge("拆解Tesla", "Tesla")


def test_per_source_extracted(tmp_path, load_graphify_mod):
    path = _make_graph_json(
        tmp_path,
        nodes=[
            {"id": "src_001", "type": "source", "label": "A.md"},
            {"id": "src_002", "type": "source", "label": "B.md"},
            {"id": "e1", "type": "entity", "label": "Tesla", "confidence": "EXTRACTED"},
            {"id": "e2", "type": "entity", "label": "BYD", "confidence": "INFERRED"},
        ],
        edges=[
            {"source": "src_001", "target": "e1"},
            {"source": "src_001", "target": "e2"},
            {"source": "src_002", "target": "e1"},
        ],
    )
    G, info = load_graphify_mod.load_graphify_graph(path)
    per_source = load_graphify_mod.per_source_extracted(G)
    assert per_source == {"A": {"Tesla", "BYD"}, "B": {"Tesla"}}


def test_missing_file_returns_empty(tmp_path, load_graphify_mod):
    G, info = load_graphify_mod.load_graphify_graph(tmp_path / "nonexistent.json")
    assert G.number_of_nodes() == 0
    assert info.get("error") is not None
