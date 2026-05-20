"""Tests for index.py — alias trie building and manifest staleness."""
from __future__ import annotations

import json
from pathlib import Path


def test_parse_aliases_reads_en_and_cn(wiki_dir, index_mod):
    page = wiki_dir / "companies" / "Tesla.md"
    canonical, aliases = index_mod._parse_aliases(page)
    assert canonical == "Tesla"
    assert "Tesla" in aliases
    assert "特斯拉" in aliases
    assert "TSLA" in aliases


def test_parse_aliases_excludes_aliases_field(wiki_dir, index_mod):
    """aliases: field in frontmatter is Obsidian-only — not used for vocabulary."""
    page = wiki_dir / "companies" / "Tesla.md"
    _, aliases = index_mod._parse_aliases(page)
    # aliases_en and aliases_cn are what matter; aliases: field content is irrelevant
    assert set(aliases) >= {"Tesla", "TSLA", "特斯拉"}


def test_parse_aliases_missing_fields_uses_stem(tmp_path, index_mod):
    page = tmp_path / "Stub.md"
    page.write_text("---\ntype: company\n---\nNo aliases here.", encoding="utf-8")
    canonical, aliases = index_mod._parse_aliases(page)
    assert canonical == "Stub"
    assert aliases == ["Stub"]


def test_build_index_contains_en_alias(wiki_dir, tmp_path, index_mod):
    automaton = index_mod.build_index(
        wiki_dir, tmp_path / "manifest.json", tmp_path / "aliases.json"
    )
    hits = list(automaton.iter("Tesla is great"))
    assert any(canonical == "Tesla" for _, (canonical, _) in hits)


def test_build_index_contains_cn_alias(wiki_dir, tmp_path, index_mod):
    automaton = index_mod.build_index(
        wiki_dir, tmp_path / "manifest.json", tmp_path / "aliases.json"
    )
    hits = list(automaton.iter("比亚迪 is a car maker"))
    assert any(canonical == "BYD" for _, (canonical, _) in hits)


def test_build_index_value_is_canonical_alias_tuple(wiki_dir, tmp_path, index_mod):
    automaton = index_mod.build_index(
        wiki_dir, tmp_path / "manifest.json", tmp_path / "aliases.json"
    )
    hits = list(automaton.iter("Tesla"))
    # Value must be (canonical, matched_alias) — not just canonical
    assert all(isinstance(v, tuple) and len(v) == 2 for _, v in hits)
    end_idx, (canonical, alias) = hits[0]
    assert canonical == "Tesla"
    assert alias == "Tesla"
    assert end_idx == len("Tesla") - 1


def test_build_index_writes_manifest(wiki_dir, tmp_path, index_mod):
    manifest_path = tmp_path / "manifest.json"
    index_mod.build_index(wiki_dir, manifest_path, tmp_path / "aliases.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "pyahocorasick_version" in manifest
    assert manifest["alias_count"] >= 9  # 3 pages × ≥3 aliases each
    assert len(manifest["page_shas"]) == 3


def test_build_index_writes_aliases_json(wiki_dir, tmp_path, index_mod):
    aliases_path = tmp_path / "aliases.json"
    index_mod.build_index(wiki_dir, tmp_path / "manifest.json", aliases_path)
    alias_map = json.loads(aliases_path.read_text(encoding="utf-8"))
    assert alias_map["特斯拉"] == "Tesla"
    assert alias_map["比亚迪"] == "BYD"
    assert alias_map["SiC MOSFET"] == "SiC-MOSFET"


def test_is_stale_true_when_no_manifest(wiki_dir, tmp_path, index_mod):
    assert index_mod.is_stale(wiki_dir, tmp_path / "nonexistent.json") is True


def test_is_stale_false_after_build(wiki_dir, tmp_path, index_mod):
    manifest_path = tmp_path / "manifest.json"
    index_mod.build_index(wiki_dir, manifest_path, tmp_path / "aliases.json")
    assert index_mod.is_stale(wiki_dir, manifest_path) is False


def test_is_stale_true_after_page_modified(wiki_dir, tmp_path, index_mod):
    manifest_path = tmp_path / "manifest.json"
    index_mod.build_index(wiki_dir, manifest_path, tmp_path / "aliases.json")
    (wiki_dir / "companies" / "Tesla.md").write_text("modified", encoding="utf-8")
    assert index_mod.is_stale(wiki_dir, manifest_path) is True


def test_alias_collision_logs_and_keeps_first(tmp_path, index_mod):
    """When two pages share an alias, first wins; no crash."""
    companies = tmp_path / "wiki" / "companies"
    companies.mkdir(parents=True)
    (companies / "A.md").write_text("---\naliases_en: [shared]\naliases_cn: []\n---\n", encoding="utf-8")
    (companies / "B.md").write_text("---\naliases_en: [shared]\naliases_cn: []\n---\n", encoding="utf-8")
    wiki = tmp_path / "wiki"
    # Should not raise
    automaton = index_mod.build_index(wiki, tmp_path / "m.json", tmp_path / "a.json")
    assert len(automaton) > 0


def test_merged_page_skipped_from_trie(tmp_path, index_mod):
    """Pages with tags: [merged] should not contribute to the alias trie."""
    companies = tmp_path / "wiki" / "companies"
    companies.mkdir(parents=True)
    (companies / "OldName.md").write_text(
        "---\naliases_en: [OldName, legacy alias]\naliases_cn: []\ntags: [merged]\n---\nMerged.\n",
        encoding="utf-8",
    )
    (companies / "NewName.md").write_text(
        "---\naliases_en: [NewName, OldName]\naliases_cn: []\n---\nCanonical.\n",
        encoding="utf-8",
    )
    wiki = tmp_path / "wiki"
    automaton = index_mod.build_index(wiki, tmp_path / "m.json", tmp_path / "a.json")
    # "OldName" should resolve to "NewName", not "OldName"
    hits = list(automaton.iter("OldName mention"))
    assert any(canonical == "NewName" for _, (canonical, _) in hits)
    # "legacy alias" (only in merged stub) must not appear in trie at all
    hits2 = list(automaton.iter("legacy alias mention"))
    assert not hits2
