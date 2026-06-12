"""CLI integration tests for link.py — dry-run only, no filesystem side effects."""
from __future__ import annotations

import importlib.util
import json
import sys
import textwrap
from pathlib import Path


def _load_link():
    if "link" in sys.modules:
        return sys.modules["link"]
    src = Path(__file__).resolve().parents[1] / "link.py"
    spec = importlib.util.spec_from_file_location("link", src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["link"] = mod
    spec.loader.exec_module(mod)
    return mod


def _make_raw_file(tmp_path: Path, name: str, body: str) -> Path:
    raw = tmp_path / "raw"
    raw.mkdir(exist_ok=True)
    p = raw / name
    p.write_text(f"---\nsource_url: http://example.com\n---\n{body}", encoding="utf-8")
    return p


def _make_source_page(tmp_path: Path, name: str, touches: list[str]) -> Path:
    sources = tmp_path / "wiki" / "sources"
    sources.mkdir(parents=True, exist_ok=True)
    p = sources / name
    fm_t = "\n".join(f"  - '[[{t}]]'" for t in touches)
    p.write_text(
        f"---\ntype: source\nsource_url: http://example.com/{name}\ntouches:\n{fm_t}\n---\nBody.\n",
        encoding="utf-8",
    )
    return p


def test_run_single_dry_run_prints_entities(wiki_dir, tmp_path, capsys):
    raw_file = _make_raw_file(
        tmp_path, "test.md",
        "Tesla unveiled a SiC MOSFET inverter. 比亚迪 also uses 碳化硅."
    )
    link = _load_link()
    link.run_single(
        raw_path=raw_file,
        wiki_root=wiki_dir,
        index_dir=tmp_path / "index",
        cache_dir=tmp_path / "cache",
        dry_run=True,
        force=False,
        verbose=False,
    )
    out = capsys.readouterr().out
    assert "entities:" in out


def test_run_single_writes_cache_file(wiki_dir, tmp_path):
    raw_file = _make_raw_file(tmp_path, "test.md", "Tesla and BYD.")
    link = _load_link()
    cache_dir = tmp_path / "cache"
    link.run_single(
        raw_path=raw_file,
        wiki_root=wiki_dir,
        index_dir=tmp_path / "index",
        cache_dir=cache_dir,
        dry_run=False,
        force=False,
        verbose=False,
    )
    cache_file = cache_dir / "test.json"
    assert cache_file.exists()
    data = json.loads(cache_file.read_text(encoding="utf-8"))
    assert "entities" in data
    assert any(e["canonical"] == "Tesla" for e in data["entities"])


def test_run_single_skips_if_cache_exists(wiki_dir, tmp_path, capsys):
    raw_file = _make_raw_file(tmp_path, "test.md", "Tesla.")
    cache_dir = tmp_path / "cache"
    link = _load_link()
    # First run: populates cache with a valid manifest_sha
    link.run_single(
        raw_path=raw_file,
        wiki_root=wiki_dir,
        index_dir=tmp_path / "index",
        cache_dir=cache_dir,
        dry_run=False,
        force=False,
        verbose=False,
    )
    capsys.readouterr()  # clear output from first run
    # Second run: cache is fresh (sha matches) — must skip
    link.run_single(
        raw_path=raw_file,
        wiki_root=wiki_dir,
        index_dir=tmp_path / "index",
        cache_dir=cache_dir,
        dry_run=False,
        force=False,
        verbose=False,
    )
    out = capsys.readouterr().out
    assert "skip" in out.lower()


def test_run_single_force_overwrites_cache(wiki_dir, tmp_path):
    raw_file = _make_raw_file(tmp_path, "test.md", "Tesla and BYD.")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "test.json").write_text('{"stale": true}', encoding="utf-8")
    link = _load_link()
    link.run_single(
        raw_path=raw_file,
        wiki_root=wiki_dir,
        index_dir=tmp_path / "index",
        cache_dir=cache_dir,
        dry_run=False,
        force=True,
        verbose=False,
    )
    data = json.loads((cache_dir / "test.json").read_text(encoding="utf-8"))
    assert "entities" in data  # overwritten with real extraction


def test_run_backfill_dry_run_prints_report(wiki_dir, tmp_path, capsys):
    _make_raw_file(tmp_path, "source_a.md", "Tesla unveiled a SiC MOSFET inverter.")
    _make_source_page(tmp_path, "source_a.md", ["Tesla"])
    link = _load_link()
    link.run_backfill(
        wiki_root=wiki_dir,
        raw_dir=tmp_path / "raw",
        sources_dir=tmp_path / "wiki" / "sources",
        index_dir=tmp_path / "index",
        cache_dir=tmp_path / "cache",
        report_path=tmp_path / "backfill-delta.md",
        dry_run=True,
        skip_sanity_gate=True,
    )
    out = capsys.readouterr().out
    assert "backfill" in out.lower() or "match" in out.lower()


def test_run_backfill_writes_report_file(wiki_dir, tmp_path):
    _make_raw_file(tmp_path, "source_a.md", "Tesla and BYD.")
    _make_source_page(tmp_path, "source_a.md", ["Tesla", "BYD"])
    link = _load_link()
    report_path = tmp_path / "backfill-delta.md"
    link.run_backfill(
        wiki_root=wiki_dir,
        raw_dir=tmp_path / "raw",
        sources_dir=tmp_path / "wiki" / "sources",
        index_dir=tmp_path / "index",
        cache_dir=tmp_path / "cache",
        report_path=report_path,
        dry_run=False,
        skip_sanity_gate=True,
    )
    assert report_path.exists()
    assert "# Backfill Audit" in report_path.read_text(encoding="utf-8")


# ── --vector flag ───────────────────────────────────────────────────────────

def test_run_single_without_vector_omits_vector_fields(wiki_dir, tmp_path):
    raw_file = _make_raw_file(tmp_path, "test.md", "Tesla and BYD.")
    link = _load_link()
    cache_dir = tmp_path / "cache"
    link.run_single(
        raw_path=raw_file,
        wiki_root=wiki_dir,
        index_dir=tmp_path / "index",
        cache_dir=cache_dir,
        dry_run=False,
        force=False,
        verbose=False,
    )
    data = json.loads((cache_dir / "test.json").read_text(encoding="utf-8"))
    assert "vector_entities" not in data
    assert "vector_manifest_sha" not in data


def test_stale_cache_is_reextracted(wiki_dir, tmp_path, capsys):
    """A cache whose manifest_sha no longer matches must be re-extracted, not skipped."""
    link = _load_link()
    raw = tmp_path / "raw" / "test.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("Tesla uses SiC MOSFET.", encoding="utf-8")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    (cache_dir / "test.json").write_text(
        '{"manifest_sha": "0000000000000000", "entities": []}', encoding="utf-8")
    link.run_single(raw, wiki_root=wiki_dir,
                    index_dir=tmp_path / "index", cache_dir=cache_dir)
    out = capsys.readouterr().out
    assert "skip" not in out
    data = json.loads((cache_dir / "test.json").read_text(encoding="utf-8"))
    assert data["manifest_sha"] != "0000000000000000"
    assert data["entities"]


def test_fresh_cache_is_skipped(wiki_dir, tmp_path, capsys):
    link = _load_link()
    raw = tmp_path / "raw" / "test.md"
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("Tesla uses SiC MOSFET.", encoding="utf-8")
    cache_dir = tmp_path / "cache"
    cache_dir.mkdir()
    link.run_single(raw, wiki_root=wiki_dir,
                    index_dir=tmp_path / "index", cache_dir=cache_dir)  # populates
    link.run_single(raw, wiki_root=wiki_dir,
                    index_dir=tmp_path / "index", cache_dir=cache_dir)  # should skip
    assert "skip (cached" in capsys.readouterr().out


def test_sanity_gate_noninteractive_exits_nonzero(wiki_dir, tmp_path):
    """Under a non-TTY stdin the gate must exit non-zero, not silently exit 0."""
    import pytest
    link = _load_link()
    raw_dir = tmp_path / "raw"
    sources_dir = tmp_path / "wiki_sources"
    raw_dir.mkdir(); sources_dir.mkdir()
    for i in range(11):
        (raw_dir / f"s{i:02}.md").write_text("Tesla here.", encoding="utf-8")
        (sources_dir / f"s{i:02}.md").write_text(
            "---\ntype: source\nsource_url: x\ntouches: []\n---\nB.\n", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        link.run_backfill(
            wiki_root=wiki_dir, raw_dir=raw_dir, sources_dir=sources_dir,
            index_dir=tmp_path / "index", cache_dir=tmp_path / "cache",
            report_path=tmp_path / "report.md", no_lint=True)
    assert exc.value.code == 2


def test_run_single_with_vector_includes_vector_entities(wiki_dir, tmp_path, monkeypatch):
    """Mock stage2.run_for_source to avoid loading the real model."""
    raw_file = _make_raw_file(tmp_path, "test.md", "Tesla and BYD.")
    link = _load_link()

    # Patch stage2 functions via the module-level cache
    import importlib.util
    src = Path(__file__).resolve().parents[1] / "stage2.py"
    spec = importlib.util.spec_from_file_location("stage2", src)
    stage2_mod = importlib.util.module_from_spec(spec)
    sys.modules["stage2"] = stage2_mod
    spec.loader.exec_module(stage2_mod)

    fake_hits = [
        stage2_mod.VectorHit(canonical="Tesla", cosine=0.9, rank=1),
        stage2_mod.VectorHit(canonical="BYD", cosine=0.8, rank=2),
    ]
    monkeypatch.setattr(stage2_mod, "run_for_source", lambda *a, **kw: fake_hits)
    import numpy as np
    monkeypatch.setattr(stage2_mod, "build_entity_embeddings", lambda *a, **kw: (np.zeros((2, 4)), ["Tesla", "BYD"]))
    monkeypatch.setattr(stage2_mod, "manifest_sha", lambda *a, **kw: "fake_sha")

    cache_dir = tmp_path / "cache"
    link.run_single(
        raw_path=raw_file,
        wiki_root=wiki_dir,
        index_dir=tmp_path / "index",
        cache_dir=cache_dir,
        dry_run=False,
        force=False,
        verbose=False,
        vector=True,
        top_k=20,
        threshold=None,
    )
    data = json.loads((cache_dir / "test.json").read_text(encoding="utf-8"))
    assert "vector_entities" in data
    assert len(data["vector_entities"]) == 2
    assert data["vector_entities"][0]["canonical"] == "Tesla"
    assert data["vector_entities"][0]["cosine"] == 0.9
    assert data["vector_entities"][0]["rank"] == 1
    assert data["vector_entities"][0]["confidence"] == "vector"
    assert data["vector_manifest_sha"] == "fake_sha"
