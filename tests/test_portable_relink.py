"""Verify read-only relinking previews and pinned legacy behavior."""
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig

import ahocorasick
import pytest

from glassgraph.cli import main
from glassgraph.config import load_config
from glassgraph.core import relink as transformer, source_sections
from glassgraph.extraction import relink


FIXTURE = Path(__file__).parent / "fixtures/relink/v1/cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
            for path in root.rglob("*")}


def source_fixture(root, body=None, *, newline="\n", bom=False, header=True):
    body = CASES[0]["body"] if body is None else body
    prefix = "---\ntype: source\nsummary: Keep Tesla and SiC MOSFET.\n---\n" if header else ""
    text = (("\ufeff" if bom else "") + prefix + body).replace("\n", newline)
    source = root / "wiki/sources/clip.md"
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(text.encode("utf-8"))
    return source, text


def write_rules(root, text):
    rules = root / ".glassgraph/index/disambiguation.yaml"
    rules.parent.mkdir(parents=True, exist_ok=True)
    rules.write_text(text, encoding="utf-8")
    return rules


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_pinned_primitive_and_idempotence(case):
    automaton = ahocorasick.Automaton()
    for alias, canonical in [("Tesla", "Tesla"), ("BYD", "BYD"), ("SiC MOSFET", "SiC-MOSFET"), ("特斯拉", "Tesla")]:
        automaton.add_word(alias, (canonical, alias))
    automaton.make_automaton()
    actual = transformer.relink_bullets(case["body"], automaton, case["patterns"])
    assert actual == case["expected"]
    assert transformer.relink_bullets(actual, automaton, case["patterns"]) == actual


@pytest.mark.parametrize("newline", ["\n", "\r\n"])
@pytest.mark.parametrize("bom", [False, True])
@pytest.mark.parametrize("header", [False, True])
def test_preview_preserves_prefix_and_line_endings(wiki_dir, tmp_path, newline, bom, header, capsys):
    source, text = source_fixture(tmp_path, newline=newline, bom=bom, header=header)
    before = snapshot(tmp_path)
    prefix = text[:-len(CASES[0]["body"].replace("\n", newline))]
    expected = prefix + CASES[0]["expected"].replace("\n", newline)
    assert relink(load_config(tmp_path), source) == expected
    assert main(["--root", str(tmp_path), "relink", "wiki/sources/clip.md"]) == 0
    assert capsys.readouterr().out == expected
    assert snapshot(tmp_path) == before
    assert not (tmp_path / ".glassgraph").exists()


def test_empty_body_and_missing_final_newline(wiki_dir, tmp_path):
    source, text = source_fixture(tmp_path, body="")
    assert relink(load_config(tmp_path), source) == text
    source, _ = source_fixture(tmp_path, body=CASES[0]["body"].rstrip("\n"))
    assert relink(load_config(tmp_path), source).endswith(CASES[0]["expected"].rstrip("\n"))
    assert not relink(load_config(tmp_path), source).endswith("\n")


def test_unchanged_preview_is_success(wiki_dir, tmp_path, capsys):
    source, text = source_fixture(tmp_path, body="# Notes\nTesla stays outside.\n")
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "relink", str(source)]) == 0
    assert capsys.readouterr().out == text
    assert snapshot(tmp_path) == before


def test_unused_derived_state_is_not_accessed(wiki_dir, tmp_path):
    source_fixture(tmp_path)
    marker = tmp_path / ".glassgraph"
    (marker / "index").mkdir(parents=True)
    (marker / "index/manifest.json").mkdir()
    (marker / "index/aliases.json").write_bytes(b"\xff")
    (marker / "cache").write_text("retain", encoding="utf-8")
    legacy = tmp_path / ".tools/index/aliases.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"\xff")
    before = snapshot(tmp_path)
    assert "[[SiC-MOSFET|SiC MOSFET]]" in relink(load_config(tmp_path), "wiki/sources/clip.md")
    assert snapshot(tmp_path) == before


def test_current_source_aliases_and_rules_are_read(wiki_dir, tmp_path):
    source, _ = source_fixture(tmp_path, body="## Key extractions\n### Companies mentioned\n- [[BYD]] — TSLA cars.\n")
    config = load_config(tmp_path)
    assert "[[Tesla|TSLA]]" in relink(config, source)
    (wiki_dir / "companies/Tesla.md").write_text("---\naliases_en: []\n---\n", encoding="utf-8")
    assert "[[Tesla|TSLA]]" not in relink(config, source)
    source.write_text(CASES[3]["body"], encoding="utf-8")
    assert "[[Tesla]] coil" in relink(config, source)
    write_rules(tmp_path, "- pattern: Tesla coil\n")
    assert "Tesla coil" in relink(config, source)
    assert "[[Tesla]] coil" not in relink(config, source)
    assert "[[Tesla]] cars" in relink(config, source)


def test_custom_paths_order_and_exclusions(tmp_path):
    marker = tmp_path / ".glassgraph"
    marker.mkdir()
    (marker / "config.toml").write_text(
        '[paths]\nwiki="content/notes"\nraw="clippings"\nentity_dirs=["custom","companies"]\n'
        'exclude=["content/notes/custom/Excluded.md"]\n', encoding="utf-8")
    for folder, name, alias in [("custom", "First", "shared"), ("companies", "Second", "shared"),
                                 ("custom", "Excluded", "Hidden")]:
        path = tmp_path / "content/notes" / folder / f"{name}.md"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"---\naliases_en: [{alias}]\n---\n", encoding="utf-8")
    source = tmp_path / "content/notes/sources/clip.md"
    source.parent.mkdir()
    source.write_text("## Key extractions\n### Companies mentioned\n- [[Other]] — shared and Hidden.\n", encoding="utf-8")
    before = snapshot(tmp_path)
    actual = relink(load_config(tmp_path), "content/notes/sources/clip.md")
    assert "[[First|shared]]" in actual and "[[Second" not in actual and "[[Excluded" not in actual
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("name", ["raw/clip.md", "missing.md", "wiki/companies/Tesla.md", "wiki/sources/skip.md", "../outside.md"])
def test_bad_scope_produces_no_preview(wiki_dir, tmp_path, name, capsys):
    source_fixture(tmp_path)
    (tmp_path / "raw").mkdir()
    (tmp_path / "raw/clip.md").write_text(CASES[0]["body"], encoding="utf-8")
    (wiki_dir / "sources/skip.md").write_text(CASES[0]["body"], encoding="utf-8")
    marker = tmp_path / ".glassgraph"
    marker.mkdir()
    (marker / "config.toml").write_text('[paths]\nexclude=["wiki/sources/skip.md"]\n', encoding="utf-8")
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "relink", name]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err.startswith("glassgraph:")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("text", ["---\nunclosed", "---\nx: [bad\n---\nBody", "---\nx: !!bool maybe\n---\nBody",
                                  "---\nx: !!timestamp wrong\n---\nBody", "---\nx: !!int ''\n---\nBody"] +
                                 [f"---\nx: bad{control}\n---\nBody" for control in ("\x00", "\x01", "\x7f", "\ufffe")])
def test_frontmatter_failures_have_no_partial_preview(wiki_dir, tmp_path, text, capsys):
    source, _ = source_fixture(tmp_path)
    source.write_text(text, encoding="utf-8")
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "relink", str(source)]) == 2
    output = capsys.readouterr()
    assert output.out == "" and "frontmatter" in output.err
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("rules", ["[invalid", "false", "- pattern: !!bool maybe"])
def test_bad_rules_have_no_partial_preview(wiki_dir, tmp_path, rules, capsys):
    source, _ = source_fixture(tmp_path)
    write_rules(tmp_path, rules)
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "relink", str(source)]) == 2
    assert capsys.readouterr().out == ""
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("failure", ["source", "entity", "rules", "directory", "utf8"])
def test_read_failures_have_no_partial_preview(wiki_dir, tmp_path, failure, monkeypatch, capsys):
    source, _ = source_fixture(tmp_path)
    rules = write_rules(tmp_path, "[]")
    if failure == "utf8":
        source.write_bytes(b"\xff")
    before = snapshot(tmp_path)
    target = {"source": source, "entity": wiki_dir / "companies/Tesla.md", "rules": rules,
              "directory": wiki_dir / "companies", "utf8": source}[failure]
    attribute = "iterdir" if failure == "directory" else "open"
    original = getattr(Path, attribute)

    def denied(path, *args, **kwargs):
        if failure != "utf8" and path == target:
            raise PermissionError("Cannot read preview input")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, attribute, denied)
        assert main(["--root", str(tmp_path), "relink", str(source)]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err.startswith("glassgraph:")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("location", ["source", "entity", "rules"])
def test_external_redirects_are_rejected(wiki_dir, tmp_path, location, capsys):
    source_fixture(tmp_path)
    outside = tmp_path.parent / (tmp_path.name + "-external.md")
    outside.write_text("PRIVATE", encoding="utf-8")
    rules = tmp_path / ".glassgraph/index/disambiguation.yaml"
    target = {"source": wiki_dir / "sources/redirect.md", "entity": wiki_dir / "companies/Redirect.md", "rules": rules}[location]
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        target.symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is unavailable")
    before = snapshot(tmp_path)
    source = "wiki/sources/redirect.md" if location == "source" else "wiki/sources/clip.md"
    assert main(["--root", str(tmp_path), "relink", source]) == 2
    output = capsys.readouterr()
    assert output.out == "" and "PRIVATE" not in output.err
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("mode", ["flag", "environment", "marker"])
@pytest.mark.parametrize("entry", ["module", "console"])
def test_installed_command_preserves_utf8_and_crlf_bytes(wiki_dir, tmp_path, mode, entry):
    _, text = source_fixture(tmp_path, newline="\r\n", bom=True)
    (tmp_path / ".glassgraph").mkdir()
    nested = tmp_path / "unrelated/deep"
    nested.mkdir(parents=True)
    before = snapshot(tmp_path)
    env = dict(os.environ)
    env.pop("GLASSGRAPH_ROOT", None)
    env.pop("PYTHONPATH", None)
    command = ([sys.executable, "-I", "-B", "-m", "glassgraph"] if entry == "module" else
               [str(Path(sysconfig.get_path("scripts")) / ("glassgraph.exe" if os.name == "nt" else "glassgraph"))])
    command += ["relink", "wiki/sources/clip.md"]
    if mode == "flag":
        command += ["--root", str(tmp_path)]
    elif mode == "environment":
        env["GLASSGRAPH_ROOT"] = str(tmp_path)
    result = subprocess.run(command, cwd=nested, env=env, capture_output=True)
    assert result.returncode == 0, result.stderr
    prefix = text[:-len(CASES[0]["body"].replace("\n", "\r\n"))]
    assert result.stdout == (prefix + CASES[0]["expected"].replace("\n", "\r\n")).encode("utf-8")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("installed", [True, False])
def test_legacy_import_and_shared_patterns_outside_checkout(tmp_path, installed):
    script = """
import importlib.abc, importlib.util, sys, sysconfig
if sys.argv[2] == 'source':
    sys.path.append(sysconfig.get_path('purelib'))
    class BlockInstalledPackage(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == 'glassgraph':
                raise ModuleNotFoundError('Require the checkout bootstrap', name='glassgraph')
    sys.meta_path.insert(0, BlockInstalledPackage())
from pathlib import Path
for name in ('relink', 'relations'):
    spec = importlib.util.spec_from_file_location(name, Path(sys.argv[1]) / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    if name == 'relink':
        from glassgraph.core import relink
        assert module.relink_bullets is relink.relink_bullets
    else:
        from glassgraph.core import source_sections
        assert module._KEYX_RE is source_sections.KEY_EXTRACTIONS_RE
        assert module._BULLET_RE is source_sections.BULLET_RE
if sys.argv[2] == 'source':
    assert Path(relink.__file__).resolve() == Path(sys.argv[1]).resolve() / 'src/glassgraph/core/relink.py'
"""
    arguments = [sys.executable, "-I", "-B"] + ([] if installed else ["-S"])
    repo = Path(__file__).resolve().parents[1]
    result = subprocess.run(arguments + ["-c", script, str(repo), "installed" if installed else "source"],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr


def test_apply_option_is_not_available(wiki_dir, tmp_path, capsys):
    source_fixture(tmp_path)
    before = snapshot(tmp_path)
    with pytest.raises(SystemExit) as error:
        main(["--root", str(tmp_path), "relink", "wiki/sources/clip.md", "--apply"])
    assert error.value.code == 2
    assert capsys.readouterr().out == ""
    assert snapshot(tmp_path) == before
