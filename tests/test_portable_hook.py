"""Exercise hook admission, configured scope, previews, and installed entry points."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from glassgraph.cli import main
from glassgraph.wiki import hook

GOOD = "---\ntype: company\n---\nBody.\n"
DUP = "---\ntype: company\ntype: company\n---\nBody.\n"


def vault(root, config=""):
    marker = root / ".glassgraph"
    marker.mkdir(parents=True)
    (marker / "config.toml").write_text(config, encoding="utf-8")
    return root


def payload(path, content=GOOD, **extra):
    return {"tool_name": "Write", "tool_input": {"file_path": str(path), "content": content}, **extra}


def snapshot(root):
    return {str(p.relative_to(root)): p.read_bytes() if p.is_file() else None for p in root.rglob("*")}


@pytest.mark.parametrize("content,valid", [
    (GOOD, True), (DUP, False), ("\ufeff" + GOOD, False), ("Body", False),
    ("---\ntype: [company]\n---\n", False), ("---\ntype: {x: y}\n---\n", False),
    ("---\ntype: source\ntouches: [[Acme]]\n---\n", False),
    ('---\ntype: source\ntouches: ["[[Acme]]"]\nrelations: [{s: a, p: b, o: c, by: d}]\n---\n', True),
    ("---\ntype: company\nrelations: [x]\n---\n", False),
    ("---\ntype: company\ntouches: null\n---\n", True),
    ("---\ntype: market\n---\n", False), ("---\ntype: company\nx: [\n---\n", False),
    ("---\ntype: company\nx: !!int bad\n---\n", False),
])
def test_structural_gate(tmp_path, content, valid):
    root = vault(tmp_path)
    before = snapshot(root)
    assert hook.run(payload(root / "wiki/companies/New.md", content)) == (0 if valid else 2)
    assert snapshot(root) == before


def test_custom_scope_relative_target_and_exclusions(tmp_path):
    root = vault(tmp_path, '[paths]\nwiki="notes"\nexclude=["notes/skip"]\n')
    assert hook.run(payload("notes/new/Acme.md", DUP, cwd=str(root))) == 2
    for name in ("wiki/Acme.md", "raw/Acme.md", "notes/skip/Acme.md", "notes/.archive/old.md",
                 "notes/index.md", "notes/overview.md", "notes/log.md", "notes/data.txt"):
        assert hook.run(payload(name, DUP, cwd=str(root))) == 0


def test_edit_result_and_replace_all(tmp_path):
    root = vault(tmp_path)
    target = root / "wiki/Acme.md"
    target.parent.mkdir()
    target.write_text(GOOD + "Body.\n", encoding="utf-8")
    data = {"tool_name": "Edit", "tool_input": {"file_path": str(target),
            "old_string": "type: company", "new_string": "type: [company]"}}
    before = snapshot(root)
    assert hook.run(data) == 2
    data["tool_input"].update(old_string="absent", new_string="bad")
    assert hook.run(data) == 0
    data["tool_input"].update(old_string="", new_string="bad")
    assert hook.run(data) == 0
    data["tool_input"].update(old_string="Body.", new_string="Updated.", replace_all=True)
    assert hook.resulting_content("Edit", data["tool_input"]).count("Updated.") == 2
    assert hook.run(data) == 0
    assert snapshot(root) == before


def test_missing_edit_and_invalid_utf8(tmp_path, capsys):
    root = vault(tmp_path)
    target = root / "wiki/Acme.md"
    data = {"tool_name": "Edit", "tool_input": {"file_path": str(target),
            "old_string": "x", "new_string": "y"}}
    assert hook.run(data) == 0
    target.parent.mkdir()
    target.write_bytes(b"\xff")
    assert hook.run(data) == 2
    assert "Traceback" not in capsys.readouterr().err


@pytest.mark.parametrize("data", [None, [], 1, {}, {"tool_name": "Bash"},
                                {"tool_name": "Write", "tool_input": []}])
def test_irrelevant_envelopes(data):
    assert hook.run(data) == 0


@pytest.mark.parametrize("field,value", [("content", []), ("file_path", []),
                                          ("file_path", ""), ("file_path", "bad\0.md")])
def test_invalid_fields(tmp_path, field, value, capsys):
    root = vault(tmp_path)
    data = payload(root / "wiki/Acme.md")
    data["tool_input"][field] = value
    assert hook.run(data) == 2
    assert "Traceback" not in capsys.readouterr().err


def test_read_failure_blocks(tmp_path, monkeypatch):
    root = vault(tmp_path)
    target = root / "wiki/Acme.md"
    original = Path.read_text

    def read(path, *args, **kwargs):
        if path == target:
            raise PermissionError("denied")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", read)
    assert hook.run({"tool_name": "Edit", "tool_input": {"file_path": str(target)}}) == 2


@pytest.mark.parametrize("entry", ["module", "cli", "console"])
@pytest.mark.parametrize("mode", ["flag", "environment", "target"])
def test_installed_entry_and_discovery(tmp_path, entry, mode):
    root = vault(tmp_path / "vault")
    unrelated = tmp_path / "elsewhere"
    unrelated.mkdir()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env.pop("GLASSGRAPH_ROOT", None)
    command = [sys.executable, "-m", "glassgraph.wiki.hook"] if entry == "module" else [sys.executable, "-m", "glassgraph", "hook"]
    if entry == "console":
        import sysconfig
        command = [str(Path(sysconfig.get_path("scripts")) / ("glassgraph.exe" if os.name == "nt" else "glassgraph")), "hook"]
    if mode == "flag":
        command += ["--root", str(root)]
        env["GLASSGRAPH_ROOT"] = str(unrelated)
    elif mode == "environment":
        env["GLASSGRAPH_ROOT"] = str(root)
    before = snapshot(root)
    for content, expected in ((GOOD, 0), (DUP, 2)):
        result = subprocess.run(command, input=json.dumps(payload(root / "wiki/new/Acme.md", content)),
                                text=True, capture_output=True, env=env, cwd=unrelated)
        assert result.returncode == expected, result.stderr
        assert not result.stdout
        assert "Traceback" not in result.stderr
    assert snapshot(root) == before


def test_missing_marker_and_bad_config(tmp_path, monkeypatch):
    monkeypatch.delenv("GLASSGRAPH_ROOT", raising=False)
    assert hook.run(payload(tmp_path / "wiki/Acme.md")) == 2
    vault(tmp_path, "bad = [")
    assert hook.run(payload(tmp_path / "wiki/Acme.md")) == 2


def test_cli_and_malformed_json(tmp_path, monkeypatch):
    vault(tmp_path)
    monkeypatch.setattr(sys, "stdin", io.StringIO("{"))
    assert main(["hook", "--root", str(tmp_path)]) == 0
    monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(payload(tmp_path / "wiki/Acme.md", DUP))))
    assert main(["--root", str(tmp_path), "hook"]) == 2


def test_symlink_escape(tmp_path):
    root = vault(tmp_path / "vault")
    outside = tmp_path / "outside"
    outside.mkdir()
    wiki = root / "wiki"
    wiki.mkdir()
    try:
        (wiki / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Directory symlinks unavailable")
    assert hook.run(payload(wiki / "link/Acme.md", GOOD), root) == 2


@pytest.mark.parametrize("field,value", [("old_string", []), ("new_string", {}), ("replace_all", "yes")])
def test_invalid_edit_fields(tmp_path, field, value):
    root = vault(tmp_path)
    data = {"tool_name": "Edit", "tool_input": {"file_path": str(root / "wiki/Acme.md"),
            "old_string": "x", "new_string": "y"}}
    data["tool_input"][field] = value
    assert hook.run(data) == 2


def test_traversal_uses_resolved_scope(tmp_path):
    root = vault(tmp_path)
    (root / "wiki").mkdir()
    assert hook.run(payload(root / "wiki/../raw/Acme.md", DUP), root) == 2
    assert hook.run(payload(root / "docs/../wiki/Acme.md", DUP), root) == 2


def test_invalid_cwd(tmp_path):
    root = vault(tmp_path)
    assert hook.run(payload("wiki/Acme.md", cwd=[]), root) == 2
    assert hook.run(payload("wiki/Acme.md", cwd="relative"), root) == 2
