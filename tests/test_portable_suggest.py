"""Verify portable suggestions against pinned output and actual file changes."""
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig

import pytest

from glassgraph.cli import main
from glassgraph.config import load_config
from glassgraph.core import index, linker, suggest as ranker
from glassgraph.extraction import suggest


FIXTURE = Path(__file__).parent / "fixtures/suggest/v1"


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
            for path in root.rglob("*")}


def source_fixture(root):
    source = root / "raw/sample.md"
    source.parent.mkdir(exist_ok=True)
    source.write_bytes((FIXTURE / "target.md").read_bytes())
    sources = root / "wiki/sources"
    sources.mkdir(parents=True, exist_ok=True)
    for path in (FIXTURE / "sources").iterdir():
        (sources / path.name).write_bytes(path.read_bytes())
    return source


@pytest.mark.parametrize("name,top", [("default", 20), ("top-three", 3), ("top-zero", 0)])
def test_pinned_report_and_ranked_fields(wiki_dir, tmp_path, name, top):
    source = source_fixture(tmp_path)
    before = snapshot(tmp_path)
    config = load_config(tmp_path)
    assert suggest(config, source, top_n=top) == (FIXTURE / f"{name}.txt").read_text(encoding="utf-8")
    if name == "default":
        _, _, aliases = index.compile_index(wiki_dir, config=config)
        df = ranker.compute_df_index(wiki_dir / "sources", config=config)
        fields = ranker.rank_candidates(linker._preprocess(source.read_text(encoding="utf-8")), set(aliases), df)
        assert fields == json.loads((FIXTURE / "ranked.json").read_text(encoding="utf-8"))
        assert "HiddenFrontMatter" not in {item["token"] for item in fields}
        assert "HiddenFence" not in {item["token"] for item in fields}
    assert snapshot(tmp_path) == before
    assert not (tmp_path / ".glassgraph").exists()


def test_unused_derived_state_and_rules_are_not_read(wiki_dir, tmp_path):
    source_fixture(tmp_path)
    state = tmp_path / ".glassgraph/index"
    state.mkdir(parents=True)
    (state / "manifest.json").mkdir()
    for name in ("aliases.json", "token-df.json", "disambiguation.yaml"):
        (state / name).write_bytes(b"\xff")
    (tmp_path / ".glassgraph/cache").write_text("retain", encoding="utf-8")
    legacy = tmp_path / ".tools/index/token-df.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text('{"Nova Switch":999}', encoding="utf-8")
    before = snapshot(tmp_path)
    assert suggest(load_config(tmp_path), "raw/sample.md") == (FIXTURE / "default.txt").read_text(encoding="utf-8")
    assert snapshot(tmp_path) == before


def test_current_target_aliases_and_df_are_read_each_run(wiki_dir, tmp_path):
    source = source_fixture(tmp_path)
    config = load_config(tmp_path)
    original = suggest(config, source)
    (wiki_dir / "sources/C.md").write_text("Nova Switch", encoding="utf-8")
    assert suggest(config, source) != original
    source.write_text("Indigo", encoding="utf-8")
    assert "'Indigo'" in suggest(config, source)
    (wiki_dir / "companies/Tesla.md").write_text("---\naliases_en: [Indigo]\n---\n", encoding="utf-8")
    assert suggest(config, source) == "No candidates found.\n"


def test_df_semantics_include_headers_and_fences_but_not_nested_files(wiki_dir, tmp_path):
    source_fixture(tmp_path)
    nested = wiki_dir / "sources/nested"
    nested.mkdir()
    (nested / "Ignored.md").write_text("Nova Switch", encoding="utf-8")
    df = ranker.compute_df_index(wiki_dir / "sources", config=load_config(tmp_path))
    assert df["Cobalt Motor"] == 2
    assert df["Nova Switch"] == 1
    (wiki_dir / "sources/A.md").write_text("---\nlabel: HeaderOnly\n---\n```\nFenceOnly\n```", encoding="utf-8")
    df = ranker.compute_df_index(wiki_dir / "sources", config=load_config(tmp_path))
    assert df["HeaderOnly"] == 1 and df["FenceOnly"] == 1
    assert df.get("Nova Switch", 0) == 0


def test_directories_named_markdown_are_not_files(wiki_dir, tmp_path):
    source_fixture(tmp_path)
    for folder in ("sources", "companies"):
        nested = wiki_dir / folder / "notes.md"
        nested.mkdir()
        (nested / "Nested.md").write_text("Nova Switch", encoding="utf-8")
    before = snapshot(tmp_path)
    assert suggest(load_config(tmp_path), "raw/sample.md") == (FIXTURE / "default.txt").read_text(encoding="utf-8")
    assert snapshot(tmp_path) == before


def test_source_removal_uses_separate_before_after_fixtures(tmp_path):
    for name, filenames in (("before", ["A.md", "B.md"]), ("after", ["A.md"])):
        directory = tmp_path / name / "wiki/sources"
        directory.mkdir(parents=True)
        for filename in filenames:
            (directory / filename).write_text("Nova Switch", encoding="utf-8")
    before = ranker.compute_df_index(tmp_path / "before/wiki/sources", config=load_config(tmp_path / "before"))
    after = ranker.compute_df_index(tmp_path / "after/wiki/sources", config=load_config(tmp_path / "after"))
    assert before["Nova Switch"] == 2 and after["Nova Switch"] == 1


@pytest.mark.parametrize("excluded", [False, True])
def test_missing_or_excluded_source_corpus_is_empty(wiki_dir, tmp_path, excluded):
    source = tmp_path / "raw/sample.md"
    source.parent.mkdir()
    source.write_text("Indigo", encoding="utf-8")
    if excluded:
        corpus = wiki_dir / "sources"
        corpus.mkdir()
        (corpus / "Invalid.md").write_bytes(b"\xff")
        marker = tmp_path / ".glassgraph"
        marker.mkdir()
        (marker / "config.toml").write_text('[paths]\nexclude=["wiki/sources"]\n', encoding="utf-8")
    before = snapshot(tmp_path)
    assert "df=0" in suggest(load_config(tmp_path), source)
    assert snapshot(tmp_path) == before


def test_custom_paths_and_file_exclusions(tmp_path):
    marker = tmp_path / ".glassgraph"
    marker.mkdir()
    (marker / "config.toml").write_text(
        '[paths]\nwiki="content/notes"\nraw="clippings"\nentity_dirs=["custom"]\n'
        'exclude=["content/notes/custom/Excluded.md","content/notes/sources/Skip.md"]\n', encoding="utf-8")
    for name, aliases in [("Known", "KnownToken"), ("Excluded", "NovelToken")]:
        page = tmp_path / "content/notes/custom" / f"{name}.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(f"---\naliases_en: [{aliases}]\n---\n", encoding="utf-8")
    corpus = tmp_path / "content/notes/sources"
    corpus.mkdir()
    (corpus / "Skip.md").write_bytes(b"\xff")
    (corpus / "A.md").write_text("NovelToken", encoding="utf-8")
    source = tmp_path / "clippings/source.md"
    source.parent.mkdir()
    source.write_text("KnownToken NovelToken", encoding="utf-8")
    before = snapshot(tmp_path)
    report = suggest(load_config(tmp_path), "clippings/source.md")
    assert "'KnownToken'" not in report and "'NovelToken'" in report
    assert "df=1" in report
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("source", ["missing.md", "wiki/companies/Tesla.md", "raw/no.txt", "raw/skip.md", "../outside.md", "raw/\0bad.md"])
def test_invalid_sources_produce_no_report(wiki_dir, tmp_path, source, capsys):
    source_fixture(tmp_path)
    (tmp_path / "raw/no.txt").write_text("Indigo", encoding="utf-8")
    (tmp_path / "raw/skip.md").write_text("Indigo", encoding="utf-8")
    marker = tmp_path / ".glassgraph"
    marker.mkdir()
    (marker / "config.toml").write_text('[paths]\nexclude=["raw/skip.md"]\n', encoding="utf-8")
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "suggest", source]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err.startswith("glassgraph:")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("target", ["raw/sample.md", "wiki/sources/A.md"])
def test_invalid_utf8_produces_no_report(wiki_dir, tmp_path, target, capsys):
    source_fixture(tmp_path)
    (tmp_path / target).write_bytes(b"\xff")
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "suggest", "raw/sample.md"]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err.startswith("glassgraph:")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("target", ["directory", "file", "stat"])
def test_unreadable_corpus_fails_without_partial_report(wiki_dir, tmp_path, target, monkeypatch, capsys):
    source_fixture(tmp_path)
    before = snapshot(tmp_path)
    if target == "directory":
        original = Path.iterdir

        def denied(path):
            if path == wiki_dir / "sources":
                raise PermissionError("Cannot read the source corpus")
            return original(path)

        attribute = "iterdir"
    elif target == "file":
        original = Path.open

        def denied(path, *args, **kwargs):
            if path == wiki_dir / "sources/A.md":
                raise PermissionError("Cannot read a source page")
            return original(path, *args, **kwargs)

        attribute = "open"
    else:
        original = Path.stat

        def denied(path, *args, **kwargs):
            if path == wiki_dir / "sources/A.md":
                raise PermissionError("Cannot inspect a source page")
            return original(path, *args, **kwargs)

        attribute = "stat"
    with monkeypatch.context() as patch:
        patch.setattr(Path, attribute, denied)
        assert main(["--root", str(tmp_path), "suggest", "raw/sample.md"]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err.startswith("glassgraph:")
    assert snapshot(tmp_path) == before


def test_unreadable_config_cannot_fall_back_to_defaults(wiki_dir, tmp_path, monkeypatch, capsys):
    source_fixture(tmp_path)
    config_file = tmp_path / ".glassgraph/config.toml"
    config_file.parent.mkdir()
    config_file.write_text("", encoding="utf-8")
    before = snapshot(tmp_path)
    original_stat = Path.stat
    original_open = Path.open

    def denied_stat(path, *args, **kwargs):
        if path == config_file:
            raise PermissionError("Cannot inspect configuration")
        return original_stat(path, *args, **kwargs)

    def denied_open(path, *args, **kwargs):
        if path == config_file:
            raise PermissionError("Cannot read configuration")
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "stat", denied_stat)
        patch.setattr(Path, "open", denied_open)
        assert main(["--root", str(tmp_path), "suggest", "raw/sample.md"]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err.startswith("glassgraph:")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("limit", ["-1", "bad"])
def test_invalid_limits_are_errors(wiki_dir, tmp_path, limit, capsys):
    source_fixture(tmp_path)
    before = snapshot(tmp_path)
    if limit == "bad":
        with pytest.raises(SystemExit) as error:
            main(["--root", str(tmp_path), "suggest", "raw/sample.md", "--top", limit])
        assert error.value.code == 2
    else:
        assert main(["--root", str(tmp_path), "suggest", "raw/sample.md", "--top", limit]) == 2
    assert capsys.readouterr().out == ""
    assert snapshot(tmp_path) == before


def test_source_corpus_path_must_be_a_directory(wiki_dir, tmp_path, capsys):
    source = tmp_path / "raw/sample.md"
    source.parent.mkdir()
    source.write_text("Indigo", encoding="utf-8")
    (wiki_dir / "sources").write_text("retain", encoding="utf-8")
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "suggest", "raw/sample.md"]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err.startswith("glassgraph:")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("body", ["", "The"])
def test_no_candidates_is_success(wiki_dir, tmp_path, body, capsys):
    source = source_fixture(tmp_path)
    source.write_text(body, encoding="utf-8")
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "suggest", "raw/sample.md"]) == 0
    assert capsys.readouterr().out == "No candidates found.\n"
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("location", ["source", "entity", "corpus"])
def test_redirected_external_reads_are_rejected(wiki_dir, tmp_path, location, capsys):
    source_fixture(tmp_path)
    outside = tmp_path.parent / (tmp_path.name + "-external.md")
    outside.write_text("PRIVATE", encoding="utf-8")
    target = {"source": tmp_path / "raw/redirect.md", "entity": wiki_dir / "companies/Redirect.md",
              "corpus": wiki_dir / "sources/Redirect.md"}[location]
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is unavailable")
    before = snapshot(tmp_path)
    source = "raw/redirect.md" if location == "source" else "raw/sample.md"
    assert main(["--root", str(tmp_path), "suggest", source]) == 2
    output = capsys.readouterr()
    assert output.out == "" and "PRIVATE" not in output.err
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("mode", ["flag", "environment", "marker"])
@pytest.mark.parametrize("entry", ["module", "console"])
def test_installed_command_outside_checkout(wiki_dir, tmp_path, mode, entry):
    source_fixture(tmp_path)
    (tmp_path / ".glassgraph").mkdir()
    nested = tmp_path / "unrelated/deep"
    nested.mkdir(parents=True)
    before = snapshot(tmp_path)
    env = dict(os.environ)
    env.pop("GLASSGRAPH_ROOT", None)
    env.pop("PYTHONPATH", None)
    if entry == "module":
        command = [sys.executable, "-I", "-B", "-m", "glassgraph"]
    else:
        executable = "glassgraph.exe" if os.name == "nt" else "glassgraph"
        command = [str(Path(sysconfig.get_path("scripts")) / executable)]
    command += ["suggest", "raw/sample.md", "--top", "3"]
    if mode == "flag":
        command += ["--root", str(tmp_path)]
    elif mode == "environment":
        env["GLASSGRAPH_ROOT"] = str(tmp_path)
    result = subprocess.run(command, cwd=nested, env=env, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert result.stdout == (FIXTURE / "top-three.txt").read_text(encoding="utf-8")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("installed", [True, False])
def test_legacy_import_outside_checkout(tmp_path, installed):
    script = """
import importlib.abc, importlib.util, sys
if sys.argv[2] == 'source':
    class BlockInstalledPackage(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == 'glassgraph':
                raise ModuleNotFoundError('Require the checkout bootstrap', name='glassgraph')
    sys.meta_path.insert(0, BlockInstalledPackage())
spec = importlib.util.spec_from_file_location('legacy_suggest', sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
from glassgraph.core import suggest
assert module.compute_df_index is suggest.compute_df_index
assert module.load_or_build_df is suggest.load_or_build_df
if sys.argv[2] == 'source':
    from pathlib import Path
    assert Path(suggest.__file__).resolve() == Path(sys.argv[1]).resolve().parent / 'src/glassgraph/core/suggest.py'
    assert 'yaml' not in sys.modules and 'glassgraph.config' not in sys.modules
"""
    arguments = [sys.executable, "-I", "-B"] + ([] if installed else ["-S"])
    shim = Path(__file__).resolve().parents[1] / "suggest.py"
    result = subprocess.run(arguments + ["-c", script, str(shim), "installed" if installed else "source"],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
