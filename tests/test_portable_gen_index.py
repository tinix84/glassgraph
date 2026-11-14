"""Verify catalog bytes, portable scans and read-only CLI behavior."""
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
from glassgraph.wiki.gen_index import IndexError_, generate


FIXTURE = Path(__file__).parent / "fixtures/gen_index/v1"
EXPECTED = (FIXTURE / "expected.md").read_bytes()


def page(path, meta):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("---\n" + json.dumps(meta, ensure_ascii=False) + "\n---\nBody.\n", encoding="utf-8")


def vault(root):
    shutil.copytree(FIXTURE / "wiki", root / "wiki")
    return load_config(root)


def settings(root, text):
    marker = root / ".glassgraph"
    marker.mkdir(exist_ok=True)
    (marker / "config.toml").write_text(text, encoding="utf-8")


def snapshot(root):
    return {str(path.relative_to(root)): path.read_bytes() if path.is_file() else None
            for path in root.rglob("*")}


def test_pinned_catalog_and_no_writes(tmp_path, capsys):
    config = vault(tmp_path)
    (config.wiki / "index.md").write_bytes(b"retain existing index")
    before = snapshot(tmp_path)
    assert generate(config.wiki).encode("utf-8") == EXPECTED
    assert generate(config.wiki, config=config).encode("utf-8") == EXPECTED
    assert main(["--root", str(tmp_path), "gen-index"]) == 0
    assert capsys.readouterr().out.encode("utf-8") == EXPECTED
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("entry", ["module", "console"])
@pytest.mark.parametrize("root_mode", ["flag", "environment", "upward"])
def test_installed_from_unrelated_directory(tmp_path, entry, root_mode):
    root = tmp_path / "vault"
    root.mkdir()
    vault(root)
    settings(root, "")
    unrelated = tmp_path / "elsewhere"
    unrelated.mkdir()
    nested = root / "nested/child"
    nested.mkdir(parents=True)
    command = ([sys.executable, "-m", "glassgraph"] if entry == "module" else
               [str(Path(sysconfig.get_path("scripts")) / ("glassgraph.exe" if os.name == "nt" else "glassgraph"))])
    env = os.environ.copy()
    env.pop("GLASSGRAPH_ROOT", None)
    env.pop("PYTHONPATH", None)
    if root_mode == "environment":
        env["GLASSGRAPH_ROOT"] = str(root)
    command += ["gen-index"]
    if root_mode == "flag":
        env["GLASSGRAPH_ROOT"] = str(unrelated)
        command += ["--root", str(root)]
    before = snapshot(root)
    result = subprocess.run(command, cwd=nested if root_mode == "upward" else unrelated,
                            env=env, capture_output=True)
    assert result.returncode == 0, result.stderr.decode("utf-8")
    assert result.stdout == EXPECTED
    assert not result.stderr
    assert snapshot(root) == before


def test_configured_inputs_and_scan_order(tmp_path):
    settings(tmp_path, '[paths]\nwiki="catalog"\nentity_dirs=["custom", "Companies"]\n'
                       'exclude=["catalog/custom/Ignore.md", "catalog/sources/Ignore.md"]\n')
    wiki = tmp_path / "catalog"
    page(wiki / "custom/A.md", {"type": "company", "summary": "first"})
    page(wiki / "custom/B.md", {"type": "technology", "tags": "stub"})
    page(wiki / "Companies/C.md", {"type": "theme", "summary": "second"})
    for name in ("custom/Ignore.md", "sources/Ignore.md", "products/Unused.md", "custom/nested/Unused.md"):
        path = wiki / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("---\nbad: [\n---\n", encoding="utf-8")
    (wiki / "custom/not-a-file.md").mkdir()
    page(wiki / "sources/source.md", {"summary": "clip"})
    config = load_config(tmp_path)
    text = generate(config.wiki, config=config)
    assert "Catalog: 2 full entity pages, 1 stubs, 1 sources." in text
    assert text.index("[[A]]") < text.index("[[C]]") < text.index("## Technologies")
    assert "[[B]]" in text.split("## Stubs")[1]
    assert "Unused" not in text and "Ignore" not in text


@pytest.mark.parametrize("kind", ["company", "technology", "product", "market", "theme"])
def test_custom_declared_type(tmp_path, kind):
    settings(tmp_path, '[paths]\nentity_dirs=["custom"]\n')
    page(tmp_path / "wiki/custom/Entry.md", {"type": kind})
    config = load_config(tmp_path)
    text = generate(config.wiki, config=config)
    title = {"company": "Companies", "technology": "Technologies", "product": "Products",
             "market": "Markets", "theme": "Themes"}[kind]
    assert "[[Entry]]" in text.split("## " + title)[1].split("\n## ")[0]


@pytest.mark.parametrize("meta", [{}, {"type": "source"}, {"type": []}, {"type": {"bad": 1}}])
def test_custom_requires_supported_type(tmp_path, meta, capsys):
    settings(tmp_path, '[paths]\nentity_dirs=["custom"]\n')
    page(tmp_path / "wiki/custom/Entry.md", meta)
    assert main(["gen-index", "--root", str(tmp_path)]) == 2
    result = capsys.readouterr()
    assert not result.out and "supported entity type" in result.err


@pytest.mark.parametrize("body", ["Body only", "---\nbad: [\n---\n",
                                  "---\nsummary: !!unknown x\n---\n", "---\nsummary: a\x01\n---\n"])
def test_invalid_entity_input_fails_without_partial_output(tmp_path, body, capsys):
    config = vault(tmp_path)
    (config.wiki / "companies/ZZ.md").write_text(body, encoding="utf-8")
    before = snapshot(tmp_path)
    assert main(["gen-index", "--root", str(tmp_path)]) == 2
    result = capsys.readouterr()
    assert not result.out and result.err.startswith("glassgraph:")
    assert "Traceback" not in result.err
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("field,value", [("summary", 0), ("summary", False), ("summary", []),
                                         ("summary", {}), ("tags", 0), ("tags", False),
                                         ("tags", ["stub", 2]), ("tags", {})])
def test_unusable_entity_metadata(tmp_path, field, value, capsys):
    vault(tmp_path)
    page(tmp_path / "wiki/companies/ZZ.md", {field: value})
    assert main(["gen-index", "--root", str(tmp_path)]) == 2
    result = capsys.readouterr()
    assert not result.out and f"string {field}" in result.err


@pytest.mark.parametrize("body", ["---\nsummary: [bad]\n---\n", "---\nbad: [\n---\n"])
def test_bad_source_input(tmp_path, body, capsys):
    vault(tmp_path)
    (tmp_path / "wiki/sources/ZZ.md").write_text(body, encoding="utf-8")
    assert main(["gen-index", "--root", str(tmp_path)]) == 2
    assert not capsys.readouterr().out


def test_collision_after_merged_skip(tmp_path):
    config = vault(tmp_path)
    page(config.wiki / "products/Aster.md", {"tags": "merged"})
    assert generate(config.wiki, config=config).encode("utf-8") == EXPECTED
    page(config.wiki / "products/Aster.md", {})
    with pytest.raises(IndexError_, match="name collision"):
        generate(config.wiki, config=config)


def test_null_and_scalar_legacy_metadata(tmp_path):
    page(tmp_path / "wiki/companies/A.md", {"tags": None, "summary": None})
    page(tmp_path / "wiki/products/B.md", {"tags": "not-merged"})
    text = generate(tmp_path / "wiki", config=load_config(tmp_path))
    assert "[[A]]" in text and "[[B]]" not in text


def test_duplicate_keys_retain_legacy_last_value(tmp_path):
    vault(tmp_path)
    path = tmp_path / "wiki/companies/ZZ.md"
    path.write_text("---\nsummary: first\nsummary: last\n---\n", encoding="utf-8")
    assert "[[ZZ]] — last" in generate(tmp_path / "wiki", config=load_config(tmp_path))


def test_no_apply_and_missing_wiki(tmp_path, capsys):
    assert main(["gen-index", "--root", str(tmp_path)]) == 2
    assert "existing configured wiki" in capsys.readouterr().err
    with pytest.raises(SystemExit) as error:
        main(["gen-index", "--root", str(tmp_path), "--apply"])
    assert error.value.code == 2


def test_empty_existing_wiki(tmp_path):
    (tmp_path / "wiki").mkdir()
    text = generate(tmp_path / "wiki", config=load_config(tmp_path))
    assert "Catalog: 0 full entity pages, 0 stubs, 0 sources." in text


def test_read_failure_is_not_suppressed(tmp_path, monkeypatch, capsys):
    vault(tmp_path)
    original = Path.read_text

    def denied(path, *args, **kwargs):
        if path.name == "Aster.md":
            raise PermissionError("synthetic read failure")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", denied)
    assert main(["gen-index", "--root", str(tmp_path)]) == 2
    result = capsys.readouterr()
    assert not result.out and "synthetic read failure" in result.err


@pytest.mark.parametrize("target_kind", ["entity", "source"])
def test_external_symlink_is_rejected(tmp_path, target_kind, capsys):
    root = tmp_path / "vault"
    root.mkdir()
    vault(root)
    outside = tmp_path / "outside.md"
    page(outside, {"summary": "outside"})
    link = root / ("wiki/companies/ZZ.md" if target_kind == "entity" else "wiki/sources/ZZ.md")
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("File symlinks are unavailable")
    assert main(["gen-index", "--root", str(root)]) == 2
    result = capsys.readouterr()
    assert not result.out and "inside the vault" in result.err


def test_excluded_directories_are_not_read(tmp_path):
    settings(tmp_path, '[paths]\nexclude=["wiki/companies", "wiki/sources"]\n')
    page(tmp_path / "wiki/products/Unit.md", {})
    for name in ("companies", "sources"):
        (tmp_path / "wiki" / name).write_bytes(b"invalid directory input")
    config = load_config(tmp_path)
    assert "Catalog: 1 full entity pages, 0 stubs, 0 sources." in generate(config.wiki, config=config)


def test_unreadable_input_directory_is_error(tmp_path, capsys):
    (tmp_path / "wiki").mkdir()
    (tmp_path / "wiki/companies").write_bytes(b"not a directory")
    assert main(["gen-index", "--root", str(tmp_path)]) == 2
    assert not capsys.readouterr().out


def test_does_not_read_or_write_derived_state(tmp_path):
    config = vault(tmp_path)
    settings(tmp_path, "")
    for directory in (".glassgraph/index", ".glassgraph/cache", ".glassgraph/reports",
                      ".tools/index", ".tools/extraction-cache"):
        path = tmp_path / directory
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"unusable state")
    before = snapshot(tmp_path)
    assert generate(config.wiki, config=config).encode("utf-8") == EXPECTED
    assert snapshot(tmp_path) == before
