"""Tests for explain.py — span-level Stage 1 debugging output."""
from __future__ import annotations

import textwrap
from pathlib import Path


def test_format_hit_basic(explain_mod):
    body = "Tesla released a new SiC MOSFET inverter in 2024."
    line = explain_mod.format_hit(body, start=0, end=4, canonical="Tesla", alias="Tesla", context_chars=10)
    assert "[0:" in line
    assert "Tesla" in line
    assert "→ Tesla" in line


def test_format_hit_context_includes_surrounding_chars(explain_mod):
    body = "The Tesla 3D1 SiC inverter was teardown by Munro."
    line = explain_mod.format_hit(body, start=4, end=8, canonical="Tesla", alias="Tesla", context_chars=10)
    assert "The Tesla" in line  # context shows preceding chars


def test_explain_file_runs_full_pipeline(wiki_dir, tmp_path, explain_mod, index_mod):
    raw = tmp_path / "raw.md"
    raw.write_text("---\nsource_url: x\n---\nTesla unveils SiC MOSFET inverter.\n", encoding="utf-8")
    automaton = index_mod.build_index(wiki_dir, tmp_path / "m.json", tmp_path / "a.json")
    output = explain_mod.explain_file(raw, automaton, filter_canonical=None, show_suppressed=False, context_chars=20)
    assert "Tesla" in output
    assert "SiC MOSFET" in output


def test_explain_filter_canonical(wiki_dir, tmp_path, explain_mod, index_mod):
    raw = tmp_path / "raw.md"
    raw.write_text("---\nsource_url: x\n---\nTesla and BYD made announcements.\n", encoding="utf-8")
    automaton = index_mod.build_index(wiki_dir, tmp_path / "m.json", tmp_path / "a.json")
    output = explain_mod.explain_file(raw, automaton, filter_canonical="Tesla", show_suppressed=False, context_chars=10)
    # Tesla hit should be present
    assert "→ Tesla" in output
    # BYD hit should NOT be present (filtered out) — but BYD may appear in Tesla's context window
    assert "→ BYD" not in output


def test_explain_show_suppressed(wiki_dir, tmp_path, explain_mod, index_mod, disambiguation_yaml):
    raw = tmp_path / "raw.md"
    raw.write_text("---\nsource_url: x\n---\nTesla coil and Tesla cars.\n", encoding="utf-8")
    automaton = index_mod.build_index(wiki_dir, tmp_path / "m.json", tmp_path / "a.json")
    out_with = explain_mod.explain_file(raw, automaton, filter_canonical=None, show_suppressed=True, context_chars=20, disambiguation_yaml=disambiguation_yaml)
    assert "SUPPRESSED" in out_with or "suppressed" in out_with.lower()


def test_explain_summary_includes_counts(wiki_dir, tmp_path, explain_mod, index_mod):
    raw = tmp_path / "raw.md"
    raw.write_text("---\nsource_url: x\n---\nTesla Tesla BYD\n", encoding="utf-8")
    automaton = index_mod.build_index(wiki_dir, tmp_path / "m.json", tmp_path / "a.json")
    output = explain_mod.explain_file(raw, automaton, filter_canonical=None, show_suppressed=False, context_chars=10)
    assert "hits" in output.lower() or "Summary" in output
