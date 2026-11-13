"""Check lookup compatibility, owner provenance, and read-only execution."""
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig

import pytest

from glassgraph.cli import main
from glassgraph.config import load_config
from glassgraph.core import index
from glassgraph.core.lookup import lookup


FIXTURE = Path(__file__).parent / "fixtures/lookup/v1"
CASES = json.loads((FIXTURE / "cases.json").read_text(encoding="utf-8"))


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
            for path in root.rglob("*")}


def config_file(root, text):
    marker = root / ".glassgraph"
    marker.mkdir(exist_ok=True)
    (marker / "config.toml").write_text(text, encoding="utf-8")


def page(root, folder, stem, aliases, extra=""):
    target = root / "wiki" / folder / f"{stem}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(f"---\naliases_en: {json.dumps(aliases)}\n{extra}---\n", encoding="utf-8")
    return target


@pytest.mark.parametrize("case", CASES, ids=lambda case: case["name"])
def test_pinned_lookup_report_and_status(wiki_dir, tmp_path, case, capsys):
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "lookup", case["name"]]) == case["exit_code"]
    expected = case["stdout"]
    if case["page"]:
        expected = expected.replace("{PAGE}", str(wiki_dir / case["page"]))
    assert capsys.readouterr().out == expected
    assert snapshot(tmp_path) == before
    assert not (tmp_path / ".glassgraph").exists()


def test_alias_serialization_matches_pinned_baseline(wiki_dir):
    _, _, aliases = index.compile_index(wiki_dir)
    assert json.dumps(aliases, indent=2, ensure_ascii=False) == (FIXTURE / "aliases.json").read_text(encoding="utf-8")
    assert aliases == {alias: owner.page.stem for alias, owner in index.alias_owners(wiki_dir).items()}


def test_unused_derived_state_is_not_read_or_changed(wiki_dir, tmp_path):
    marker = tmp_path / ".glassgraph"
    marker.mkdir()
    (marker / "index").write_bytes(b"\xff")
    (marker / "cache").write_text("retain", encoding="utf-8")
    legacy = tmp_path / ".tools/index/aliases.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b"\xff")
    before = snapshot(tmp_path)
    status, report = lookup(load_config(tmp_path), "TSLA")
    assert status == 0 and str(wiki_dir / "companies/Tesla.md") in report
    assert snapshot(tmp_path) == before


def test_exact_and_lowercase_collision_order(tmp_path):
    first = page(tmp_path, "companies", "First", ["Alpha", "shared"])
    second = page(tmp_path, "technologies", "Second", ["alpha", "shared"])
    config = load_config(tmp_path)
    for name, owner in [("Alpha", first), ("alpha", second), ("ALPHA", second), ("shared", first)]:
        status, report = lookup(config, name)
        assert status == 0 and report.rstrip().endswith(str(owner))
    config_file(tmp_path, '[paths]\nentity_dirs=["technologies","companies"]\n')
    assert lookup(load_config(tmp_path), "shared")[1].rstrip().endswith(str(second))
    assert lookup(load_config(tmp_path), "ALPHA")[1].rstrip().endswith(str(first))


@pytest.mark.parametrize("mode", ["normal", "merged", "excluded"])
def test_equal_stems_keep_actual_alias_owner(tmp_path, mode):
    first = page(tmp_path, "companies", "Same", ["OnlyCompany"], "tags: [merged]\n" if mode == "merged" else "")
    second = page(tmp_path, "technologies", "Same", ["OnlyTech"])
    if mode == "excluded":
        config_file(tmp_path, '[paths]\nexclude=["wiki/companies/Same.md"]\n')
    config = load_config(tmp_path)
    assert lookup(config, "OnlyTech") == (0, f"Same | technology | {second}\n")
    if mode == "normal":
        assert lookup(config, "Same") == (0, f"Same | company | {first}\n")
    else:
        assert lookup(config, "OnlyCompany")[0] == 1
        assert lookup(config, "Same")[1].rstrip().endswith(str(second))


def test_current_alias_edits_are_visible(wiki_dir, tmp_path):
    config = load_config(tmp_path)
    assert lookup(config, "TSLA")[0] == 0
    (wiki_dir / "companies/Tesla.md").write_text("---\naliases_en: [NovelAlias]\n---\n", encoding="utf-8")
    assert lookup(config, "TSLA")[0] == 1
    assert lookup(config, "NovelAlias")[0] == 0


def test_custom_alias_and_type_share_one_page_version(tmp_path, monkeypatch):
    from glassgraph.core import frontmatter

    config_file(tmp_path, '[paths]\nentity_dirs=["custom"]\n')
    target = page(tmp_path, "custom", "Example", ["OldAlias"], "type: company\n")
    config = load_config(tmp_path)
    original = frontmatter.parse_file
    reads = []

    def changing_page(path):
        if path != target:
            return original(path)
        reads.append(path)
        if len(reads) == 1:
            return frontmatter.parse("---\ntype: company\naliases_en: [OldAlias]\n---\n")
        return frontmatter.parse("---\ntype: product\naliases_en: [NewAlias]\n---\n")

    monkeypatch.setattr(frontmatter, "parse_file", changing_page)
    assert lookup(config, "OldAlias") == (0, f"Example | company | {target}\n")
    assert len(reads) == 1
    assert lookup(config, "NewAlias") == (0, f"Example | product | {target}\n")
    assert len(reads) == 2
    assert lookup(config, "OldAlias")[0] == 1


@pytest.mark.parametrize("kind", ["company", "technology", "product", "market", "theme"])
def test_custom_folder_declared_type(tmp_path, kind):
    config_file(tmp_path, '[paths]\nwiki="content/notes"\nentity_dirs=["custom"]\n')
    target = tmp_path / "content/notes/custom/Example.md"
    target.parent.mkdir(parents=True)
    target.write_text(f"---\ntype: {kind}\naliases_en: [Alias]\n---\n", encoding="utf-8")
    before = snapshot(tmp_path)
    assert lookup(load_config(tmp_path), "Alias") == (0, f"Example | {kind} | {target}\n")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("declaration", ["", "type: source\n", "type: unknown\n", "type: [company]\n"])
def test_unsupported_custom_type_is_error_without_report(tmp_path, declaration, capsys):
    config_file(tmp_path, '[paths]\nentity_dirs=["custom"]\n')
    page(tmp_path, "custom", "Example", ["Alias"], declaration)
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "lookup", "Alias"]) == 2
    output = capsys.readouterr()
    assert output.out == "" and "supported entity type" in output.err
    assert snapshot(tmp_path) == before


def test_default_folder_type_and_lowercase_semantics_are_preserved(tmp_path):
    target = page(tmp_path, "Companies", "Example", ["Straße"], "type: technology\n")
    config_file(tmp_path, '[paths]\nentity_dirs=["Companies"]\n')
    config = load_config(tmp_path)
    assert lookup(config, "Example") == (0, f"Example | company | {target}\n")
    assert lookup(config, "STRASSE")[0] == 1


def test_missing_wiki_is_error(tmp_path, capsys):
    assert main(["--root", str(tmp_path), "lookup", "Example"]) == 2
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize("failure", ["directory", "file", "stat", "utf8"])
def test_read_errors_do_not_emit_partial_report(wiki_dir, tmp_path, failure, monkeypatch, capsys):
    target = wiki_dir / "companies/Tesla.md"
    if failure == "utf8":
        target.write_bytes(b"\xff")
    before = snapshot(tmp_path)
    if failure == "directory":
        attribute, blocked = "iterdir", wiki_dir / "companies"
    else:
        attribute, blocked = ("stat" if failure == "stat" else "open"), target
    original = getattr(Path, attribute)

    def denied(path, *args, **kwargs):
        if failure != "utf8" and path == blocked:
            raise PermissionError("Cannot read lookup input")
        return original(path, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(Path, attribute, denied)
        assert main(["--root", str(tmp_path), "lookup", "Tesla"]) == 2
    output = capsys.readouterr()
    assert output.out == "" and output.err.startswith("glassgraph:")
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("location", ["file", "directory"])
def test_external_entity_redirection_is_rejected(wiki_dir, tmp_path, location, capsys):
    outside = tmp_path.parent / (tmp_path.name + "-external")
    outside.mkdir()
    (outside / "Private.md").write_text("PRIVATE", encoding="utf-8")
    target = wiki_dir / ("companies/External.md" if location == "file" else "external")
    try:
        target.symlink_to(outside / "Private.md" if location == "file" else outside,
                          target_is_directory=location == "directory")
    except OSError:
        pytest.skip("Symlink creation is unavailable")
    if location == "directory":
        config_file(tmp_path, '[paths]\nentity_dirs=["external"]\n')
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "lookup", "Tesla"]) == 2
    output = capsys.readouterr()
    assert output.out == "" and "PRIVATE" not in output.err
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("mode", ["flag", "environment", "marker"])
@pytest.mark.parametrize("entry", ["module", "console"])
def test_installed_command_outside_checkout(wiki_dir, tmp_path, mode, entry):
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
    command += ["lookup", "特斯拉"]
    if mode == "flag":
        command += ["--root", str(tmp_path)]
    elif mode == "environment":
        env["GLASSGRAPH_ROOT"] = str(tmp_path)
    result = subprocess.run(command, cwd=nested, env=env, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"Tesla | company | {wiki_dir / 'companies/Tesla.md'}\n"
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("installed", [True, False])
def test_legacy_lookup_invocation_outside_checkout(wiki_dir, tmp_path, installed):
    script = """
import importlib.abc, importlib.util, sys, sysconfig
if sys.argv[4] == 'source':
    sys.path.append(sysconfig.get_path('purelib'))
    class BlockInstalledPackage(importlib.abc.MetaPathFinder):
        def find_spec(self, fullname, path=None, target=None):
            if fullname == 'glassgraph':
                raise ModuleNotFoundError('Require the checkout bootstrap', name='glassgraph')
    sys.meta_path.insert(0, BlockInstalledPackage())
spec = importlib.util.spec_from_file_location('legacy_link', sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
from pathlib import Path
assert module.run_lookup('TSLA', wiki_root=Path(sys.argv[2]), index_dir=Path(sys.argv[3])) == 0
from glassgraph.core import lookup
if sys.argv[4] == 'source':
    assert Path(lookup.__file__).resolve() == Path(sys.argv[1]).resolve().parent / 'src/glassgraph/core/lookup.py'
"""
    args = [sys.executable, "-I", "-B"] + ([] if installed else ["-S"])
    shim = Path(__file__).resolve().parents[1] / "link.py"
    result = subprocess.run(args + ["-c", script, str(shim), str(wiki_dir), str(tmp_path / "legacy-index"),
                                    "installed" if installed else "source"],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert result.stdout == f"Tesla | company | {wiki_dir / 'companies/Tesla.md'}\n"
