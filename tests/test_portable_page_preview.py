"""Verify pinned writer bytes, configured previews, and failure boundaries."""
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import sysconfig

import pytest

from glassgraph.cli import main
from glassgraph.config import ConfigError, load_config
from glassgraph.wiki.write_page import ValidationError, preview, render_page, write_page

FIXTURE = Path(__file__).parent / "fixtures/page_preview/v1/cases.json"
CASES = json.loads(FIXTURE.read_text(encoding="utf-8"))
META = {"type": "company", "aliases_en": ["Acme"], "aliases_cn": [], "country": "Example", "kind": "other"}


def vault(root, config=""):
    marker = root / ".glassgraph"
    marker.mkdir(parents=True)
    (marker / "config.toml").write_text(config, encoding="utf-8")
    return load_config(root)


def inputs(root, meta=META, body="Example body.\n"):
    meta_file = root / "meta.json"
    body_file = root / "body.md"
    meta_file.write_text(json.dumps(meta, ensure_ascii=False), encoding="utf-8")
    body_file.write_text(body, encoding="utf-8")
    return meta_file, body_file


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None for p in root.rglob("*")}


@pytest.mark.parametrize("case", CASES, ids=lambda c: c["name"])
def test_pinned_page_bytes_and_input_immutability(tmp_path, case):
    original = copy.deepcopy(case["meta"])
    text, warnings = render_page(case["page_type"], case["meta"], case["body"])
    assert text.encode("utf-8") == case["expected"].encode("utf-8")
    assert warnings == case["warnings"]
    assert case["meta"] == original
    target = tmp_path / "new/page.md"
    assert write_page(target, case["page_type"], case["meta"], case["body"]) == warnings
    assert target.read_bytes() == text.encode("utf-8")


def test_relation_hash_and_aliases():
    from glassgraph.core.frontmatter import parse
    meta = {**META, "aliases": 42, "aliases_en": [" Acme ", "Acme", "Widget"],
            "aliases_cn": ["示例", "Acme"], "relations": []}
    body = "\n\nHash this body.\n\n"
    text, _ = render_page("company", meta, body)
    parsed = parse(text).metadata
    assert parsed["aliases"] == ["Acme", "Widget", "示例"]
    assert parsed["relations_src_md5"] == hashlib.md5(body.strip("\n").encode("utf-8")).hexdigest()
    assert meta["aliases"] == 42


@pytest.mark.parametrize("meta", [[], None, 7, "bad", {"type": "company"},
    {**META, "aliases_en": 7}, {**META, "aliases_cn": {"bad": "value"}},
    {**META, "tags": "bad"}, {**META, "type": ["company"]},
    {**META, "relations": [{"s": "[[Acme]]", "p": [], "o": "[[Widget]]", "by": "x"}]},
    {**META, "relations": [{"s": "[[Acme]]", "p": {}, "o": "[[Widget]]", "by": "x"}]}])
def test_malformed_metadata_rejected_without_write(tmp_path, meta):
    target = tmp_path / "new/page.md"
    with pytest.raises(ValidationError):
        write_page(target, "company", meta, "Body.\n")
    assert not target.parent.exists()


def test_invalid_body_and_type():
    with pytest.raises(ValidationError):
        render_page("company", META, [])
    with pytest.raises(ValidationError):
        render_page([], META, "Body.")


@pytest.mark.parametrize("dry_run", [False, True])
def test_preview_cli_no_writes(tmp_path, capsys, dry_run):
    config = vault(tmp_path)
    inputs(tmp_path)
    before = snapshot(tmp_path)
    args = ["write-page", "--root", str(tmp_path), "--type", "company", "--path", "wiki/new/Acme.md",
            "--meta", "meta.json", "--body", "body.md"]
    if dry_run:
        args.append("--dry-run")
    assert main(args) == 0
    captured = capsys.readouterr()
    assert captured.out == render_page("company", META, "Example body.\n")[0]
    assert not captured.err
    assert snapshot(tmp_path) == before


def test_warnings_use_stderr_and_schema_errors_no_stdout(tmp_path, capsys):
    vault(tmp_path)
    inputs(tmp_path, {"type": "company", "aliases_en": ["Acme"]})
    args = ["--root", str(tmp_path), "write-page", "--type", "company", "--path", "wiki/Acme.md",
            "--meta", "meta.json", "--body", "body.md"]
    assert main(args) == 0
    captured = capsys.readouterr()
    assert captured.out.startswith("---\n")
    assert "WARN: country:" in captured.err
    inputs(tmp_path, {"type": "company"})
    assert main(args) == 1
    captured = capsys.readouterr()
    assert not captured.out
    assert "VALIDATION FAILED" in captured.err


@pytest.mark.parametrize("target", ["raw/Acme.md", "wiki/../raw/Acme.md", "../outside.md", "wiki/data.txt",
                                    "notes/skip/Acme.md", "notes/not-a-file.md"])
def test_configured_target_scope(tmp_path, target):
    config = vault(tmp_path, '[paths]\nwiki="notes"\nexclude=["notes/skip"]\n')
    meta, body = inputs(tmp_path)
    (tmp_path / "notes/not-a-file.md").mkdir(parents=True)
    before = snapshot(tmp_path)
    with pytest.raises(ConfigError):
        preview(config, target, "company", meta, body)
    assert snapshot(tmp_path) == before
    assert preview(config, "notes/new/Acme.md", "company", meta, body)[0].startswith("---\n")


@pytest.mark.parametrize("failure", ["bad-json", "bad-meta-utf8", "bad-body-utf8", "missing-meta", "missing-body"])
def test_input_errors_return_two_without_partial_stdout(tmp_path, capsys, failure):
    vault(tmp_path)
    meta, body = inputs(tmp_path)
    if failure == "bad-json":
        meta.write_text("{", encoding="utf-8")
    elif failure == "bad-meta-utf8":
        meta.write_bytes(b"\xff")
    elif failure == "bad-body-utf8":
        body.write_bytes(b"\xff")
    elif failure == "missing-meta":
        meta = tmp_path / "absent.json"
    else:
        body = tmp_path / "absent.md"
    before = snapshot(tmp_path)
    assert main(["--root", str(tmp_path), "write-page", "--type", "company", "--path", "wiki/Acme.md",
                 "--meta", str(meta), "--body", str(body)]) == 2
    captured = capsys.readouterr()
    assert not captured.out
    assert "Traceback" not in captured.err
    assert snapshot(tmp_path) == before


@pytest.mark.parametrize("entry", ["module", "console"])
@pytest.mark.parametrize("mode", ["flag", "environment", "upward"])
def test_installed_entry_points(tmp_path, entry, mode):
    root = tmp_path / "vault"
    vault(root, '[paths]\nwiki="notes"\n')
    meta, body = inputs(tmp_path)
    nested = root / "nested"
    nested.mkdir()
    unrelated = tmp_path / "elsewhere"
    unrelated.mkdir()
    env = os.environ.copy()
    env.pop("GLASSGRAPH_ROOT", None)
    env.pop("PYTHONPATH", None)
    command = ([sys.executable, "-m", "glassgraph"] if entry == "module" else
               [str(Path(sysconfig.get_path("scripts")) / ("glassgraph.exe" if os.name == "nt" else "glassgraph"))])
    command += ["write-page", "--type", "company", "--path", "notes/new/Acme.md",
                "--meta", str(meta), "--body", str(body)]
    if mode == "flag":
        command += ["--root", str(root)]
        env["GLASSGRAPH_ROOT"] = str(unrelated)
    elif mode == "environment":
        env["GLASSGRAPH_ROOT"] = str(root)
    before = snapshot(root)
    result = subprocess.run(command, cwd=nested if mode == "upward" else unrelated, env=env, capture_output=True)
    assert result.returncode == 0, result.stderr.decode("utf-8")
    assert result.stdout == render_page("company", META, "Example body.\n")[0].encode("utf-8")
    assert not result.stderr
    assert snapshot(root) == before


def test_bom_and_newline_inputs_and_existing_target(tmp_path):
    config = vault(tmp_path)
    meta, body = inputs(tmp_path)
    meta.write_bytes(b"\xef\xbb\xbf" + json.dumps(META).encode("utf-8"))
    body.write_bytes(b"\xef\xbb\xbfBody.\r\n")
    target = tmp_path / "wiki/Acme.md"
    target.parent.mkdir()
    target.write_bytes(b"Keep original content")
    before = snapshot(tmp_path)
    assert preview(config, target, "company", meta, body)[0] == render_page("company", META, "Body.\n")[0]
    assert snapshot(tmp_path) == before


def test_symlink_target_escape(tmp_path):
    config = vault(tmp_path / "vault")
    meta, body = inputs(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    wiki = config.wiki
    wiki.mkdir()
    try:
        (wiki / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks unavailable")
    with pytest.raises(ConfigError):
        preview(config, "wiki/link/Acme.md", "company", meta, body)
