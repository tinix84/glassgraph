"""Exercise portable extraction through public interfaces and actual files."""
import dataclasses
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from glassgraph.cli import main
from glassgraph.config import load_config
from glassgraph.extraction import extract


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob("*") if p.is_file()}


def make_source(root, name="sample.md", text="Tesla coil. Tesla and 比亚迪 use SiC."):
    path = root / "raw" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    return path


def test_parity_and_dry_run(wiki_dir, tmp_path, index_mod, linker_mod, capsys):
    source = make_source(tmp_path)
    rules = tmp_path / ".glassgraph/index/disambiguation.yaml"
    rules.parent.mkdir(parents=True)
    rules.write_text("- pattern: Tesla coil\n", encoding="utf-8")
    legacy = tmp_path / "legacy"
    legacy.mkdir()
    automaton = index_mod.build_index(wiki_dir, legacy / "manifest.json", legacy / "aliases.json")
    sha = hashlib.sha256((legacy / "aliases.json").read_bytes()).hexdigest()[:16]
    expected = dataclasses.asdict(linker_mod.extract_file(source, automaton, sha, rules))
    before = snapshot(tmp_path)
    assert main(["extract", "raw/sample.md", "--root", str(tmp_path), "--dry-run"]) == 0
    actual = json.loads(capsys.readouterr().out)
    for key in ("source", "manifest_sha", "entities", "disambiguation_warnings"):
        assert actual[key] == expected[key]
    assert actual["disambiguation_warnings"]
    assert snapshot(tmp_path) == before
    data = extract(load_config(tmp_path), "raw/sample.md")
    assert (tmp_path / ".glassgraph/index/aliases.json").read_bytes() == (legacy / "aliases.json").read_bytes()
    assert json.loads((tmp_path / ".glassgraph/cache/extraction/raw/sample.md.json").read_text(encoding="utf-8")) == data
    assert all(snapshot(tmp_path)[name] == content for name, content in before.items())


def test_dry_run_creates_no_state(wiki_dir, tmp_path):
    make_source(tmp_path)
    before = snapshot(tmp_path)
    extract(load_config(tmp_path), "raw/sample.md", dry_run=True)
    assert not (tmp_path / ".glassgraph").exists()
    assert snapshot(tmp_path) == before


def test_rerun_tracks_source_alias_rules_and_same_stem(wiki_dir, tmp_path):
    source = make_source(tmp_path, "a/same.md", "Tesla coil.")
    other = make_source(tmp_path, "b/same.md", "BYD")
    state = tmp_path / ".tools/index/aliases.json"
    state.parent.mkdir(parents=True)
    state.write_text("legacy state", encoding="utf-8")
    config = load_config(tmp_path)
    assert extract(config, source)["entities"][0]["canonical"] == "Tesla"
    rules = tmp_path / ".glassgraph/index/disambiguation.yaml"
    rules.write_text("- pattern: Tesla coil\n", encoding="utf-8")
    assert extract(config, source)["entities"] == []
    source.write_text("TSLA", encoding="utf-8")
    assert extract(config, source)["entities"][0]["canonical"] == "Tesla"
    (wiki_dir / "companies/Tesla.md").write_text("---\naliases_en: [Other]\n---\n", encoding="utf-8")
    assert extract(config, source)["entities"] == []
    assert extract(config, other)["entities"][0]["canonical"] == "BYD"
    assert (tmp_path / ".glassgraph/cache/extraction/raw/a/same.md.json").exists()
    assert (tmp_path / ".glassgraph/cache/extraction/raw/b/same.md.json").exists()
    assert state.read_text(encoding="utf-8") == "legacy state"


def test_config_order_exclusions_and_sources(tmp_path):
    marker = tmp_path / ".glassgraph"
    marker.mkdir()
    (marker / "config.toml").write_text(
        '[paths]\nwiki="notes"\nraw="clippings"\nentity_dirs=["custom","companies"]\n'
        'exclude=["notes/custom/Skip.md"]\n', encoding="utf-8")
    for folder, name, extra in [("custom", "First", ""), ("companies", "Second", ""),
                                 ("custom", "Skip", ""), ("custom", "Merged", "tags: [merged]\n")]:
        path = tmp_path / "notes" / folder / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\naliases_en: [shared]\n{extra}---\n", encoding="utf-8")
    source = tmp_path / "notes/sources/Example.md"
    source.parent.mkdir()
    source.write_text("shared Skip Merged", encoding="utf-8")
    data = extract(load_config(tmp_path), "notes/sources/Example.md", dry_run=True)
    assert [hit["canonical"] for hit in data["entities"]] == ["First"]


@pytest.mark.parametrize("name", ["missing.md", "wiki/companies/Tesla.md", "raw/invalid.txt", "raw/skip.md", "../outside.md"])
def test_bad_sources_fail_without_writes(wiki_dir, tmp_path, name, capsys):
    make_source(tmp_path, "invalid.txt")
    make_source(tmp_path, "skip.md")
    marker = tmp_path / ".glassgraph"
    marker.mkdir()
    (marker / "config.toml").write_text('[paths]\nexclude=["raw/skip.md"]\n', encoding="utf-8")
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "extract", name]) == 2
    assert capsys.readouterr().err.startswith("glassgraph:")
    assert snapshot(tmp_path) == before
    assert not (marker / "index").exists()


@pytest.mark.parametrize("mode", ["overlap", "parent-file", "cache-directory", "hardlink"])
def test_unsafe_outputs_fail_before_writes(wiki_dir, tmp_path, mode, capsys):
    make_source(tmp_path)
    marker = tmp_path / ".glassgraph"
    marker.mkdir()
    if mode == "overlap":
        (marker / "config.toml").write_text('[paths]\nwiki=".glassgraph"\n', encoding="utf-8")
    elif mode == "parent-file":
        (marker / "cache").write_text("retain", encoding="utf-8")
    elif mode == "cache-directory":
        (marker / "cache/extraction/raw/sample.md.json").mkdir(parents=True)
    else:
        (marker / "index").mkdir()
        os.link(wiki_dir / "companies/Tesla.md", marker / "index/aliases.json")
    before = snapshot(tmp_path)
    assert main(["extract", "raw/sample.md", "--root", str(tmp_path)]) == 2
    assert capsys.readouterr().err.startswith("glassgraph:")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("location", ["raw/sample.md", "wiki/companies/Escape.md", ".glassgraph/index"])
def test_redirected_input_and_output_rejected(wiki_dir, tmp_path, location, capsys):
    make_source(tmp_path)
    external = tmp_path.parent / (tmp_path.name + "-external")
    external.mkdir()
    outside_file = external / "private.md"
    outside_file.write_text("PRIVATE", encoding="utf-8")
    target = tmp_path / location
    # Use a separate source when the tested source name is already present.
    if location == "raw/sample.md":
        target = tmp_path / "raw/redirect.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(external if location.endswith("index") else outside_file,
                          target_is_directory=location.endswith("index"))
    except OSError:
        pytest.skip("Symlink creation is unavailable")
    before = snapshot(tmp_path)
    source = "raw/redirect.md" if location.startswith("raw") else "raw/sample.md"
    assert main(["--root", str(tmp_path), "extract", source]) == 2
    output = capsys.readouterr()
    assert "PRIVATE" not in output.out + output.err
    assert snapshot(tmp_path) == before
    assert list(external.iterdir()) == [outside_file]


@pytest.mark.parametrize("content", ["- pattern: [bad]\n", "[invalid", "wrong: mapping"])
def test_bad_rules_fail_without_state_writes(wiki_dir, tmp_path, content, capsys):
    make_source(tmp_path)
    rules = tmp_path / ".glassgraph/index/disambiguation.yaml"
    rules.parent.mkdir(parents=True)
    rules.write_text(content, encoding="utf-8")
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "extract", "raw/sample.md"]) == 2
    assert capsys.readouterr().err.startswith("glassgraph:")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("root_mode", ["flag", "environment", "marker"])
@pytest.mark.parametrize("entry", ["module", "console"])
def test_installed_command_outside_checkout(wiki_dir, tmp_path, root_mode, entry):
    make_source(tmp_path)
    (tmp_path / ".glassgraph").mkdir()
    nested = tmp_path / "unrelated/deep"
    nested.mkdir(parents=True)
    env = dict(os.environ)
    env.pop("GLASSGRAPH_ROOT", None)
    env.pop("PYTHONPATH", None)
    command = ([sys.executable, "-I", "-B", "-m", "glassgraph"] if entry == "module"
               else [str(Path(sys.executable).parent / "Scripts/glassgraph.exe")]
               if os.name == "nt" else [str(Path(sys.executable).parent / "glassgraph")])
    command += ["extract", "raw/sample.md", "--dry-run"]
    if root_mode == "flag":
        command += ["--root", str(tmp_path)]
    elif root_mode == "environment":
        env["GLASSGRAPH_ROOT"] = str(tmp_path)
    result = subprocess.run(command, cwd=nested, env=env, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["entities"]
    assert list((tmp_path / ".glassgraph").iterdir()) == []


def test_nested_wiki_manifest_uses_vault_relative_paths(tmp_path):
    marker = tmp_path / ".glassgraph"
    marker.mkdir()
    (marker / "config.toml").write_text('[paths]\nwiki="content/wiki"\n', encoding="utf-8")
    page = tmp_path / "content/wiki/companies/Example.md"
    page.parent.mkdir(parents=True)
    page.write_text("Example", encoding="utf-8")
    make_source(tmp_path, text="Example")
    extract(load_config(tmp_path), "raw/sample.md")
    manifest = json.loads((marker / "index/manifest.json").read_text(encoding="utf-8"))
    assert list(manifest["page_shas"]) == [str(Path("content/wiki/companies/Example.md"))]


@pytest.mark.parametrize("field", ["tags: 1", "tags: [1]", "aliases_en: [1]"])
def test_invalid_entity_lists_return_error_without_writes(wiki_dir, tmp_path, field, capsys):
    make_source(tmp_path)
    (wiki_dir / "companies/Tesla.md").write_text(f"---\n{field}\n---\n", encoding="utf-8")
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "extract", "raw/sample.md"]) == 2
    assert "metadata" in capsys.readouterr().err
    assert snapshot(tmp_path) == before


def test_invalid_source_encoding_and_null_path_return_error(wiki_dir, tmp_path, capsys):
    source = make_source(tmp_path)
    source.write_bytes(b"\xff")
    before = snapshot(tmp_path)
    for name in ("raw/sample.md", "raw/\0sample.md"):
        assert main(["--root", str(tmp_path), "extract", name]) == 2
        assert capsys.readouterr().err.startswith("glassgraph:")
        assert snapshot(tmp_path) == before


def test_uppercase_markdown_extension_is_preserved_in_cache(wiki_dir, tmp_path):
    make_source(tmp_path, "sample.MD")
    extract(load_config(tmp_path), "raw/sample.MD")
    assert (tmp_path / ".glassgraph/cache/extraction/raw/sample.MD.json").exists()


def test_case_sensitive_extension_variants_keep_separate_caches(wiki_dir, tmp_path):
    first = make_source(tmp_path, "same.md", "Tesla")
    second = tmp_path / "raw/same.MD"
    if second.exists():
        pytest.skip("The filesystem does not distinguish filename case")
    second.write_text("BYD", encoding="utf-8")
    config = load_config(tmp_path)
    assert extract(config, first)["entities"][0]["canonical"] == "Tesla"
    assert extract(config, second)["entities"][0]["canonical"] == "BYD"
    assert len(list((tmp_path / ".glassgraph/cache/extraction/raw").glob("*.json"))) == 2


@pytest.mark.parametrize("installed", [True, False])
@pytest.mark.parametrize("name", ["index", "linker"])
def test_legacy_imports_outside_checkout(tmp_path, name, installed):
    script = """
import importlib.util, sys, sysconfig
if sys.argv[2] == 'source':
    sys.path.append(sysconfig.get_path('purelib'))
spec = importlib.util.spec_from_file_location('legacy', sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
if sys.argv[3] == 'index':
    assert callable(module.build_index)
    assert module.INDEX_DIR == __import__('pathlib').Path(sys.argv[1]).parent.parent / 'index'
else:
    from glassgraph.core import linker
    assert module.extract_file is linker.extract_file
"""
    args = [sys.executable, "-I", "-B"] + ([] if installed else ["-S"])
    shim = Path(__file__).resolve().parents[1] / f"{name}.py"
    result = subprocess.run(args + ["-c", script, str(shim), "installed" if installed else "source", name],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
