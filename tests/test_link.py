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
    p.write_text(f"---\ntouches:\n{fm_t}\n---\nBody.\n", encoding="utf-8")
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
    cache_dir.mkdir()
    (cache_dir / "test.json").write_text('{"skip": true}', encoding="utf-8")
    link = _load_link()
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
    assert "skip" in out.lower() or json.loads((cache_dir / "test.json").read_text())["skip"] is True


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
