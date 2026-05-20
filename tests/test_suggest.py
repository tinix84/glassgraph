"""Tests for suggest.py — TF-IDF-style alias candidate proposal."""
from __future__ import annotations

import json
from pathlib import Path


def test_extract_candidates_english(suggest_mod):
    body = "Megawatt Charging System leverages Tesla Cybertruck wiring."
    cands = suggest_mod.extract_candidates(body)
    assert "Megawatt Charging System" in cands or "Megawatt Charging" in cands
    assert "Tesla Cybertruck" in cands


def test_extract_candidates_cjk(suggest_mod):
    body = "比亚迪超充技术领先，宁德时代电池应用广泛。"
    cands = suggest_mod.extract_candidates(body)
    assert any("比亚迪" in c for c in cands)
    assert any("宁德时代" in c for c in cands)


def test_compute_df_index(tmp_path, suggest_mod):
    sources = tmp_path / "wiki" / "sources"
    sources.mkdir(parents=True)
    (sources / "A.md").write_text("---\n---\nTesla appears here.", encoding="utf-8")
    (sources / "B.md").write_text("---\n---\nTesla and BYD appear here.", encoding="utf-8")
    (sources / "C.md").write_text("---\n---\nOnly BYD here.", encoding="utf-8")
    df = suggest_mod.compute_df_index(sources)
    assert df.get("Tesla") == 2
    assert df.get("BYD") == 2


def test_score_filters_known_aliases(suggest_mod):
    body = "Tesla and NovelTerm both appear. Tesla appears twice."
    known_aliases = {"Tesla", "TSLA"}
    df = {"Tesla": 10, "NovelTerm": 0}
    ranked = suggest_mod.rank_candidates(body, known_aliases=known_aliases, df=df, top_n=10)
    canonicals = [c["token"] for c in ranked]
    assert "Tesla" not in canonicals
    assert "NovelTerm" in canonicals


def test_score_formula(suggest_mod):
    body = "Alpha Alpha Alpha Beta"
    df = {"Alpha": 1, "Beta": 100}
    ranked = suggest_mod.rank_candidates(body, known_aliases=set(), df=df, top_n=10)
    alpha = next(c for c in ranked if c["token"] == "Alpha")
    beta = next(c for c in ranked if c["token"] == "Beta")
    assert alpha["score"] > beta["score"]
