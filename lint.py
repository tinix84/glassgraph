"""Defensive lints for the 2brain wiki — 7 checks aggregated into one report.

Each check is a pure function: (root_path) -> list[LintFinding]. Findings are
sorted by severity (CRITICAL > WARN > INFO) then file path. Returns exit code 1
when any CRITICAL finding present.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml


_WIKILINK_RE = re.compile(r"\[\[([^\[\]\|]+?)(?:\|[^\[\]]+)?\]\]")
_SEVERITY_ORDER = {"CRITICAL": 0, "WARN": 1, "INFO": 2}
_ENTITY_DIRS = ("companies", "technologies", "products", "themes")


@dataclass
class LintFinding:
    severity: str
    check: str
    file: Path
    line: int | None
    message: str


# ── frontmatter helpers ─────────────────────────────────────────────────────

def _read_frontmatter(path: Path) -> tuple[dict | None, str | None]:
    """Return (frontmatter_dict, raw_fm_text) or (None, None) if no frontmatter / parse fails.

    Distinguishes 'no frontmatter' (returns None, None) from 'parse failure'
    (returns None, raw_text) so callers can decide severity.
    """
    text = path.read_text(encoding="utf-8")
    if not text.startswith("---"):
        return None, None
    end = text.find("\n---", 3)
    if end == -1:
        return None, None
    fm_text = text[3:end]
    try:
        fm = yaml.safe_load(fm_text)
        if fm is None:
            fm = {}
        return fm, fm_text
    except yaml.YAMLError:
        return None, fm_text


def _all_wiki_pages(wiki_root: Path) -> list[Path]:
    """All entity + source + theme + index pages."""
    pages = []
    for d_name in (*_ENTITY_DIRS, "sources"):
        d = wiki_root / d_name
        if d.exists():
            pages.extend(sorted(d.glob("*.md")))
    root_index = wiki_root / "index.md"
    if root_index.exists():
        pages.append(root_index)
    return pages


def _entity_pages(wiki_root: Path) -> list[Path]:
    pages = []
    for d_name in _ENTITY_DIRS:
        d = wiki_root / d_name
        if d.exists():
            pages.extend(sorted(d.glob("*.md")))
    return pages


def _build_canonical_index(wiki_root: Path) -> dict[str, str]:
    """Map every alias (and page stem) → canonical stem.

    Used by broken-wikilink and touches-orphan to verify references resolve.
    Last-write-wins on collisions (consistent with Stage 1 dedup logic).
    """
    canonical_index: dict[str, str] = {}
    for page in _entity_pages(wiki_root):
        canonical = page.stem
        canonical_index.setdefault(canonical, canonical)
        fm, _ = _read_frontmatter(page)
        if not fm:
            continue
        for field in ("aliases_en", "aliases_cn"):
            val = fm.get(field) or []
            if isinstance(val, str):
                val = [val]
            for alias in val:
                if isinstance(alias, str) and alias.strip():
                    canonical_index.setdefault(alias.strip(), canonical)
    return canonical_index


# ── Check 1: yaml-validity ──────────────────────────────────────────────────

def check_yaml_validity(pages: list[Path]) -> list[LintFinding]:
    findings = []
    for page in pages:
        text = page.read_text(encoding="utf-8")
        if not text.startswith("---"):
            continue  # no frontmatter is fine
        end = text.find("\n---", 3)
        if end == -1:
            findings.append(LintFinding(
                severity="CRITICAL", check="yaml-validity",
                file=page, line=1,
                message="frontmatter delimiter --- not closed",
            ))
            continue
        try:
            yaml.safe_load(text[3:end])
        except yaml.YAMLError as e:
            line = getattr(getattr(e, "problem_mark", None), "line", None)
            findings.append(LintFinding(
                severity="CRITICAL", check="yaml-validity",
                file=page, line=(line + 1) if line is not None else None,
                message=f"YAML parse error: {e}",
            ))
    return findings


# ── Check 2: duplicate-alias ────────────────────────────────────────────────

def check_duplicate_aliases(wiki_root: Path) -> list[LintFinding]:
    """Aliases appearing on 2+ entity pages with different canonicals."""
    alias_to_pages: dict[str, list[Path]] = {}
    for page in _entity_pages(wiki_root):
        fm, _ = _read_frontmatter(page)
        if not fm:
            continue
        seen_on_this_page: set[str] = set()
        for field in ("aliases_en", "aliases_cn"):
            val = fm.get(field) or []
            if isinstance(val, str):
                val = [val]
            for alias in val:
                if not isinstance(alias, str) or not alias.strip():
                    continue
                a = alias.strip()
                if a in seen_on_this_page:
                    continue
                seen_on_this_page.add(a)
                alias_to_pages.setdefault(a, []).append(page)

    findings = []
    for alias, pages in alias_to_pages.items():
        canonicals = {p.stem for p in pages}
        if len(canonicals) > 1:
            findings.append(LintFinding(
                severity="WARN", check="duplicate-alias",
                file=pages[0], line=None,
                message=f"alias '{alias}' claimed by: {sorted(canonicals)}",
            ))
    return findings


# ── Check 3: broken-wikilink ────────────────────────────────────────────────

def check_broken_wikilinks(wiki_root: Path) -> list[LintFinding]:
    canonical_index = _build_canonical_index(wiki_root)
    findings = []
    for page in _entity_pages(wiki_root):
        text = page.read_text(encoding="utf-8")
        for line_idx, line in enumerate(text.splitlines(), start=1):
            for m in _WIKILINK_RE.finditer(line):
                target = m.group(1).strip()
                if target not in canonical_index:
                    findings.append(LintFinding(
                        severity="WARN", check="broken-wikilink",
                        file=page, line=line_idx,
                        message=f"[[{target}]] does not resolve to any entity page or alias",
                    ))
    return findings


# ── Check 4: case-mismatch-wikilink ─────────────────────────────────────────

def check_case_mismatch_wikilinks(wiki_root: Path) -> list[LintFinding]:
    canonical_index = _build_canonical_index(wiki_root)
    lower_to_canonical = {k.lower(): k for k in canonical_index}
    findings = []
    for page in _entity_pages(wiki_root):
        text = page.read_text(encoding="utf-8")
        for line_idx, line in enumerate(text.splitlines(), start=1):
            for m in _WIKILINK_RE.finditer(line):
                target = m.group(1).strip()
                if target in canonical_index:
                    continue
                lower = target.lower()
                if lower in lower_to_canonical and lower_to_canonical[lower] != target:
                    findings.append(LintFinding(
                        severity="WARN", check="case-mismatch-wikilink",
                        file=page, line=line_idx,
                        message=f"[[{target}]] should be [[{lower_to_canonical[lower]}]] (case mismatch)",
                    ))
    return findings


# ── Check 5: missing-required-field ─────────────────────────────────────────

def check_missing_required_fields(wiki_root: Path) -> list[LintFinding]:
    findings = []
    for page in _entity_pages(wiki_root):
        fm, _ = _read_frontmatter(page)
        if fm is None:
            continue  # yaml-validity will catch parse failures
        if not fm.get("type"):
            findings.append(LintFinding(
                severity="CRITICAL", check="missing-required-field",
                file=page, line=None,
                message="missing required field 'type'",
            ))
        has_en = bool(fm.get("aliases_en"))
        has_cn = bool(fm.get("aliases_cn"))
        if not (has_en or has_cn) and "merged" not in (fm.get("tags") or []):
            findings.append(LintFinding(
                severity="CRITICAL", check="missing-required-field",
                file=page, line=None,
                message="missing both aliases_en and aliases_cn (entity page must have at least one)",
            ))
    sources_dir = wiki_root / "sources"
    if sources_dir.exists():
        for page in sorted(sources_dir.glob("*.md")):
            fm, _ = _read_frontmatter(page)
            if fm is None:
                continue
            if not fm.get("source_url"):
                findings.append(LintFinding(
                    severity="CRITICAL", check="missing-required-field",
                    file=page, line=None,
                    message="source page missing required field 'source_url'",
                ))
    return findings


# ── Check 6: touches-orphan ─────────────────────────────────────────────────

def check_touches_orphans(wiki_root: Path) -> list[LintFinding]:
    canonical_index = _build_canonical_index(wiki_root)
    findings = []
    sources_dir = wiki_root / "sources"
    if not sources_dir.exists():
        return findings
    for page in sorted(sources_dir.glob("*.md")):
        fm, _ = _read_frontmatter(page)
        if not fm:
            continue
        touches = fm.get("touches") or []
        if isinstance(touches, str):
            touches = [touches]
        for raw in touches:
            if not isinstance(raw, str):
                continue
            m = _WIKILINK_RE.match(raw.strip())
            target = m.group(1).strip() if m else raw.strip()
            if target and target not in canonical_index:
                findings.append(LintFinding(
                    severity="WARN", check="touches-orphan",
                    file=page, line=None,
                    message=f"touches: [[{target}]] does not resolve to any entity page or alias",
                ))
    return findings


# ── Check 7: empty-aliases-non-merged ───────────────────────────────────────

def check_empty_aliases_non_merged(wiki_root: Path) -> list[LintFinding]:
    findings = []
    for page in _entity_pages(wiki_root):
        fm, _ = _read_frontmatter(page)
        if not fm:
            continue
        if "merged" in (fm.get("tags") or []):
            continue
        has_en = bool(fm.get("aliases_en"))
        has_cn = bool(fm.get("aliases_cn"))
        if not (has_en or has_cn):
            findings.append(LintFinding(
                severity="INFO", check="empty-aliases-non-merged",
                file=page, line=None,
                message="entity page has empty aliases_en and aliases_cn but is not tagged 'merged'",
            ))
    return findings


# ── Aggregator + exit code ──────────────────────────────────────────────────

def run_lint(wiki_root: Path) -> list[LintFinding]:
    """Run all 7 checks and return findings sorted by severity then file."""
    all_pages = _all_wiki_pages(wiki_root)
    findings: list[LintFinding] = []
    findings.extend(check_yaml_validity(all_pages))
    findings.extend(check_duplicate_aliases(wiki_root))
    findings.extend(check_broken_wikilinks(wiki_root))
    findings.extend(check_case_mismatch_wikilinks(wiki_root))
    findings.extend(check_missing_required_fields(wiki_root))
    findings.extend(check_touches_orphans(wiki_root))
    findings.extend(check_empty_aliases_non_merged(wiki_root))
    findings.sort(key=lambda f: (_SEVERITY_ORDER[f.severity], str(f.file), f.line or 0))
    return findings


def exit_code_from_findings(findings: list[LintFinding]) -> int:
    return 1 if any(f.severity == "CRITICAL" for f in findings) else 0


def format_report(findings: list[LintFinding]) -> str:
    if not findings:
        return "Lint: 0 findings. ✓\n"
    lines = []
    counts = {"CRITICAL": 0, "WARN": 0, "INFO": 0}
    for f in findings:
        counts[f.severity] += 1
        loc = f"{f.file}:{f.line}" if f.line else str(f.file)
        lines.append(f"[{f.severity}] {f.check}  {loc}  {f.message}")
    lines.append("")
    lines.append(f"Summary: {counts['CRITICAL']} CRITICAL, {counts['WARN']} WARN, {counts['INFO']} INFO")
    return "\n".join(lines) + "\n"
