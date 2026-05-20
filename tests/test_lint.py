"""Tests for lint.py — 7 defensive checks + LintFinding dataclass."""
from __future__ import annotations

import textwrap
from pathlib import Path


# ── LintFinding dataclass ──────────────────────────────────────────────────

def test_lint_finding_has_required_fields(lint_mod):
    f = lint_mod.LintFinding(severity="CRITICAL", check="x", file=Path("a.md"), line=1, message="msg")
    assert f.severity == "CRITICAL"
    assert f.check == "x"
    assert f.line == 1


def test_lint_finding_line_optional(lint_mod):
    f = lint_mod.LintFinding(severity="WARN", check="x", file=Path("a.md"), line=None, message="msg")
    assert f.line is None


# ── Check 1: yaml-validity ─────────────────────────────────────────────────

def test_yaml_validity_passes_well_formed(tmp_path, lint_mod):
    p = tmp_path / "ok.md"
    p.write_text("---\ntype: company\naliases_en: [X]\n---\nBody.\n", encoding="utf-8")
    findings = lint_mod.check_yaml_validity([p])
    assert findings == []


def test_yaml_validity_catches_bare_question_mark(tmp_path, lint_mod):
    p = tmp_path / "bad.md"
    p.write_text("---\ntype: product\nreleased: ?\n---\nBody.\n", encoding="utf-8")
    findings = lint_mod.check_yaml_validity([p])
    assert len(findings) == 1
    assert findings[0].severity == "CRITICAL"
    assert findings[0].check == "yaml-validity"


def test_yaml_validity_no_frontmatter_ok(tmp_path, lint_mod):
    p = tmp_path / "plain.md"
    p.write_text("No frontmatter here.\n", encoding="utf-8")
    findings = lint_mod.check_yaml_validity([p])
    assert findings == []  # no frontmatter is not invalid YAML


# ── Check 2: duplicate-alias ───────────────────────────────────────────────

def test_duplicate_alias_detects_collision(tmp_path, lint_mod):
    companies = tmp_path / "wiki" / "companies"
    companies.mkdir(parents=True)
    (companies / "A.md").write_text("---\ntype: company\naliases_en: [shared]\naliases_cn: []\n---\n", encoding="utf-8")
    (companies / "B.md").write_text("---\ntype: company\naliases_en: [shared]\naliases_cn: []\n---\n", encoding="utf-8")
    findings = lint_mod.check_duplicate_aliases(tmp_path / "wiki")
    assert len(findings) == 1
    assert findings[0].severity == "WARN"
    assert "shared" in findings[0].message


def test_duplicate_alias_same_canonical_ok(tmp_path, lint_mod):
    """If the same alias appears on the same canonical page twice (e.g. in aliases_en and aliases_cn), don't flag."""
    companies = tmp_path / "wiki" / "companies"
    companies.mkdir(parents=True)
    (companies / "A.md").write_text("---\ntype: company\naliases_en: [X]\naliases_cn: [X]\n---\n", encoding="utf-8")
    findings = lint_mod.check_duplicate_aliases(tmp_path / "wiki")
    assert findings == []


# ── Check 3: broken-wikilink ───────────────────────────────────────────────

def test_broken_wikilink_caught(tmp_path, lint_mod):
    companies = tmp_path / "wiki" / "companies"
    companies.mkdir(parents=True)
    (companies / "A.md").write_text("---\ntype: company\naliases_en: [A]\naliases_cn: []\n---\nMentions [[NonExistent]].\n", encoding="utf-8")
    findings = lint_mod.check_broken_wikilinks(tmp_path / "wiki")
    assert any(f.check == "broken-wikilink" and "NonExistent" in f.message for f in findings)


def test_broken_wikilink_resolves_via_alias(tmp_path, lint_mod):
    """If [[X]] matches an alias on some page, it's not broken."""
    companies = tmp_path / "wiki" / "companies"
    companies.mkdir(parents=True)
    (companies / "Tesla.md").write_text("---\ntype: company\naliases_en: [Tesla, TSLA]\naliases_cn: []\n---\n", encoding="utf-8")
    (companies / "Other.md").write_text("---\ntype: company\naliases_en: [Other]\naliases_cn: []\n---\nMentions [[TSLA]].\n", encoding="utf-8")
    findings = lint_mod.check_broken_wikilinks(tmp_path / "wiki")
    assert not any(f.check == "broken-wikilink" and "TSLA" in f.message for f in findings)


# ── Check 4: case-mismatch-wikilink ────────────────────────────────────────

def test_case_mismatch_wikilink_caught(tmp_path, lint_mod):
    companies = tmp_path / "wiki" / "companies"
    companies.mkdir(parents=True)
    (companies / "SiC-diode.md").write_text("---\ntype: technology\naliases_en: [SiC-diode]\naliases_cn: []\n---\n", encoding="utf-8")
    (companies / "Other.md").write_text("---\ntype: technology\naliases_en: [Other]\naliases_cn: []\n---\nUses [[SiC-Diode]].\n", encoding="utf-8")
    findings = lint_mod.check_case_mismatch_wikilinks(tmp_path / "wiki")
    assert any(f.check == "case-mismatch-wikilink" and "SiC-Diode" in f.message for f in findings)


# ── Check 5: missing-required-field ────────────────────────────────────────

def test_missing_type_field_caught(tmp_path, lint_mod):
    p = tmp_path / "wiki" / "companies" / "X.md"
    p.parent.mkdir(parents=True)
    p.write_text("---\naliases_en: [X]\naliases_cn: []\n---\n", encoding="utf-8")  # missing type:
    findings = lint_mod.check_missing_required_fields(tmp_path / "wiki")
    assert any(f.check == "missing-required-field" and "type" in f.message for f in findings)


def test_missing_aliases_caught(tmp_path, lint_mod):
    p = tmp_path / "wiki" / "companies" / "X.md"
    p.parent.mkdir(parents=True)
    p.write_text("---\ntype: company\n---\n", encoding="utf-8")  # missing both alias fields
    findings = lint_mod.check_missing_required_fields(tmp_path / "wiki")
    assert any(f.check == "missing-required-field" and "aliases" in f.message for f in findings)


def test_source_missing_url_caught(tmp_path, lint_mod):
    p = tmp_path / "wiki" / "sources" / "X.md"
    p.parent.mkdir(parents=True)
    p.write_text("---\ntype: source\n---\n", encoding="utf-8")  # missing source_url:
    findings = lint_mod.check_missing_required_fields(tmp_path / "wiki")
    assert any(f.check == "missing-required-field" and "source_url" in f.message for f in findings)


# ── Check 6: touches-orphan ────────────────────────────────────────────────

def test_touches_orphan_caught(tmp_path, lint_mod):
    sources = tmp_path / "wiki" / "sources"
    sources.mkdir(parents=True)
    (sources / "S.md").write_text("---\ntype: source\nsource_url: http://x\ntouches:\n  - '[[Ghost]]'\n---\n", encoding="utf-8")
    findings = lint_mod.check_touches_orphans(tmp_path / "wiki")
    assert any(f.check == "touches-orphan" and "Ghost" in f.message for f in findings)


def test_touches_orphan_resolves_via_alias(tmp_path, lint_mod):
    companies = tmp_path / "wiki" / "companies"
    sources = tmp_path / "wiki" / "sources"
    companies.mkdir(parents=True)
    sources.mkdir(parents=True)
    (companies / "Tesla.md").write_text("---\ntype: company\naliases_en: [Tesla, TSLA]\naliases_cn: []\n---\n", encoding="utf-8")
    (sources / "S.md").write_text("---\ntype: source\nsource_url: http://x\ntouches:\n  - '[[TSLA]]'\n---\n", encoding="utf-8")
    findings = lint_mod.check_touches_orphans(tmp_path / "wiki")
    assert not any(f.check == "touches-orphan" and "TSLA" in f.message for f in findings)


# ── Check 7: empty-aliases-non-merged ──────────────────────────────────────

def test_empty_aliases_non_merged_caught(tmp_path, lint_mod):
    p = tmp_path / "wiki" / "companies" / "X.md"
    p.parent.mkdir(parents=True)
    p.write_text("---\ntype: company\naliases_en: []\naliases_cn: []\n---\n", encoding="utf-8")
    findings = lint_mod.check_empty_aliases_non_merged(tmp_path / "wiki")
    assert any(f.check == "empty-aliases-non-merged" for f in findings)
    assert findings[0].severity == "INFO"


def test_empty_aliases_merged_ok(tmp_path, lint_mod):
    p = tmp_path / "wiki" / "companies" / "X.md"
    p.parent.mkdir(parents=True)
    p.write_text("---\ntype: company\naliases_en: []\naliases_cn: []\ntags: [merged]\n---\n", encoding="utf-8")
    findings = lint_mod.check_empty_aliases_non_merged(tmp_path / "wiki")
    assert findings == []


# ── Aggregator ─────────────────────────────────────────────────────────────

def test_run_lint_returns_all_findings(tmp_path, lint_mod):
    """run_lint() aggregates all check functions and sorts findings by severity then file."""
    wiki = tmp_path / "wiki"
    (wiki / "companies").mkdir(parents=True)
    bad = wiki / "companies" / "Bad.md"
    bad.write_text("---\nreleased: ?\n---\n", encoding="utf-8")  # CRITICAL yaml-validity
    info = wiki / "companies" / "EmptyAliases.md"
    info.write_text("---\ntype: company\naliases_en: []\naliases_cn: []\n---\n", encoding="utf-8")  # INFO empty-aliases
    findings = lint_mod.run_lint(wiki)
    severities = [f.severity for f in findings]
    # CRITICAL must come first
    assert severities.index("CRITICAL") < severities.index("INFO")


def test_run_lint_exit_code_for_critical(tmp_path, lint_mod):
    """exit_code_from_findings() returns 1 if any CRITICAL, else 0."""
    findings_critical = [lint_mod.LintFinding("CRITICAL", "x", Path("a.md"), 1, "m")]
    findings_warn = [lint_mod.LintFinding("WARN", "x", Path("a.md"), 1, "m")]
    assert lint_mod.exit_code_from_findings(findings_critical) == 1
    assert lint_mod.exit_code_from_findings(findings_warn) == 0
    assert lint_mod.exit_code_from_findings([]) == 0
