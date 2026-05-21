"""Tests for stage2.py — BGE-M3 vector retrieval.

Three layers:
  Layer 1: pure logic (no model load)
  Layer 2: mocked encoder (sub-second integration)
  Layer 3: real model determinism (opt-in via RUN_BGE_M3_TESTS=1, added in Task 5)
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest


# ── Layer 1: pure logic ─────────────────────────────────────────────────────

def test_strip_frontmatter_and_body(stage2_mod):
    text = "---\ntype: company\naliases_en: [X]\n---\nBody here."
    fm, body = stage2_mod._strip_frontmatter_and_body(text)
    assert "Body here" in body
    assert "type: company" in fm


def test_strip_frontmatter_no_frontmatter(stage2_mod):
    text = "No frontmatter at all."
    fm, body = stage2_mod._strip_frontmatter_and_body(text)
    assert fm == ""
    assert body == text


def test_chunk_body_no_chunks_when_short(stage2_mod):
    chunks = stage2_mod._chunk_body("short body", chunk_chars=2000, overlap_chars=200)
    assert chunks == ["short body"]


def test_chunk_body_overlap(stage2_mod):
    body = "abcdefghij" * 500  # 5000 chars
    chunks = stage2_mod._chunk_body(body, chunk_chars=2000, overlap_chars=200)
    assert len(chunks) >= 3
    # consecutive chunks must overlap by exactly overlap_chars
    assert chunks[0][-200:] == chunks[1][:200]


def test_page_text_for_embedding(tmp_path, stage2_mod):
    p = tmp_path / "Tesla.md"
    p.write_text("---\ntype: company\n---\nTesla makes EVs.\n", encoding="utf-8")
    text = stage2_mod._page_text_for_embedding(p)
    assert text.startswith("Tesla\n\n")
    assert "Tesla makes EVs" in text


def test_entity_pages_returns_sorted_paths(tmp_path, stage2_mod):
    (tmp_path / "companies").mkdir()
    (tmp_path / "technologies").mkdir()
    (tmp_path / "companies" / "B.md").write_text("---\n---\n", encoding="utf-8")
    (tmp_path / "companies" / "A.md").write_text("---\n---\n", encoding="utf-8")
    (tmp_path / "technologies" / "C.md").write_text("---\n---\n", encoding="utf-8")
    pages = stage2_mod._entity_pages(tmp_path)
    stems = [p.stem for p in pages]
    # companies sorted, then technologies sorted (per _ENTITY_DIRS order)
    assert stems == ["A", "B", "C"]


def test_manifest_stale_when_missing(tmp_path, stage2_mod):
    assert stage2_mod._manifest_stale(tmp_path / "nonexistent.json", {"a": "sha1"}, "model-rev") is True


def test_manifest_stale_when_sha_differs(tmp_path, stage2_mod):
    m = tmp_path / "m.json"
    m.write_text(json.dumps({
        "model": "X", "model_revision": "rev1",
        "embedding_dim": 1024, "page_shas": {"a": "sha1"},
        "generated_at": "now",
    }), encoding="utf-8")
    assert stage2_mod._manifest_stale(m, {"a": "DIFFERENT"}, "rev1") is True


def test_manifest_stale_when_model_revision_differs(tmp_path, stage2_mod):
    m = tmp_path / "m.json"
    m.write_text(json.dumps({
        "model": "X", "model_revision": "rev1",
        "embedding_dim": 1024, "page_shas": {"a": "sha1"},
        "generated_at": "now",
    }), encoding="utf-8")
    assert stage2_mod._manifest_stale(m, {"a": "sha1"}, "rev2") is True


def test_manifest_fresh_when_all_match(tmp_path, stage2_mod):
    m = tmp_path / "m.json"
    m.write_text(json.dumps({
        "model": "X", "model_revision": "rev1",
        "embedding_dim": 1024, "page_shas": {"a": "sha1"},
        "generated_at": "now",
    }), encoding="utf-8")
    assert stage2_mod._manifest_stale(m, {"a": "sha1"}, "rev1") is False


def test_top_k_ranking_uses_max_across_chunks(stage2_mod):
    """Inject a fake (chunks × entities) similarity matrix and verify max-pool + sort."""
    canonicals = ["E0", "E1", "E2", "E3"]
    # 2 chunks, 4 entities. E2 wins via chunk-0; E0 wins via chunk-1; etc.
    sims = np.array([
        [0.5, 0.3, 0.9, 0.1],   # chunk 0
        [0.8, 0.7, 0.2, 0.6],   # chunk 1
    ])
    ranked = stage2_mod._rank_from_sims(sims, canonicals, k=4)
    # max across chunks: E0=0.8, E1=0.7, E2=0.9, E3=0.6
    assert ranked == [("E2", 0.9), ("E0", 0.8), ("E1", 0.7), ("E3", 0.6)]


def test_top_k_limits_to_k(stage2_mod):
    canonicals = ["E0", "E1", "E2", "E3", "E4"]
    sims = np.array([[0.9, 0.8, 0.7, 0.6, 0.5]])
    ranked = stage2_mod._rank_from_sims(sims, canonicals, k=2)
    assert ranked == [("E0", 0.9), ("E1", 0.8)]


def test_threshold_filter(stage2_mod):
    ranked = [("E0", 0.9), ("E1", 0.7), ("E2", 0.5), ("E3", 0.3)]
    filtered = stage2_mod._apply_threshold(ranked, threshold=0.6)
    assert filtered == [("E0", 0.9), ("E1", 0.7)]


def test_threshold_none_keeps_all(stage2_mod):
    ranked = [("E0", 0.9), ("E1", 0.1)]
    assert stage2_mod._apply_threshold(ranked, threshold=None) == ranked


def test_set_deterministic_runs_without_torch(stage2_mod):
    """_set_deterministic() must not raise even on fresh call."""
    stage2_mod._set_deterministic()  # smoke test


# ── Layer 2: mocked encoder ─────────────────────────────────────────────────


class _FakeEncoder:
    """Deterministic stub: embedding is SHA-256 of input text (32 dims)."""
    def encode(self, texts, normalize_embeddings=False, show_progress_bar=False, batch_size=8):
        vecs = []
        for t in texts:
            digest = hashlib.sha256(t.encode("utf-8")).digest()
            vec = np.frombuffer(digest, dtype=np.uint8).astype(np.float32) / 255.0
            if normalize_embeddings:
                norm = np.linalg.norm(vec)
                if norm > 0:
                    vec = vec / norm
            vecs.append(vec)
        return np.array(vecs)
    def eval(self):
        pass


def _install_fake_model(monkeypatch, stage2_mod, fake_revision="fake-rev-123"):
    monkeypatch.setattr(stage2_mod, "_get_model", lambda: _FakeEncoder())
    monkeypatch.setattr(stage2_mod, "_get_model_revision", lambda: fake_revision)


def test_build_entity_embeddings_with_mock(tmp_path, stage2_mod, monkeypatch):
    _install_fake_model(monkeypatch, stage2_mod)
    wiki = tmp_path / "wiki"
    (wiki / "companies").mkdir(parents=True)
    (wiki / "companies" / "Tesla.md").write_text("---\ntype: company\n---\nEV company.\n", encoding="utf-8")
    (wiki / "companies" / "BYD.md").write_text("---\ntype: company\n---\nChinese EV.\n", encoding="utf-8")
    embs, canonicals = stage2_mod.build_entity_embeddings(
        wiki, tmp_path / "embeddings.npy", tmp_path / "manifest.json", tmp_path / "canonicals.json"
    )
    assert embs.shape == (2, 32)
    assert set(canonicals) == {"BYD", "Tesla"}
    assert (tmp_path / "embeddings.npy").exists()
    assert (tmp_path / "manifest.json").exists()
    assert (tmp_path / "canonicals.json").exists()


def test_build_entity_embeddings_caches(tmp_path, stage2_mod, monkeypatch):
    """Second call with no changes loads from cache (no re-encode)."""
    _install_fake_model(monkeypatch, stage2_mod)
    wiki = tmp_path / "wiki"
    (wiki / "companies").mkdir(parents=True)
    (wiki / "companies" / "Tesla.md").write_text("---\ntype: company\n---\n", encoding="utf-8")
    npy = tmp_path / "e.npy"
    man = tmp_path / "m.json"
    can = tmp_path / "c.json"
    embs1, _ = stage2_mod.build_entity_embeddings(wiki, npy, man, can)
    embs2, _ = stage2_mod.build_entity_embeddings(wiki, npy, man, can)
    assert np.array_equal(embs1, embs2)


def test_build_entity_embeddings_invalidates_on_content_change(tmp_path, stage2_mod, monkeypatch):
    _install_fake_model(monkeypatch, stage2_mod)
    wiki = tmp_path / "wiki"
    (wiki / "companies").mkdir(parents=True)
    page = wiki / "companies" / "Tesla.md"
    page.write_text("---\ntype: company\n---\nv1\n", encoding="utf-8")
    npy = tmp_path / "e.npy"; man = tmp_path / "m.json"; can = tmp_path / "c.json"
    embs1, _ = stage2_mod.build_entity_embeddings(wiki, npy, man, can)
    page.write_text("---\ntype: company\n---\nv2 different content\n", encoding="utf-8")
    embs2, _ = stage2_mod.build_entity_embeddings(wiki, npy, man, can)
    assert not np.array_equal(embs1, embs2)


def test_build_entity_embeddings_invalidates_on_model_revision_change(tmp_path, stage2_mod, monkeypatch):
    wiki = tmp_path / "wiki"
    (wiki / "companies").mkdir(parents=True)
    (wiki / "companies" / "Tesla.md").write_text("---\ntype: company\n---\nx\n", encoding="utf-8")
    npy = tmp_path / "e.npy"; man = tmp_path / "m.json"; can = tmp_path / "c.json"
    _install_fake_model(monkeypatch, stage2_mod, fake_revision="rev-A")
    embs_a, _ = stage2_mod.build_entity_embeddings(wiki, npy, man, can)
    _install_fake_model(monkeypatch, stage2_mod, fake_revision="rev-B")
    embs_b, _ = stage2_mod.build_entity_embeddings(wiki, npy, man, can)
    # Same content but different model revision → rebuild ran (matrix may be identical because the fake encoder
    # doesn't depend on revision, but the manifest must have been overwritten with rev-B)
    manifest = json.loads(man.read_text(encoding="utf-8"))
    assert manifest["model_revision"] == "rev-B"


def test_run_for_source_top_k(tmp_path, stage2_mod, monkeypatch):
    _install_fake_model(monkeypatch, stage2_mod)
    wiki = tmp_path / "wiki"
    (wiki / "companies").mkdir(parents=True)
    (wiki / "companies" / "A.md").write_text("---\ntype: company\n---\nalpha alpha alpha\n", encoding="utf-8")
    (wiki / "companies" / "B.md").write_text("---\ntype: company\n---\nbeta beta beta\n", encoding="utf-8")
    raw = tmp_path / "raw.md"
    raw.write_text("---\n---\nThis source is about alpha alpha alpha.\n", encoding="utf-8")
    embs, canonicals = stage2_mod.build_entity_embeddings(
        wiki, tmp_path / "e.npy", tmp_path / "m.json", tmp_path / "c.json"
    )
    hits = stage2_mod.run_for_source(raw, embs, canonicals, top_k=2, threshold=None)
    assert len(hits) == 2
    # All hits have the right shape
    for h in hits:
        assert hasattr(h, "canonical")
        assert hasattr(h, "cosine")
        assert hasattr(h, "rank")
        assert h.confidence == "vector"


def test_run_for_source_applies_threshold(tmp_path, stage2_mod, monkeypatch):
    _install_fake_model(monkeypatch, stage2_mod)
    wiki = tmp_path / "wiki"
    (wiki / "companies").mkdir(parents=True)
    (wiki / "companies" / "A.md").write_text("---\ntype: company\n---\nalpha\n", encoding="utf-8")
    raw = tmp_path / "raw.md"
    raw.write_text("---\n---\nzzzz totally unrelated content yyyy.\n", encoding="utf-8")
    embs, canonicals = stage2_mod.build_entity_embeddings(
        wiki, tmp_path / "e.npy", tmp_path / "m.json", tmp_path / "c.json"
    )
    # high threshold should suppress everything from the fake encoder
    hits = stage2_mod.run_for_source(raw, embs, canonicals, top_k=20, threshold=0.99)
    assert hits == []
