"""Check portable clustering against pinned reports and scoped file inputs."""
import dataclasses
from datetime import date
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import sysconfig

import pytest

from glassgraph.cli import main
from glassgraph.config import load_config
from glassgraph.core import cluster, source_metadata


FIXTURE = Path(__file__).parent / "fixtures/cluster/v1"
CASES = json.loads((FIXTURE / "cases.json").read_text(encoding="utf-8"))


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
            for path in root.rglob("*")}


def vault(root):
    shutil.copytree(FIXTURE / "wiki", root / "wiki")
    return load_config(root)


def config_file(root, text):
    marker = root / ".glassgraph"
    marker.mkdir(exist_ok=True)
    (marker / "config.toml").write_text(text, encoding="utf-8")


def page(path, metadata):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n" + json.dumps(metadata, ensure_ascii=False) + "\n---\nBody.\n", encoding="utf-8")


@pytest.mark.parametrize("case", CASES, ids=lambda item: item["name"])
def test_pinned_report_and_candidate_records(tmp_path, case, capsys):
    config = vault(tmp_path)
    before = snapshot(tmp_path)
    assert cluster.preview(config, min_sources=case["min_sources"], coverage=case["coverage"],
                           date_str=case["date"]) == case["report"]
    records = cluster.uncovered_candidates(config.wiki, case["min_sources"], case["coverage"], config=config)
    assert [dataclasses.asdict(record) for record in records] == case["candidates"]
    assert main(["--root", str(tmp_path), "cluster", "--min-sources", str(case["min_sources"]),
                 "--coverage", str(case["coverage"]), "--date", case["date"]]) == 0
    assert capsys.readouterr().out == case["report"]
    assert snapshot(tmp_path) == before
    assert not (tmp_path / ".glassgraph").exists()


def test_unused_derived_state_is_not_accessed(tmp_path):
    config = vault(tmp_path)
    marker = tmp_path / ".glassgraph"
    marker.mkdir()
    for name in ("index", "cache", "reports"):
        (marker / name).write_bytes(b"\xff")
    legacy = tmp_path / ".tools/extraction-cache/cluster-report.md"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("retain", encoding="utf-8")
    before = snapshot(tmp_path)
    assert cluster.preview(config, date_str=CASES[0]["date"]) == CASES[0]["report"]
    assert snapshot(tmp_path) == before


def test_current_theme_and_source_edits_are_visible(tmp_path):
    config = vault(tmp_path)
    assert len(cluster.uncovered_candidates(config.wiki, config=config)) == 1
    page(config.wiki / "themes/New.md", {"type": "theme", "sources": [f"拆解{i}.md" for i in range(5)]})
    assert not cluster.uncovered_candidates(config.wiki, config=config)
    for number in range(5):
        page(config.wiki / f"sources/new{number}.md", {"touches": ["New-A", "New-B"]})
    assert cluster.uncovered_candidates(config.wiki, config=config)[0].entities == ["New-A", "New-B"]
    for number in range(5):
        page(config.wiki / f"sources/new{number}.md", {"touches": ["New-A"]})
    assert not cluster.uncovered_candidates(config.wiki, config=config)


def test_removal_uses_separate_before_after_fixtures(tmp_path):
    for name, count in (("before", 3), ("after", 2)):
        root = tmp_path / name
        for number in range(count):
            page(root / f"wiki/sources/{number}.md", {"touches": ["A", "B"]})
    before = load_config(tmp_path / "before")
    after = load_config(tmp_path / "after")
    assert len(cluster.candidate_groups(before.wiki / "sources", 3, config=before)) == 1
    assert cluster.candidate_groups(after.wiki / "sources", 3, config=after) == []


def test_custom_paths_declared_themes_and_exclusions(tmp_path):
    config_file(tmp_path, '[paths]\nwiki="notes"\nraw="clippings"\nentity_dirs=["custom"]\n'
                          'exclude=["notes/sources/Skip.md","notes/custom/Skip.md"]\n')
    for name in ("A", "B"):
        page(tmp_path / f"notes/sources/{name}.md", {"touches": ["One", "Two"]})
    (tmp_path / "notes/sources/Skip.md").write_bytes(b"\xff")
    page(tmp_path / "notes/custom/Theme.md", {"type": "theme", "sources": "A.md"})
    page(tmp_path / "notes/custom/Company.md", {"type": "company", "sources": False})
    (tmp_path / "notes/custom/Skip.md").write_bytes(b"\xff")
    config = load_config(tmp_path)
    assert len(cluster.uncovered_candidates(config.wiki, 2, 0.6, config=config)) == 1
    page(tmp_path / "notes/custom/Theme.md", {"type": "theme", "sources": ["A.md", "B.md"]})
    assert not cluster.uncovered_candidates(config.wiki, 2, 0.6, config=config)


def test_omitted_theme_folder_does_not_cover_candidates(tmp_path):
    vault(tmp_path)
    config_file(tmp_path, '[paths]\nentity_dirs=[]\n')
    config = load_config(tmp_path)
    assert len(cluster.uncovered_candidates(config.wiki, config=config)) == 2


def test_nonrecursive_scans_skip_directories_and_unrelated_entities(tmp_path):
    config = vault(tmp_path)
    page(config.wiki / "sources/nested/Hidden.md", {"touches": ["A", "B"]})
    page(config.wiki / "sources/folder.md/Nested.md", {"touches": ["A", "B"]})
    invalid = config.wiki / "companies/Invalid.md"
    invalid.parent.mkdir()
    invalid.write_bytes(b"\xff")
    assert cluster.preview(config, date_str=CASES[0]["date"]) == CASES[0]["report"]


def test_archive_source_exclusion_is_preserved(tmp_path):
    config_file(tmp_path, '[paths]\nwiki=".archive/wiki"\n')
    page(tmp_path / ".archive/wiki/sources/A.md", {"touches": ["A", "B"]})
    config = load_config(tmp_path)
    assert cluster.candidate_groups(config.wiki / "sources", 1, config=config) == []


def test_missing_or_excluded_sources_are_empty(tmp_path):
    (tmp_path / "wiki").mkdir()
    config = load_config(tmp_path)
    assert "Uncovered candidate clusters: 0" in cluster.preview(config)
    page(tmp_path / "wiki/sources/A.md", {"touches": ["A", "B"]})
    config_file(tmp_path, '[paths]\nexclude=["wiki/sources"]\n')
    assert "Uncovered candidate clusters: 0" in cluster.preview(load_config(tmp_path), min_sources=1)


def test_default_date_uses_local_calendar(tmp_path, monkeypatch):
    config = vault(tmp_path)

    class FixedDate(date):
        @classmethod
        def today(cls):
            return cls(2026, 1, 2)

    monkeypatch.setattr(cluster, "date", FixedDate)
    assert cluster.preview(config).startswith("# Theme Cluster Report — 2026-01-02\n")


@pytest.mark.parametrize("options", [
    ["--min-sources=0"], ["--min-sources=-1"], ["--coverage=-0.1"], ["--coverage=1.1"],
    ["--coverage=nan"], ["--coverage=inf"], ["--coverage=-inf"], ["--date=2026-02-30"],
    ["--date=20260613"], ["--date="],
])
def test_invalid_options_produce_no_report(tmp_path, options, capsys):
    vault(tmp_path)
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "cluster", *options]) == 2
    assert capsys.readouterr().out == ""
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("option", ["--min-sources=bad", "--coverage=bad"])
def test_nonnumeric_options_are_argument_errors(tmp_path, option, capsys):
    vault(tmp_path)
    with pytest.raises(SystemExit) as error:
        main(["--root", str(tmp_path), "cluster", option])
    assert error.value.code == 2
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("location,metadata", [
    ("sources/A.md", {"touches": False}), ("sources/A.md", {"touches": 1}),
    ("sources/A.md", {"touches": [1]}), ("themes/Existing.md", {"sources": False}),
    ("themes/Existing.md", {"sources": {"bad": "mapping"}}),
])
def test_unusable_metadata_is_an_error(tmp_path, location, metadata, capsys):
    vault(tmp_path)
    page(tmp_path / "wiki" / location, metadata)
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "cluster"]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err.startswith("glassgraph:")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("location,content", [
    ("sources/A.md", b"\xff"), ("themes/Existing.md", b"\xff"),
    ("sources/A.md", b"---\ntouches: [bad\n---\n"),
    ("themes/Existing.md", b"---\nsources: bad\x00\n---\n"),
])
def test_parse_and_encoding_failures_are_errors(tmp_path, location, content, capsys):
    vault(tmp_path)
    (tmp_path / "wiki" / location).write_bytes(content)
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "cluster"]) == 2
    assert capsys.readouterr().out == ""
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("failure", ["source-directory", "theme-directory", "source-file", "theme-file", "source-stat"])
def test_read_failures_do_not_emit_partial_report(tmp_path, failure, monkeypatch, capsys):
    config = vault(tmp_path)
    targets = {"source-directory": config.wiki / "sources", "theme-directory": config.wiki / "themes",
               "source-file": config.wiki / "sources/ab0.md", "theme-file": config.wiki / "themes/Existing.md",
               "source-stat": config.wiki / "sources/ab0.md"}
    attribute = "iterdir" if failure.endswith("directory") else "stat" if failure.endswith("stat") else "open"
    original = getattr(Path, attribute)
    before = snapshot(tmp_path)

    def denied(path, *args, **kwargs):
        if path == targets[failure]:
            raise PermissionError("Cannot read cluster input")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, attribute, denied)
        assert main(["--root", str(tmp_path), "cluster"]) == 2
    assert capsys.readouterr().out == ""
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("folder", ["sources", "themes"])
def test_external_redirects_are_rejected(tmp_path, folder, capsys):
    vault(tmp_path)
    outside = tmp_path.parent / (tmp_path.name + "-private.md")
    outside.write_text("PRIVATE", encoding="utf-8")
    target = tmp_path / "wiki" / folder / "Redirect.md"
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is unavailable")
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "cluster"]) == 2
    output = capsys.readouterr()
    assert output.out == "" and "PRIVATE" not in output.err
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("mode", ["flag", "environment", "marker"])
@pytest.mark.parametrize("entry", ["module", "console"])
def test_installed_command_outside_checkout(tmp_path, mode, entry):
    vault(tmp_path)
    (tmp_path / ".glassgraph").mkdir()
    nested = tmp_path / "unrelated/deep"
    nested.mkdir(parents=True)
    before = snapshot(tmp_path)
    env = dict(os.environ)
    env.pop("GLASSGRAPH_ROOT", None)
    env.pop("PYTHONPATH", None)
    command = ([sys.executable, "-I", "-B", "-m", "glassgraph"] if entry == "module" else
               [str(Path(sysconfig.get_path("scripts")) / ("glassgraph.exe" if os.name == "nt" else "glassgraph"))])
    command += ["cluster", "--date", CASES[0]["date"]]
    if mode == "flag":
        command += ["--root", str(tmp_path)]
    elif mode == "environment":
        env["GLASSGRAPH_ROOT"] = str(tmp_path)
    result = subprocess.run(command, cwd=nested, env=env, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert result.stdout == CASES[0]["report"]
    assert snapshot(tmp_path) == before


def test_hash_seeds_preserve_tied_report_order(tmp_path):
    vault(tmp_path)
    reports = []
    for seed in ("1", "2", "17"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        result = subprocess.run([sys.executable, "-B", "-m", "glassgraph", "--root", str(tmp_path),
                                 "cluster", "--coverage=1", "--date", CASES[0]["date"]],
                                cwd=tmp_path, env=env, capture_output=True, text=True, encoding="utf-8")
        assert result.returncode == 0, result.stderr
        reports.append(result.stdout)
    assert reports == [CASES[1]["report"]] * 3


def test_package_does_not_require_legacy_graph_or_networkx(tmp_path):
    vault(tmp_path)
    script = """
import importlib.abc, sys
class BlockGraphDependencies(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'graph', 'networkx'}:
            raise ModuleNotFoundError('Graph dependency is unavailable', name=fullname)
sys.meta_path.insert(0, BlockGraphDependencies())
from glassgraph.config import load_config
from glassgraph.core.cluster import preview
sys.stdout.reconfigure(encoding='utf-8')
print(preview(load_config(sys.argv[1]), date_str='2026-06-13'), end='')
"""
    result = subprocess.run([sys.executable, "-I", "-B", "-c", script, str(tmp_path)],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert result.stdout == CASES[0]["report"]


def test_legacy_command_still_writes_its_report(tmp_path, capsys):
    import importlib.util

    config = vault(tmp_path)
    path = Path(__file__).resolve().parents[1] / "link.py"
    spec = importlib.util.spec_from_file_location("legacy_cluster_command", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    cache = tmp_path / "legacy-cache"
    assert module.run_cluster(wiki_root=config.wiki, cache_dir=cache) == 0
    report = (cache / "cluster-report.md").read_text(encoding="utf-8")
    assert report.splitlines()[1:] == CASES[0]["report"].splitlines()[1:]
    assert "uncovered candidates: 1" in capsys.readouterr().out


@pytest.mark.parametrize("installed", [True, False])
def test_legacy_imports_and_shared_parser(tmp_path, installed):
    script = """
import importlib.abc, importlib.util, sys, sysconfig
if sys.argv[2] == 'source':
    sys.path.append(sysconfig.get_path('purelib'))
    class BlockInstalledPackage(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == 'glassgraph':
                raise ModuleNotFoundError('Require source bootstrap', name='glassgraph')
    sys.meta_path.insert(0, BlockInstalledPackage())
from pathlib import Path
for name in ('cluster', 'graph'):
    spec = importlib.util.spec_from_file_location(name, Path(sys.argv[1]) / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if name == 'cluster':
        from glassgraph.core import cluster
        assert module.render_report is cluster.render_report
    else:
        from glassgraph.core import source_metadata
        assert module._parse_touches is source_metadata.parse_touches
if sys.argv[2] == 'source':
    assert Path(cluster.__file__).resolve() == Path(sys.argv[1]).resolve() / 'src/glassgraph/core/cluster.py'
"""
    args = [sys.executable, "-I", "-B"] + ([] if installed else ["-S"])
    result = subprocess.run(args + ["-c", script, str(Path(__file__).resolve().parents[1]),
                                    "installed" if installed else "source"],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr


def test_legacy_string_and_list_parsing_remains_shared(tmp_path, graph_mod):
    for value, expected in [(None, []), ("[[A|alias]]", ["A"]), (["[[A]]", "B"], ["A", "B"])]:
        source = tmp_path / "source.md"
        page(source, {"touches": value})
        assert source_metadata.parse_touches(source, strict=True) == expected
        assert graph_mod._parse_touches(source) == expected
