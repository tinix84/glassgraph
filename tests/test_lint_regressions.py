"""Regression coverage for metadata shapes and Obsidian source links."""
import pytest
import yaml


def page(wiki, folder, name, meta, body=""):
    target = wiki / folder / name
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("---\n" + yaml.safe_dump(meta, allow_unicode=True) + "---\n" + body, encoding="utf-8")
    return target


@pytest.mark.parametrize("field,value", [
    ("touches", [["Tesla"]]), ("touches", ["Tesla"]),
    ("touches", None), ("touches", 123),
    ("vendor", [["Tesla"]]), ("vendor", 123),
    ("sources", [["Report.md"]]), ("sources", "Report.md"),
    ("aliases", [["Tesla"]]), ("aliases_en", 123),
    ("tags", {"stub": True}), ("tags", 123), ("released", 2025),
    ("updated", "2026-02-30"), ("type", ["company"]),
    ("category", ["inverter"]), ("source_lang", ["en"]),
    ("country", False), ("source_created", None),
])
def test_malformed_metadata_is_critical_without_crashing(tmp_path, lint_mod, field, value):
    wiki = tmp_path / "wiki"
    meta = {"type": "company", "aliases": ["Tesla"], "aliases_en": ["Tesla"], "aliases_cn": []}
    meta[field] = value
    target = page(wiki, "companies", "Tesla.md", meta)
    findings = lint_mod.run_lint(wiki)
    assert any(f.severity == "CRITICAL" and f.file == target and field in f.message for f in findings)
    assert lint_mod.exit_code_from_findings(findings) == 1


@pytest.mark.parametrize("target", [
    "报告", "报告.md", "sources/报告", "sources/报告.md",
    "wiki/sources/报告.md", "报告.md#Evidence", "报告#^claim",
    "sources/报告.md#Evidence|citation", "#Local heading", "#^local",
])
def test_valid_source_links_are_not_broken(tmp_path, lint_mod, target):
    wiki = tmp_path / "wiki"
    page(wiki, "sources", "报告.md", {"type": "source"})
    page(wiki, "companies", "Tesla.md", {"type": "company", "aliases_en": ["Tesla"]}, "[[" + target + "]]\n")
    assert lint_mod.check_broken_wikilinks(wiki) == []
    assert lint_mod.check_case_mismatch_wikilinks(wiki) == []


@pytest.mark.parametrize("target", ["missing.md", "missing/报告.md", "sources/missing.md", "../outside.md"])
def test_missing_source_paths_still_reported(tmp_path, lint_mod, target):
    wiki = tmp_path / "wiki"
    page(wiki, "sources", "报告.md", {"type": "source"})
    page(wiki, "companies", "Tesla.md", {"type": "company", "aliases_en": ["Tesla"]}, "[[" + target + "]]\n")
    assert len(lint_mod.check_broken_wikilinks(wiki)) == 1


def test_alias_union_missing_language_alias_is_reported(tmp_path, lint_mod):
    wiki = tmp_path / "wiki"
    page(wiki, "companies", "Tesla.md", {"type": "company", "aliases": ["Tesla"], "aliases_en": ["Tesla", "TSLA"], "aliases_cn": []})
    findings = lint_mod.check_aliases_drift(wiki)
    assert any("TSLA" in f.message for f in findings)


def test_source_without_frontmatter_is_critical(tmp_path, lint_mod):
    wiki = tmp_path / "wiki"
    target = wiki / "sources" / "Report.md"
    target.parent.mkdir(parents=True)
    target.write_text("# Report\n", encoding="utf-8")
    assert any(f.severity == "CRITICAL" and f.file == target for f in lint_mod.run_lint(wiki))


def test_case_mismatch_source_link_keeps_diagnostic(tmp_path, lint_mod):
    wiki = tmp_path / "wiki"
    page(wiki, "sources", "Report.md", {"type": "source"})
    page(wiki, "companies", "Tesla.md", {"type": "company", "aliases_en": ["Tesla"]}, "[[sources/report.md#Evidence]]")
    findings = lint_mod.check_case_mismatch_wikilinks(wiki)
    assert len(findings) == 1
    assert "Report.md" in findings[0].message


def test_raw_source_link_resolves_without_hiding_missing_folder(tmp_path, lint_mod):
    wiki = tmp_path / "wiki"
    raw = tmp_path / "raw" / "zotero" / "Report.md"
    raw.parent.mkdir(parents=True)
    raw.write_text("# Original\n", encoding="utf-8")
    page(wiki, "companies", "Tesla.md", {"type": "company", "aliases_en": ["Tesla"]},
         "[[raw/zotero/Report.md#Evidence]] [[raw/missing/Report.md]]")
    findings = lint_mod.check_broken_wikilinks(wiki)
    assert len(findings) == 1
    assert "raw/missing/Report.md" in findings[0].message


def test_source_required_fields_and_directory_type_are_checked(tmp_path, lint_mod):
    wiki = tmp_path / "wiki"
    page(wiki, "sources", "Report.md", {"type": "source", "source_url": "https://example.test"})
    page(wiki, "companies", "Wrong.md", {"type": "technology", "aliases_en": ["Wrong"]})
    findings = lint_mod.run_lint(wiki)
    assert any(f.severity == "CRITICAL" and "touches: required" in f.message for f in findings)
    assert any(f.severity == "CRITICAL" and "expected 'company'" in f.message for f in findings)


def test_invalid_unquoted_calendar_date_reports_instead_of_crashing(tmp_path, lint_mod):
    wiki = tmp_path / "wiki"
    target = wiki / "products" / "Invalid.md"
    target.parent.mkdir(parents=True)
    target.write_text("---\ntype: product\nreleased: 2026-02-30\n---\n", encoding="utf-8")
    findings = lint_mod.run_lint(wiki)
    assert any(f.severity == "CRITICAL" and f.file == target for f in findings)
