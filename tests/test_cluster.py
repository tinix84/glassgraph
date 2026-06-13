"""Tests for co-occurrence theme-candidate clustering."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load(name: str):
    if name in sys.modules:
        return sys.modules[name]
    src = Path(__file__).resolve().parents[1] / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def cluster():
    return _load("cluster")


def _src(d: Path, name: str, touches: list[str]):
    body = "\n".join(f'  - "[[{t}]]"' for t in touches)
    (d / name).write_text(
        f"---\ntype: source\nsource_url: x\ntouches:\n{body}\n---\nBody.\n",
        encoding="utf-8")


@pytest.fixture
def corpus(tmp_path):
    s = tmp_path / "wiki" / "sources"
    s.mkdir(parents=True)
    for i in range(5):
        _src(s, f"ab{i}.md", ["GaN-HEMT", "Data-center"])
    _src(s, "cd0.md", ["IGBT", "Tesla"])
    _src(s, "cd1.md", ["IGBT", "Tesla"])
    return tmp_path / "wiki"


def test_cooccurrence_counts_shared_sources(cluster, corpus):
    cooc = cluster.cooccurrence(corpus / "sources")
    assert cooc[frozenset({"GaN-HEMT", "Data-center"})] == 5
    assert cooc[frozenset({"IGBT", "Tesla"})] == 2


def test_candidate_groups_threshold(cluster, corpus):
    groups = cluster.candidate_groups(corpus / "sources", min_sources=5)
    members = [set(g.entities) for g in groups]
    assert {"GaN-HEMT", "Data-center"} in members
    assert {"IGBT", "Tesla"} not in members


def test_candidate_group_carries_evidence_sources(cluster, corpus):
    groups = cluster.candidate_groups(corpus / "sources", min_sources=5)
    g = next(g for g in groups if set(g.entities) == {"GaN-HEMT", "Data-center"})
    assert g.source_count == 5
    assert all(s.startswith("ab") for s in g.sources)


def test_coverage_filter_drops_covered(cluster, corpus):
    themes = corpus / "themes"
    themes.mkdir()
    src_list = "\n".join(f"  - {f}.md" for f in ["ab0", "ab1", "ab2", "ab3"])
    (themes / "GaN-in-data-centers.md").write_text(
        f"---\ntype: theme\nthesis: x\nstatus: open\nsources:\n{src_list}\n---\nT.\n",
        encoding="utf-8")
    uncovered = cluster.uncovered_candidates(corpus, min_sources=5, coverage=0.6)
    members = [set(g.entities) for g in uncovered]
    assert {"GaN-HEMT", "Data-center"} not in members


def test_uncovered_when_no_theme(cluster, corpus):
    (corpus / "themes").mkdir(exist_ok=True)
    uncovered = cluster.uncovered_candidates(corpus, min_sources=5, coverage=0.6)
    members = [set(g.entities) for g in uncovered]
    assert {"GaN-HEMT", "Data-center"} in members


def test_report_lists_candidates(cluster, corpus):
    (corpus / "themes").mkdir(exist_ok=True)
    report = cluster.render_report(corpus, min_sources=5, coverage=0.6, date_str="2026-06-13")
    assert "GaN-HEMT" in report and "Data-center" in report
    assert "## Candidate" in report or "candidate" in report.lower()


def test_cjk_source_filenames(cluster, tmp_path):
    s = tmp_path / "wiki" / "sources"
    s.mkdir(parents=True)
    for i in range(5):
        _src(s, f"拆解{i}.md", ["SiC-MOSFET", "HVDC"])
    groups = cluster.candidate_groups(s, min_sources=5)
    assert any(set(g.entities) == {"SiC-MOSFET", "HVDC"} for g in groups)
