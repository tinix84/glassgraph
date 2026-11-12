"""Portable metadata validation through the package and legacy lint."""
import pytest
import yaml


@pytest.mark.parametrize("field,value", [
    ("vendor", [["Example"]]), ("sources", [["Report.md"]]),
    ("aliases_en", "Example"), ("tags", 123),
    ("updated", "2026-02-30"), ("released", 2025),
])
def test_packaged_writer_and_legacy_lint_reject_invalid_metadata(
    tmp_path, lint_mod, field, value,
):
    from glassgraph.wiki.schema import validate_meta

    meta = {"type": "company", "aliases_en": ["Example"], "aliases_cn": [],
            "tags": [], "sources": [], "country": "US", "kind": "other"}
    meta[field] = value
    errors, _ = validate_meta(meta, "company")
    assert any(field in error for error in errors)

    wiki = tmp_path / "wiki"
    target = wiki / "companies" / "Example.md"
    target.parent.mkdir(parents=True)
    target.write_text("---\n" + yaml.safe_dump(meta) + "---\n", encoding="utf-8")
    findings = lint_mod.run_lint(wiki)
    assert any(f.severity == "CRITICAL" and field in f.message for f in findings)


def test_writer_preserves_alias_gate_and_nonblocking_recommendations():
    from glassgraph.wiki.schema import validate_meta

    meta = {"type": "company", "aliases_en": [], "aliases_cn": [], "tags": []}
    errors, warnings = validate_meta(meta, "company")
    assert any("at least one" in error for error in errors)
    assert any("country" in warning for warning in warnings)
    meta["tags"] = ["merged"]
    assert validate_meta(meta, "company")[0] == []


def test_packaged_parser_preserves_bom_duplicates_and_body():
    from glassgraph.core.frontmatter import parse

    parsed = parse("\ufeff---\r\ntype: company\r\ntype: product\r\n---\r\nBody.\r\n")
    assert parsed.had_bom
    assert parsed.duplicate_keys == ["type"]
    assert parsed.metadata == {"type": "product"}
    assert parsed.body == "Body.\r\n"
