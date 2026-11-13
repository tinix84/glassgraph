"""Verify installed read-only explanation and pinned report compatibility."""
import os
from pathlib import Path
import subprocess
import sys
import sysconfig

import pytest

from glassgraph.cli import main
from glassgraph.config import load_config
from glassgraph.extraction import explain


FIXTURE = Path(__file__).parent / "fixtures/explain/v1"


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None
            for p in root.rglob("*")}


def source_fixture(root, *, with_rules=True):
    source = root / "raw/sample.md"
    source.parent.mkdir(exist_ok=True)
    source.write_bytes((FIXTURE / "source.md").read_bytes())
    rules = root / ".glassgraph/index/disambiguation.yaml"
    rules.parent.mkdir(parents=True)
    if with_rules:
        rules.write_bytes((FIXTURE / "disambiguation.yaml").read_bytes())
    return source


@pytest.mark.parametrize("name,options", [
    ("default", {}), ("filter", {"filter_canonical": "Tesla"}),
    ("suppressed", {"show_suppressed": True}), ("context-zero", {"context_chars": 0}),
    ("context-short", {"context_chars": 5}),
])
def test_report_matches_pinned_formatter(wiki_dir, tmp_path, name, options):
    source = source_fixture(tmp_path)
    before = snapshot(tmp_path)
    expected = (FIXTURE / f"{name}.txt").read_text(encoding="utf-8")
    assert explain(load_config(tmp_path), source, **options) == expected
    assert snapshot(tmp_path) == before


def test_cli_report_options_and_no_existing_derived_state(wiki_dir, tmp_path, capsys):
    source = tmp_path / "raw/sample.md"
    source.parent.mkdir()
    source.write_text("Tesla and BYD", encoding="utf-8")
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "explain", "raw/sample.md", "--filter", "Tesla", "--context", "0"]) == 0
    output = capsys.readouterr()
    assert output.err == ""
    assert "→ Tesla" in output.out and "→ BYD" not in output.out
    assert "[0:5]" in output.out
    assert snapshot(tmp_path) == before
    assert not (tmp_path / ".glassgraph").exists()


def test_readonly_command_ignores_unwritable_unused_output_paths(wiki_dir, tmp_path):
    source_fixture(tmp_path)
    (tmp_path / ".glassgraph/index/manifest.json").mkdir()
    (tmp_path / ".glassgraph/cache").write_text("retain", encoding="utf-8")
    legacy = tmp_path / ".tools/index/aliases.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text("legacy state", encoding="utf-8")
    before = snapshot(tmp_path)
    assert "[0:5]" not in explain(load_config(tmp_path), "raw/sample.md")
    assert snapshot(tmp_path) == before


def test_current_source_alias_and_rules_are_read_each_time(wiki_dir, tmp_path):
    source = source_fixture(tmp_path)
    config = load_config(tmp_path)
    assert "[0:5]" not in explain(config, source)
    source.write_text("TSLA", encoding="utf-8")
    assert "→ Tesla" in explain(config, source)
    (wiki_dir / "companies/Tesla.md").write_text("---\naliases_en: [NewName]\n---\n", encoding="utf-8")
    assert "0 hits" in explain(config, source)
    source.write_text("Tesla coil", encoding="utf-8")
    assert "0 hits" in explain(config, source)
    (tmp_path / ".glassgraph/index/disambiguation.yaml").write_text("[]", encoding="utf-8")
    assert "→ Tesla" in explain(config, source)


def test_configured_entity_order_and_exclusions(tmp_path):
    marker = tmp_path / ".glassgraph"
    marker.mkdir()
    (marker / "config.toml").write_text(
        '[paths]\nwiki="content/notes"\nraw="clippings"\nentity_dirs=["custom","companies"]\n'
        'exclude=["content/notes/custom/Skip.md"]\n', encoding="utf-8")
    for folder, name in [("custom", "First"), ("companies", "Second"), ("custom", "Skip")]:
        page = tmp_path / "content/notes" / folder / f"{name}.md"
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text("---\naliases_en: [shared]\n---\n", encoding="utf-8")
    source = tmp_path / "content/notes/sources/sample.md"
    source.parent.mkdir()
    source.write_text("shared Skip", encoding="utf-8")
    before = snapshot(tmp_path)
    report = explain(load_config(tmp_path), "content/notes/sources/sample.md")
    assert "→ First" in report and "→ Second" not in report and "→ Skip" not in report
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("source", ["missing.md", "wiki/companies/Tesla.md", "raw/no.txt", "raw/skip.md", "../outside.md", "raw/\0bad.md"])
def test_invalid_sources_return_error_without_report(wiki_dir, tmp_path, source, capsys):
    source_fixture(tmp_path)
    (tmp_path / "raw/no.txt").write_text("Tesla", encoding="utf-8")
    (tmp_path / "raw/skip.md").write_text("Tesla", encoding="utf-8")
    (tmp_path / ".glassgraph/config.toml").write_text('[paths]\nexclude=["raw/skip.md"]\n', encoding="utf-8")
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "explain", source]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err.startswith("glassgraph:")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("target,content", [
    ("raw/sample.md", b"\xff"),
    (".glassgraph/index/disambiguation.yaml", b"[invalid"),
    (".glassgraph/index/disambiguation.yaml", b"- pattern: 2"),
    (".glassgraph/index/disambiguation.yaml", b"false"),
    (".glassgraph/index/disambiguation.yaml", b"0"),
    (".glassgraph/index/disambiguation.yaml", b"{}"),
    (".glassgraph/index/disambiguation.yaml", b"''"),
    (".glassgraph/index/disambiguation.yaml", b"null"),
    (".glassgraph/index/disambiguation.yaml", b"~"),
    (".glassgraph/index/disambiguation.yaml", b"- pattern: 2026-02-31"),
    (".glassgraph/index/disambiguation.yaml", b"- pattern: !!bool maybe"),
    (".glassgraph/index/disambiguation.yaml", b"- pattern: !!timestamp wrong"),
    (".glassgraph/index/disambiguation.yaml", b"- pattern: !!int ''"),
])
def test_read_errors_return_no_partial_report(wiki_dir, tmp_path, target, content, capsys):
    source_fixture(tmp_path)
    (tmp_path / target).write_bytes(content)
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "explain", "raw/sample.md"]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err.startswith("glassgraph:")
    assert snapshot(tmp_path) == before


def test_negative_context_returns_error_without_writes(wiki_dir, tmp_path, capsys):
    source_fixture(tmp_path)
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "explain", "raw/sample.md", "--context", "-1"]) == 2
    output = capsys.readouterr()
    assert output.out == "" and "nonnegative" in output.err
    assert snapshot(tmp_path) == before


def test_nonnumeric_context_is_an_argument_error(wiki_dir, tmp_path, capsys):
    source_fixture(tmp_path)
    before = snapshot(tmp_path)
    with pytest.raises(SystemExit) as error:
        main(["--root", str(tmp_path), "explain", "raw/sample.md", "--context", "bad"])
    assert error.value.code == 2
    assert capsys.readouterr().out == ""
    assert snapshot(tmp_path) == before


def test_empty_dictionary_reports_no_hits_without_state(tmp_path):
    (tmp_path / "wiki").mkdir()
    source_fixture(tmp_path, with_rules=False)
    before = snapshot(tmp_path)
    assert explain(load_config(tmp_path), "raw/sample.md") == (
        "\nSummary: 0 hits, 0 unique canonicals, 0 disambiguation warnings\n")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("content", ["[invalid", "false", "0", "{}", "''"])
def test_legacy_formatter_keeps_lenient_rule_default(wiki_dir, tmp_path, explain_mod, content):
    from glassgraph.core.index import compile_index

    source = source_fixture(tmp_path)
    rules = tmp_path / ".glassgraph/index/disambiguation.yaml"
    rules.write_text(content, encoding="utf-8")
    automaton, _, _ = compile_index(wiki_dir)
    assert "[0:5]" in explain_mod.explain_file(source, automaton, disambiguation_yaml=rules)


@pytest.mark.parametrize("content", ["", "# no rules\n", "[]"])
def test_empty_rules_remain_valid(wiki_dir, tmp_path, content):
    source = source_fixture(tmp_path)
    rules = tmp_path / ".glassgraph/index/disambiguation.yaml"
    rules.write_text(content, encoding="utf-8")
    before = snapshot(tmp_path)
    assert "[0:5]" in explain(load_config(tmp_path), source)
    assert snapshot(tmp_path) == before


def test_unreadable_entity_directory_is_a_read_error(wiki_dir, tmp_path, monkeypatch, capsys):
    source_fixture(tmp_path)
    before = snapshot(tmp_path)
    original = Path.iterdir

    def denied(path):
        if Path(path) == wiki_dir / "companies":
            raise PermissionError("Cannot read the entity directory")
        return original(path)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "iterdir", denied)
        assert main(["--root", str(tmp_path), "explain", "raw/sample.md"]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err.startswith("glassgraph:")
    assert snapshot(tmp_path) == before


def test_unreadable_optional_rules_are_a_read_error(wiki_dir, tmp_path, monkeypatch, capsys):
    source_fixture(tmp_path)
    before = snapshot(tmp_path)
    rules = tmp_path / ".glassgraph/index/disambiguation.yaml"
    original = Path.open

    def denied(path, *args, **kwargs):
        if path == rules:
            raise PermissionError("Cannot read the rule file")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, "open", denied)
        assert main(["--root", str(tmp_path), "explain", "raw/sample.md"]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err.startswith("glassgraph:")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("location", ["source", "entity", "rules"])
def test_redirected_reads_stay_inside_vault(wiki_dir, tmp_path, location, capsys):
    source_fixture(tmp_path, with_rules=location != "rules")
    outside = tmp_path.parent / (tmp_path.name + "-private.md")
    outside.write_text("PRIVATE", encoding="utf-8")
    target = {"source": tmp_path / "raw/redirect.md", "entity": wiki_dir / "companies/Redirect.md",
              "rules": tmp_path / ".glassgraph/index/disambiguation.yaml"}[location]
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is unavailable")
    before = snapshot(tmp_path)
    source = "raw/redirect.md" if location == "source" else "raw/sample.md"
    assert main(["--root", str(tmp_path), "explain", source]) == 2
    output = capsys.readouterr()
    assert output.out == "" and "PRIVATE" not in output.err
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("mode", ["flag", "environment", "marker"])
@pytest.mark.parametrize("entry", ["module", "console"])
def test_installed_command_outside_checkout(wiki_dir, tmp_path, mode, entry):
    source_fixture(tmp_path)
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
    command += ["explain", "raw/sample.md", "--suppressed", "--context", "5"]
    if mode == "flag":
        command += ["--root", str(tmp_path)]
    elif mode == "environment":
        env["GLASSGRAPH_ROOT"] = str(tmp_path)
    result = subprocess.run(command, cwd=nested, env=env, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert "SUPPRESSED" in result.stdout and "→ BYD" in result.stdout
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("installed", [True, False])
def test_legacy_file_import_outside_checkout(tmp_path, installed):
    script = """
import importlib.abc, importlib.util, sys, sysconfig
if sys.argv[2] == 'source':
    sys.path.append(sysconfig.get_path('purelib'))
    class BlockInstalledPackage(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == 'glassgraph':
                raise ModuleNotFoundError('Require the checkout bootstrap', name='glassgraph')
    sys.meta_path.insert(0, BlockInstalledPackage())
spec = importlib.util.spec_from_file_location('legacy_explain', sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
from glassgraph.core import explain
assert module.explain_file is explain.explain_file
assert module.format_hit('Tesla', 0, 4, 'Tesla', 'Tesla').startswith('[0:5]')
if sys.argv[2] == 'source':
    from pathlib import Path
    assert '_glassgraph_explain_bootstrap' in sys.modules
    assert Path(explain.__file__).resolve() == Path(sys.argv[1]).resolve().parent / 'src/glassgraph/core/explain.py'
"""
    arguments = [sys.executable, "-I", "-B"] + ([] if installed else ["-S"])
    shim = Path(__file__).resolve().parents[1] / "explain.py"
    result = subprocess.run(arguments + ["-c", script, str(shim), "installed" if installed else "source"],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
