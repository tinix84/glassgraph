"""Portable lint through the installed command interface."""
import subprocess
import sys
import pytest
from pathlib import Path


def test_portable_lint_matches_legacy_report_and_exit_code(tmp_path, lint_mod, capsys):
    from glassgraph.cli import main

    (tmp_path / ".glassgraph").mkdir()
    companies = tmp_path / "wiki/companies"
    companies.mkdir(parents=True)
    source = companies / "Example.md"
    source.write_text('---\ntype: company\naliases_en: [Example]\naliases_cn: []\ntags: []\nupdated: 2026\n---\n', encoding="utf-8")
    before = source.read_bytes()
    findings = lint_mod.run_lint(tmp_path / "wiki")
    assert main(["--root", str(tmp_path), "lint"]) == lint_mod.exit_code_from_findings(findings)
    assert capsys.readouterr().out == lint_mod.format_report(findings) + "\n"
    assert source.read_bytes() == before
    assert sorted(path.name for path in (tmp_path / ".glassgraph").iterdir()) == []


def test_configured_layout_and_exclusions_control_all_lint_checks(tmp_path, capsys):
    from glassgraph.cli import main

    marker = tmp_path / ".glassgraph"
    marker.mkdir()
    (marker / "config.toml").write_text(
        '[paths]\nwiki="notes"\nraw="clippings"\nentity_dirs=["vendors"]\n'
        'exclude=["notes/vendors/Ignored.md"]\n', encoding="utf-8",
    )
    vendors = tmp_path / "notes/vendors"
    vendors.mkdir(parents=True)
    (vendors / "Example.md").write_text(
        '---\ntype: company\naliases: [Example]\naliases_en: [Example]\naliases_cn: []\n---\n'
        '[[clippings/Report.md]] [[notes/vendors/Example.md]]\n', encoding="utf-8",
    )
    (vendors / "Ignored.md").write_text("---\ntype: [broken\n---\n", encoding="utf-8")
    (tmp_path / "clippings").mkdir()
    (tmp_path / "clippings/Report.md").write_text("Raw input.", encoding="utf-8")
    assert main(["lint", "--root", str(tmp_path)]) == 0
    assert capsys.readouterr().out == "Lint: 0 findings. ✓\n\n"
    page = vendors / "Example.md"
    page.write_text(page.read_text(encoding="utf-8").replace("type: company", "type: invalid"), encoding="utf-8")
    assert main(["lint", "--root", str(tmp_path)]) == 1
    assert "metadata-validity" in capsys.readouterr().out


def test_wrong_qualified_prefix_is_broken_for_custom_wiki(tmp_path, capsys):
    from glassgraph.cli import main

    (tmp_path / ".glassgraph").mkdir()
    (tmp_path / ".glassgraph/config.toml").write_text('[paths]\nwiki="notes"\n', encoding="utf-8")
    companies = tmp_path / "notes/companies"
    companies.mkdir(parents=True)
    (companies / "Example.md").write_text(
        '---\ntype: company\naliases_en: [Example]\naliases: [Example]\n---\n'
        '[[wiki/companies/Example.md]] [[notes/companies/Example.md]]\n', encoding="utf-8",
    )
    assert main(["lint", "--root", str(tmp_path)]) == 0
    report = capsys.readouterr().out
    assert "broken-wikilink" in report and "[[wiki/companies/Example.md]]" in report
    assert "[[notes/companies/Example.md]]" not in report


def test_invalid_utf8_returns_a_read_error_without_traceback(tmp_path, capsys):
    from glassgraph.cli import main

    companies = tmp_path / "wiki/companies"
    companies.mkdir(parents=True)
    (companies / "Invalid.md").write_bytes(b"\xff")
    assert main(["--root", str(tmp_path), "lint"]) == 2
    output = capsys.readouterr()
    assert output.err.startswith("glassgraph:")
    assert "Traceback" not in output.err


def test_external_process_discovers_vault_and_filters_without_hiding_failure(tmp_path, monkeypatch):
    monkeypatch.delenv("GLASSGRAPH_ROOT", raising=False)
    (tmp_path / ".glassgraph").mkdir()
    nested = tmp_path / "wiki/companies"
    nested.mkdir(parents=True)
    (nested / "Example.md").write_text('---\ntype: invalid\n---\n', encoding="utf-8")
    result = subprocess.run([sys.executable, "-m", "glassgraph", "lint", "--severity", "WARN"],
                            cwd=nested, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 1
    assert result.stdout == "Lint: 0 findings. ✓\n\n"
    assert result.stderr == ""


def test_missing_root_or_wiki_is_a_configuration_error(tmp_path, capsys, monkeypatch):
    from glassgraph.cli import main

    monkeypatch.delenv("GLASSGRAPH_ROOT", raising=False)
    monkeypatch.chdir(tmp_path)
    assert main(["lint"]) == 2
    error = capsys.readouterr().err
    assert "--root" in error and "GLASSGRAPH_ROOT" in error and ".glassgraph" in error
    assert main(["--root", str(tmp_path), "lint"]) == 2
    assert "wiki directory" in capsys.readouterr().err


def test_scanned_file_cannot_escape_through_symlink(tmp_path, capsys):
    from glassgraph.cli import main

    vault = tmp_path / "vault"
    companies = vault / "wiki/companies"
    companies.mkdir(parents=True)
    outside = tmp_path / "private.md"
    outside.write_text("PRIVATE CONTENT\n", encoding="utf-8")
    try:
        (companies / "External.md").symlink_to(outside)
    except OSError:
        pytest.skip("Symlink creation is unavailable")
    assert main(["--root", str(vault), "lint"]) == 2
    output = capsys.readouterr()
    assert "inside the vault" in output.err
    assert "PRIVATE" not in output.err + output.out


def test_reordered_directories_preserve_type_checks_and_source_exclusions(tmp_path, capsys):
    from glassgraph.cli import main

    (tmp_path / ".glassgraph").mkdir()
    (tmp_path / ".glassgraph/config.toml").write_text(
        '[paths]\nentity_dirs=["themes","markets"]\nexclude=["wiki/sources"]\n', encoding="utf-8",
    )
    for folder, page_type in [("themes", "theme"), ("markets", "market")]:
        directory = tmp_path / "wiki" / folder
        directory.mkdir(parents=True)
        (directory / "Example.md").write_text(
            f'---\ntype: {page_type}\naliases: [{page_type}]\naliases_en: [{page_type}]\naliases_cn: []\n---\n',
            encoding="utf-8",
        )
    sources = tmp_path / "wiki/sources"
    sources.mkdir()
    (sources / "Invalid.md").write_text("---\ntype: [broken\n---\n", encoding="utf-8")
    assert main(["--root", str(tmp_path), "lint"]) == 0
    assert capsys.readouterr().out == "Lint: 0 findings. ✓\n\n"


@pytest.mark.parametrize("installed", [True, False])
def test_legacy_file_import_works_outside_checkout(tmp_path, installed):
    script = """
import importlib.util, sys, sysconfig
if sys.argv[2] == 'source':
    sys.path.append(sysconfig.get_path('purelib'))
spec = importlib.util.spec_from_file_location('legacy_lint', sys.argv[1])
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
from glassgraph.core import lint
assert module.run_lint is lint.run_lint
assert module.format_report([]).startswith('Lint: 0')
print('Isolated legacy import passed')
"""
    arguments = [sys.executable, "-I", "-B"]
    if not installed:
        arguments.append("-S")
    shim = Path(__file__).resolve().parents[1] / "lint.py"
    result = subprocess.run(arguments + ["-c", script, str(shim), "installed" if installed else "source"],
                            cwd=tmp_path, capture_output=True, text=True, encoding="utf-8")
    assert result.returncode == 0, result.stderr
    assert result.stdout == "Isolated legacy import passed\n"
