"""Verify admitted page writes, refusals, and write failure boundaries."""
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig

import pytest

from glassgraph.cli import main
from glassgraph.config import load_config
from glassgraph.wiki import write_page as writer
from glassgraph.wiki.write_page import preview, render_page

FIXTURE = Path(__file__).parent / "fixtures/page_preview/v1/cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))
FOLDERS = {"company": "companies", "technology": "technologies", "product": "products",
           "market": "markets", "theme": "themes", "source": "sources"}
META = {
    "company": {"type": "company", "aliases_en": ["Acme"], "country": "Example", "kind": "other"},
    "technology": {"type": "technology", "aliases_en": ["Widget"], "category": "system"},
    "theme": {"type": "theme", "aliases_en": ["Example theme"], "thesis": "Example.", "status": "open"},
    "market": {"type": "market", "aliases_en": ["Example market"], "sector": "Example"},
    "source": {"type": "source", "source_url": "https://example.com/a", "source_lang": "en",
               "source_created": "2026-01-01", "ingested": "2026-01-02", "source_kind": "news",
               "touches": []},
}


def vault(root, config=""):
    marker = root / ".glassgraph"
    marker.mkdir(parents=True)
    (marker / "config.toml").write_text(config, encoding="utf-8")
    return load_config(root)


def inputs(root, meta, body="Example body.\n"):
    meta_file = root / "meta.json"
    body_file = root / "body.md"
    meta_file.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    body_file.write_bytes(body.encode("utf-8"))
    return meta_file, body_file


def existing(root, relative, page_type, meta):
    """Create an existing page through the legacy writer."""
    target = root / relative
    writer.write_page(target, page_type, meta, "Existing body.\n")
    return target


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None for p in root.rglob("*")}


def apply(root, page_type, target, *extra):
    return main(["write-page", "--root", str(root), "--type", page_type, "--path", target,
                 "--meta", "meta.json", "--body", "body.md", "--apply", *extra])


def temporary_files(root):
    return sorted(p.name for p in root.rglob("*.tmp"))


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_written_bytes_equal_preview(tmp_path, capsys, case):
    config = vault(tmp_path)
    meta, body = inputs(tmp_path, case["meta"], case["body"])
    target = f"wiki/{FOLDERS[case['page_type']]}/Case-page.md"
    expected, _ = preview(config, target, case["page_type"], meta, body)
    capsys.readouterr()
    assert apply(tmp_path, case["page_type"], target) == 0
    captured = capsys.readouterr()
    assert (tmp_path / target).read_bytes() == expected.encode("utf-8")
    assert captured.out == f"written | {target}\n"
    assert temporary_files(tmp_path) == []


def test_only_target_and_parents_are_written(tmp_path, capsys):
    vault(tmp_path)
    inputs(tmp_path, META["company"])
    before = snapshot(tmp_path)
    assert apply(tmp_path, "company", "wiki/companies/Acme.md") == 0
    after = snapshot(tmp_path)
    assert set(after) - set(before) == {"wiki", os.path.join("wiki", "companies"),
                                        os.path.join("wiki", "companies", "Acme.md")}
    assert {k: v for k, v in after.items() if k in before} == before
    assert not capsys.readouterr().err


def test_existing_target_needs_overwrite(tmp_path, capsys):
    vault(tmp_path)
    target = existing(tmp_path, "wiki/companies/Acme.md", "company", META["company"])
    original = target.read_bytes()
    inputs(tmp_path, META["company"], "Replacement body.\n")
    assert apply(tmp_path, "company", "wiki/companies/Acme.md") == 3
    captured = capsys.readouterr()
    assert not captured.out
    assert "ADMISSION REFUSED" in captured.err and "--overwrite" in captured.err
    assert target.read_bytes() == original
    assert apply(tmp_path, "company", "wiki/companies/Acme.md", "--overwrite") == 0
    assert target.read_bytes() == render_page("company", META["company"], "Replacement body.\n")[0].encode("utf-8")
    assert temporary_files(tmp_path) == []


@pytest.mark.parametrize("extra", [["--overwrite"], ["--dry-run", "--overwrite"]])
def test_overwrite_requires_apply(tmp_path, extra):
    vault(tmp_path)
    inputs(tmp_path, META["company"])
    with pytest.raises(SystemExit) as exit_info:
        main(["write-page", "--root", str(tmp_path), "--type", "company", "--path", "wiki/companies/Acme.md",
              "--meta", "meta.json", "--body", "body.md", *extra])
    assert exit_info.value.code == 2
    assert not (tmp_path / "wiki").exists()


def test_apply_and_dry_run_are_exclusive(tmp_path):
    vault(tmp_path)
    inputs(tmp_path, META["company"])
    with pytest.raises(SystemExit) as exit_info:
        apply(tmp_path, "company", "wiki/companies/Acme.md", "--dry-run")
    assert exit_info.value.code == 2
    assert not (tmp_path / "wiki").exists()


@pytest.mark.parametrize("page_type, target", [
    ("company", "wiki/technologies/Acme.md"),
    ("company", "wiki/Acme.md"),
    ("company", "wiki/companies/nested/Acme.md"),
    ("company", "wiki/companies/.archive/Acme.md"),
    ("company", "wiki/sources/Acme.md"),
    ("company", "wiki/unconfigured/Acme.md"),
    ("source", "wiki/companies/Source.md"),
    ("source", "wiki/sources/nested/Source.md"),
    ("source", "wiki/Source.md"),
    ("company", "wiki/themes/companies/Acme.md"),
    ("source", "wiki/x/sources/Source.md"),
    ("technology", "wiki/COMPANIES/Widget.md"),
])
def test_folder_type_mismatch_refused(tmp_path, capsys, page_type, target):
    vault(tmp_path)
    inputs(tmp_path, META[page_type])
    before = snapshot(tmp_path)
    assert apply(tmp_path, page_type, target) == 3
    captured = capsys.readouterr()
    assert "ADMISSION REFUSED" in captured.err
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("folder", ["Companies", "COMPANIES"])
def test_pages_use_the_configured_folder_spelling(tmp_path, capsys, folder):
    vault(tmp_path)
    inputs(tmp_path, META["company"])
    assert apply(tmp_path, "company", f"wiki/{folder}/Acme.md") == 0
    assert capsys.readouterr().out == "written | wiki/companies/Acme.md\n"
    assert [p.name for p in (tmp_path / "wiki").iterdir()] == ["companies"]


@pytest.mark.parametrize("config, page_type, target, status", [
    ("", "market", "wiki/markets/Example.md", 0),
    ('[paths]\nentity_dirs=["companies","notes"]\n', "theme", "wiki/notes/Example.md", 0),
    ('[paths]\nentity_dirs=["companies","notes"]\n', "company", "wiki/notes/Acme.md", 0),
    ('[paths]\nentity_dirs=["companies","notes"]\n', "source", "wiki/notes/Source.md", 3),
    ('[paths]\nentity_dirs=["companies","notes"]\n', "market", "wiki/markets/Example.md", 3),
    ('[paths]\nwiki="kb"\n', "company", "kb/companies/Acme.md", 0),
])
def test_configured_entity_directories(tmp_path, capsys, config, page_type, target, status):
    vault(tmp_path, config)
    inputs(tmp_path, META[page_type])
    assert apply(tmp_path, page_type, target) == status
    assert (tmp_path / target).is_file() == (status == 0)


@pytest.mark.parametrize("page_type, target, aliases, status", [
    ("technology", "wiki/technologies/Acme.md", ["Other"], 3),           # stem owned by another page
    ("technology", "wiki/technologies/Widget.md", ["ACME Corp"], 3),     # exact alias
    ("technology", "wiki/technologies/Widget.md", ["acme corp"], 3),     # lowercase fallback
    ("technology", "wiki/technologies/Widget.md", ["Widget"], 0),
    ("technology", "wiki/technologies/Widget.md", ["Retired"], 0),       # merged owners own nothing
    ("technology", "wiki/technologies/Retired-name.md", ["Widget"], 0),
])
def test_alias_collisions_for_new_entity_pages(tmp_path, capsys, page_type, target, aliases, status):
    vault(tmp_path)
    existing(tmp_path, "wiki/companies/Acme.md", "company",
             {**META["company"], "aliases_en": ["Acme", "ACME Corp"]})
    existing(tmp_path, "wiki/companies/Retired.md", "company",
             {"type": "company", "aliases_en": ["Retired"], "tags": ["merged"]})
    inputs(tmp_path, {**META[page_type], "aliases_en": aliases})
    assert apply(tmp_path, page_type, target) == status
    captured = capsys.readouterr()
    if status:
        assert "companies/Acme.md" in captured.err.replace("\\", "/")
    assert (tmp_path / target).is_file() == (status == 0)


def test_alias_check_skips_overwrite(tmp_path):
    vault(tmp_path)
    existing(tmp_path, "wiki/companies/Acme.md", "company", META["company"])
    existing(tmp_path, "wiki/technologies/Widget.md", "technology", META["technology"])
    inputs(tmp_path, {**META["technology"], "aliases_en": ["Widget", "Acme"]})
    assert apply(tmp_path, "technology", "wiki/technologies/Widget.md", "--overwrite") == 0


def test_duplicate_source_url(tmp_path, capsys):
    vault(tmp_path)
    existing(tmp_path, "wiki/sources/First.md", "source", META["source"])
    inputs(tmp_path, {**META["source"], "source_url": " https://example.com/a "})
    assert apply(tmp_path, "source", "wiki/sources/Second.md") == 3
    captured = capsys.readouterr()
    assert "source_url" in captured.err and "First.md" in captured.err
    assert not (tmp_path / "wiki/sources/Second.md").exists()
    inputs(tmp_path, {**META["source"], "source_url": "https://example.com/b"})
    assert apply(tmp_path, "source", "wiki/sources/Second.md") == 0
    inputs(tmp_path, META["source"], "Revised.\n")
    assert apply(tmp_path, "source", "wiki/sources/First.md", "--overwrite") == 0


def test_unparsable_source_pages_are_skipped_with_warning(tmp_path, capsys):
    vault(tmp_path)
    sources = tmp_path / "wiki/sources"
    sources.mkdir(parents=True)
    (sources / "Broken-yaml.md").write_text("---\nsource_url: [\n---\nBody\n", encoding="utf-8")
    (sources / "Broken-utf8.md").write_bytes(b"---\nsource_url: \xff\n---\n")
    (sources / "No-frontmatter.md").write_text("Body only\n", encoding="utf-8")
    inputs(tmp_path, META["source"])
    assert apply(tmp_path, "source", "wiki/sources/New.md") == 0
    captured = capsys.readouterr()
    assert "WARN: duplicate source_url check skipped 2 unparsable source page(s)" in captured.err


def test_schema_error_returns_one_without_write(tmp_path, capsys):
    vault(tmp_path)
    inputs(tmp_path, {"type": "company"})
    assert apply(tmp_path, "company", "wiki/companies/Acme.md") == 1
    captured = capsys.readouterr()
    assert not captured.out and "VALIDATION FAILED" in captured.err
    assert not (tmp_path / "wiki").exists()


@pytest.mark.parametrize("target", ["raw/companies/Acme.md", "wiki/../raw/Acme.md", "../outside.md",
                                    "wiki/companies/Acme.txt", "wiki/skip/Acme.md"])
def test_scope_errors_return_two_without_write(tmp_path, capsys, target):
    vault(tmp_path, '[paths]\nexclude=["wiki/skip"]\nentity_dirs=["companies","skip"]\n')
    inputs(tmp_path, META["company"])
    before = snapshot(tmp_path)
    assert apply(tmp_path, "company", target) == 2
    assert not capsys.readouterr().out
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("overwrite", [False, True])
def test_failed_write_leaves_no_partial_page(tmp_path, capsys, monkeypatch, overwrite):
    vault(tmp_path)
    if overwrite:
        target = existing(tmp_path, "wiki/companies/Acme.md", "company", META["company"])
        original = target.read_bytes()
    inputs(tmp_path, META["company"], "Replacement body.\n")

    def fail(*args):
        raise OSError("simulated failure")

    if overwrite:
        monkeypatch.setattr(writer.os, "replace", fail)
    else:
        monkeypatch.setattr(writer, "_move_new", fail)
    extra = ["--overwrite"] if overwrite else []
    assert apply(tmp_path, "company", "wiki/companies/Acme.md", *extra) == 2
    captured = capsys.readouterr()
    assert not captured.out and "simulated failure" in captured.err
    if overwrite:
        assert (tmp_path / "wiki/companies/Acme.md").read_bytes() == original
    else:
        assert not (tmp_path / "wiki").exists()
    assert temporary_files(tmp_path) == []


@pytest.mark.parametrize("extra", [[], ["--overwrite"]])
def test_new_target_is_not_clobbered_by_a_concurrent_page(tmp_path, capsys, monkeypatch, extra):
    vault(tmp_path)
    inputs(tmp_path, META["company"])
    real_move = writer._move_new

    def racing(source, destination):
        Path(destination).write_text("concurrent page", encoding="utf-8")
        return real_move(source, destination)

    monkeypatch.setattr(writer, "_move_new", racing)
    assert apply(tmp_path, "company", "wiki/companies/Acme.md", *extra) == 3
    assert "ADMISSION REFUSED" in capsys.readouterr().err
    assert (tmp_path / "wiki/companies/Acme.md").read_text(encoding="utf-8") == "concurrent page"
    assert temporary_files(tmp_path) == []


def test_long_target_names_are_written(tmp_path):
    vault(tmp_path)
    inputs(tmp_path, META["source"])
    target = "wiki/sources/" + "x" * 240 + ".md"
    assert apply(tmp_path, "source", target) == 0
    assert (tmp_path / target).is_file()
    assert temporary_files(tmp_path) == []


def test_preview_default_ignores_admission(tmp_path, capsys):
    vault(tmp_path)
    target = existing(tmp_path, "wiki/companies/Acme.md", "company", META["company"])
    original = target.read_bytes()
    inputs(tmp_path, META["company"])
    assert main(["write-page", "--root", str(tmp_path), "--type", "company", "--path", "wiki/other/Acme.md",
                 "--meta", "meta.json", "--body", "body.md"]) == 0
    assert capsys.readouterr().out.startswith("---\n")
    assert target.read_bytes() == original


@pytest.mark.parametrize("entry", ["module", "console"])
def test_installed_entry_points_apply(tmp_path, entry):
    root = tmp_path / "vault"
    vault(root)
    meta, body = inputs(tmp_path, META["company"])
    env = os.environ.copy()
    env.pop("GLASSGRAPH_ROOT", None)
    env.pop("PYTHONPATH", None)
    command = ([sys.executable, "-m", "glassgraph"] if entry == "module" else
               [str(Path(sysconfig.get_path("scripts")) / ("glassgraph.exe" if os.name == "nt" else "glassgraph"))])
    command += ["write-page", "--type", "company", "--path", "wiki/companies/Acme.md",
                "--meta", str(meta), "--body", str(body), "--apply"]
    result = subprocess.run(command, cwd=root, env=env, capture_output=True)
    assert result.returncode == 0, result.stderr.decode("utf-8")
    assert result.stdout.replace(b"\r\n", b"\n") == b"written | wiki/companies/Acme.md\n"
    assert (root / "wiki/companies/Acme.md").read_bytes() == \
        render_page("company", META["company"], "Example body.\n")[0].encode("utf-8")
