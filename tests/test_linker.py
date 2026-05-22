"""Tests for linker.py — extraction, dedup, CJK, disambiguation, result types."""
from __future__ import annotations

import textwrap
from pathlib import Path


# ── strip_fenced ──────────────────────────────────────────────────────────────

def test_strip_fenced_removes_triple_backtick_block(linker_mod):
    lines = ["before", "```", "Tesla BYD", "```", "after"]
    assert list(linker_mod.strip_fenced(lines)) == ["before", "after"]


def test_strip_fenced_removes_tilde_fence(linker_mod):
    lines = ["x", "~~~", "hidden", "~~~", "y"]
    assert list(linker_mod.strip_fenced(lines)) == ["x", "y"]


def test_strip_fenced_keeps_content_outside_fences(linker_mod):
    lines = ["Tesla", "```python", "x = 1", "```", "BYD"]
    result = list(linker_mod.strip_fenced(lines))
    assert "Tesla" in result and "BYD" in result


def test_strip_fenced_ignores_nested_shorter_fence(linker_mod):
    lines = ["````", "```", "still inside", "```", "````", "outside"]
    result = list(linker_mod.strip_fenced(lines))
    assert result == ["outside"]


# ── _strip_frontmatter ────────────────────────────────────────────────────────

def test_strip_frontmatter_removes_yaml(linker_mod):
    text = "---\naliases: [Tesla]\n---\nBody text here"
    result = linker_mod._strip_frontmatter(text)
    assert "Body text here" in result
    assert "aliases:" not in result


def test_strip_frontmatter_noop_when_no_frontmatter(linker_mod):
    text = "No frontmatter at all."
    assert linker_mod._strip_frontmatter(text) == text


# ── extract ───────────────────────────────────────────────────────────────────

def test_extract_finds_en_entity(wiki_dir, tmp_path, linker_mod, index_mod):
    automaton = index_mod.build_index(wiki_dir, tmp_path / "m.json", tmp_path / "a.json")
    hits, _ = linker_mod.extract("Tesla unveiled new tech.", automaton)
    assert any(h[2] == "Tesla" for h in hits)


def test_extract_finds_cn_entity(wiki_dir, tmp_path, linker_mod, index_mod):
    automaton = index_mod.build_index(wiki_dir, tmp_path / "m.json", tmp_path / "a.json")
    hits, _ = linker_mod.extract("比亚迪发布新产品。", automaton)
    assert any(h[2] == "BYD" for h in hits)


def test_extract_returns_canonical_alias_start_end(wiki_dir, tmp_path, linker_mod, index_mod):
    automaton = index_mod.build_index(wiki_dir, tmp_path / "m.json", tmp_path / "a.json")
    body = "Tesla is here"
    hits, _ = linker_mod.extract(body, automaton)
    tesla_hits = [h for h in hits if h[2] == "Tesla"]
    assert len(tesla_hits) == 1
    start, end, canonical, alias = tesla_hits[0]
    assert body[start:end + 1] == "Tesla"
    assert canonical == "Tesla"
    assert alias == "Tesla"


def test_extract_longest_match_wins(wiki_dir, tmp_path, linker_mod, index_mod):
    """'SiC MOSFET' beats 'SiC' at the same position."""
    automaton = index_mod.build_index(wiki_dir, tmp_path / "m.json", tmp_path / "a.json")
    body = "Using SiC MOSFET in the circuit."
    hits, _ = linker_mod.extract(body, automaton)
    aliases = [h[3] for h in hits]
    assert "SiC MOSFET" in aliases
    assert "SiC" not in aliases  # consumed by greedy sweep


def test_extract_cn_longest_match_wins(wiki_dir, tmp_path, linker_mod, index_mod):
    """'碳化硅MOSFET' beats '碳化硅' at the same position."""
    automaton = index_mod.build_index(wiki_dir, tmp_path / "m.json", tmp_path / "a.json")
    body = "使用碳化硅MOSFET设计逆变器"
    hits, _ = linker_mod.extract(body, automaton)
    aliases = [h[3] for h in hits]
    assert "碳化硅MOSFET" in aliases
    assert "碳化硅" not in aliases


def test_extract_no_match_inside_word(wiki_dir, tmp_path, linker_mod, index_mod):
    """'SiC' should not fire inside 'nSiCp' (no word boundary)."""
    automaton = index_mod.build_index(wiki_dir, tmp_path / "m.json", tmp_path / "a.json")
    hits, _ = linker_mod.extract("nSiCp is not a match.", automaton)
    assert not any(h[2] == "SiC-MOSFET" for h in hits)


def test_extract_no_match_in_fenced_code(wiki_dir, tmp_path, linker_mod, index_mod):
    automaton = index_mod.build_index(wiki_dir, tmp_path / "m.json", tmp_path / "a.json")
    lines = ["before", "```", "Tesla BYD SiC MOSFET", "```", "after"]
    body = "\n".join(linker_mod.strip_fenced(lines))
    hits, _ = linker_mod.extract(body, automaton)
    assert all(h[2] not in ("Tesla", "BYD", "SiC-MOSFET") for h in hits)


def test_extract_disambiguation_suppresses_span(wiki_dir, tmp_path, linker_mod, index_mod):
    automaton = index_mod.build_index(wiki_dir, tmp_path / "m.json", tmp_path / "a.json")
    body = "The Tesla coil was invented before Tesla cars."
    hits, warnings = linker_mod.extract(body, automaton, disambiguation_patterns=["tesla coil"])
    # "Tesla coil" span suppressed; second "Tesla" (standalone) may still fire
    assert any("Suppressed" in w for w in warnings)


def test_extract_empty_body_returns_empty(wiki_dir, tmp_path, linker_mod, index_mod):
    automaton = index_mod.build_index(wiki_dir, tmp_path / "m.json", tmp_path / "a.json")
    hits, warnings = linker_mod.extract("", automaton)
    assert hits == [] and warnings == []


# ── ExtractionResult / build_result ──────────────────────────────────────────

def test_build_result_groups_hits_by_canonical(wiki_dir, tmp_path, linker_mod, index_mod, sample_body):
    automaton = index_mod.build_index(wiki_dir, tmp_path / "m.json", tmp_path / "a.json")
    hits, warnings = linker_mod.extract(sample_body, automaton)
    result = linker_mod.build_result("raw/test.md", "sha_abc", hits, warnings)
    canonicals = [e.canonical for e in result.entities]
    assert "Tesla" in canonicals
    assert "BYD" in canonicals
    # No duplicate canonical entries
    assert len(canonicals) == len(set(canonicals))


def test_build_result_count_reflects_occurrences(wiki_dir, tmp_path, linker_mod, index_mod):
    automaton = index_mod.build_index(wiki_dir, tmp_path / "m.json", tmp_path / "a.json")
    body = "Tesla Tesla Tesla"  # 3 occurrences
    hits, warnings = linker_mod.extract(body, automaton)
    result = linker_mod.build_result("raw/test.md", "sha", hits, warnings)
    tesla = next(e for e in result.entities if e.canonical == "Tesla")
    assert tesla.count == 3


def test_build_result_confidence_is_dict(wiki_dir, tmp_path, linker_mod, index_mod, sample_body):
    automaton = index_mod.build_index(wiki_dir, tmp_path / "m.json", tmp_path / "a.json")
    hits, warnings = linker_mod.extract(sample_body, automaton)
    result = linker_mod.build_result("raw/test.md", "sha", hits, warnings)
    assert all(e.confidence == "dict" for e in result.entities)


# ── VectorHit + ExtractionResult.vector_entities ────────────────────────────

def test_vector_hit_has_required_fields(linker_mod):
    h = linker_mod.VectorHit(canonical="Tesla", cosine=0.85, rank=1)
    assert h.canonical == "Tesla"
    assert h.cosine == 0.85
    assert h.rank == 1
    assert h.confidence == "vector"


def test_extraction_result_vector_entities_defaults_none(linker_mod, wiki_dir, tmp_path, index_mod):
    automaton = index_mod.build_index(wiki_dir, tmp_path / "m.json", tmp_path / "a.json")
    body = "Tesla and BYD."
    hits, warnings = linker_mod.extract(body, automaton)
    result = linker_mod.build_result("raw/X.md", "sha", hits, warnings)
    assert result.vector_entities is None
    assert result.vector_manifest_sha is None


def test_extraction_result_can_carry_vector_entities(linker_mod, wiki_dir, tmp_path, index_mod):
    automaton = index_mod.build_index(wiki_dir, tmp_path / "m.json", tmp_path / "a.json")
    hits, warnings = linker_mod.extract("Tesla", automaton)
    result = linker_mod.build_result("raw/X.md", "sha", hits, warnings)
    # Attach Stage 2 results manually (Task 3 will wire this via link.py)
    result.vector_entities = [linker_mod.VectorHit(canonical="Tesla", cosine=0.9, rank=1)]
    result.vector_manifest_sha = "vector_sha"
    assert result.vector_entities[0].canonical == "Tesla"
    assert result.vector_manifest_sha == "vector_sha"
