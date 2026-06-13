"""Tests for `link.py lookup` — dedup existence query against the alias table."""
from __future__ import annotations

import importlib.util
import sys
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


def test_lookup_resolves_exact_and_alias(wiki_dir, tmp_path, capsys):
    link = _load_link()
    rc = link.run_lookup("特斯拉", wiki_root=wiki_dir, index_dir=tmp_path / "index")
    out = capsys.readouterr().out
    assert rc == 0 and "Tesla" in out


def test_lookup_case_insensitive(wiki_dir, tmp_path, capsys):
    link = _load_link()
    rc = link.run_lookup("tesla", wiki_root=wiki_dir, index_dir=tmp_path / "index")
    out = capsys.readouterr().out
    assert rc == 0 and "Tesla" in out


def test_lookup_not_found(wiki_dir, tmp_path, capsys):
    link = _load_link()
    rc = link.run_lookup("NonexistentCorp", wiki_root=wiki_dir, index_dir=tmp_path / "index")
    out = capsys.readouterr().out
    assert rc == 1 and "NOT FOUND" in out
