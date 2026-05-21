"""Smoke test for stage2_poc.py — verifies the embedding pipeline runs."""
import importlib.util
import sys
from pathlib import Path

import pytest


@pytest.fixture(scope="session")
def stage2_mod():
    src = Path(__file__).resolve().parents[1] / "stage2_poc.py"
    spec = importlib.util.spec_from_file_location("stage2_poc", src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["stage2_poc"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_chunk_body_basic(stage2_mod):
    body = "abc" * 1000
    chunks = stage2_mod._chunk_body(body, chunk_chars=500, overlap_chars=50)
    assert len(chunks) >= 5
    assert chunks[0].startswith("abc")


def test_strip_frontmatter(stage2_mod):
    text = "---\ntype: company\n---\nBody here."
    fm, body = stage2_mod._strip_frontmatter_and_body(text)
    assert "Body here" in body
    assert "type" in fm


def test_entity_pages_returns_paths(tmp_path, stage2_mod):
    (tmp_path / "companies").mkdir()
    (tmp_path / "companies" / "Tesla.md").write_text("test", encoding="utf-8")
    pages = stage2_mod._entity_pages(tmp_path)
    assert len(pages) == 1
    assert pages[0].stem == "Tesla"
