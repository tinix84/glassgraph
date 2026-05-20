"""Tests for history.py — JSONL append + delta computation."""
from __future__ import annotations

import json
from pathlib import Path


def test_append_run_creates_file(tmp_path, history_mod):
    p = tmp_path / "history.jsonl"
    entry = {
        "ts": "2026-05-20T10:00:00Z",
        "match_rate": 0.5,
        "sources": 100,
        "orphans": 0,
        "phantoms": 0,
        "entity_in_degrees": {"Tesla": {"current": 10, "stage1": 8}},
    }
    history_mod.append_run(p, entry)
    lines = p.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 1
    assert json.loads(lines[0]) == entry


def test_append_run_appends_not_overwrites(tmp_path, history_mod):
    p = tmp_path / "history.jsonl"
    history_mod.append_run(p, {"ts": "1", "match_rate": 0.4})
    history_mod.append_run(p, {"ts": "2", "match_rate": 0.5})
    lines = p.read_text(encoding="utf-8").strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["ts"] == "1"
    assert json.loads(lines[1])["ts"] == "2"


def test_read_last_run_returns_most_recent(tmp_path, history_mod):
    p = tmp_path / "history.jsonl"
    history_mod.append_run(p, {"ts": "1"})
    history_mod.append_run(p, {"ts": "2"})
    history_mod.append_run(p, {"ts": "3"})
    last = history_mod.read_last_run(p)
    assert last["ts"] == "3"


def test_read_last_run_none_if_no_file(tmp_path, history_mod):
    p = tmp_path / "nonexistent.jsonl"
    assert history_mod.read_last_run(p) is None


def test_compute_delta_match_rate(history_mod):
    prev = {"match_rate": 0.4, "entity_in_degrees": {}}
    curr = {"match_rate": 0.5, "entity_in_degrees": {}}
    delta = history_mod.compute_delta(prev, curr, min_abs_delta=3)
    assert delta["match_rate_delta"] == 0.1


def test_compute_delta_top_movers_threshold(history_mod):
    prev = {"match_rate": 0.5, "entity_in_degrees": {
        "Big": {"current": 1, "stage1": 10},
        "Small": {"current": 1, "stage1": 2},
    }}
    curr = {"match_rate": 0.5, "entity_in_degrees": {
        "Big": {"current": 10, "stage1": 10},   # delta +9 in current
        "Small": {"current": 2, "stage1": 2},    # delta +1 in current
    }}
    delta = history_mod.compute_delta(prev, curr, min_abs_delta=3)
    movers = [m["canonical"] for m in delta["top_movers"]]
    assert "Big" in movers
    assert "Small" not in movers


def test_build_history_entry(history_mod):
    """build_history_entry() shapes a current/Stage 1 graph + summary into a JSONL entry."""
    import networkx as nx
    G_curr = nx.DiGraph(); G_curr.add_edge("s1", "Tesla"); G_curr.add_edge("s2", "Tesla")
    G_s1 = nx.DiGraph(); G_s1.add_edge("s1", "Tesla"); G_s1.add_edge("s2", "BYD")
    entry = history_mod.build_history_entry(
        ts="2026-05-20T10:00:00Z",
        match_rate=0.5, sources=["s1", "s2"], orphans=0, phantoms=0,
        G_current=G_curr, G_stage1=G_s1,
        entity_nodes={"Tesla", "BYD"}, top_n=10,
    )
    assert entry["ts"] == "2026-05-20T10:00:00Z"
    assert entry["match_rate"] == 0.5
    assert "Tesla" in entry["entity_in_degrees"]
    assert entry["entity_in_degrees"]["Tesla"]["current"] == 2
