"""Defensive lints for the 2brain wiki — 14 checks aggregated into one report.

Each check is a pure function: (root_path) -> list[LintFinding]. Findings are
sorted by severity (CRITICAL > WARN > INFO) then file path. Returns exit code 1
when any CRITICAL finding present.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path


from glassgraph.core import frontmatter
from glassgraph.config import ENTITY_TYPES, ConfigError, VaultConfig
_WIKILINK_RE = frontmatter.WIKILINK_RE
_SEVERITY_ORDER = {"CRITICAL": 0, "WARN": 1, "INFO": 2}
_ENTITY_DIRS = tuple(ENTITY_TYPES)


def _strings(value) -> list[str]:
    """Let diagnostic checks continue after malformed metadata is reported."""
    if isinstance(value, str):
        return [value]
    return [x for x in value if isinstance(x, str)] if isinstance(value, list) else []


def _link_note(target: str) -> str:
    """Remove the heading or block reference, preserving the note path."""
    return target.split("#", 1)[0].strip()


@dataclass
class LintFinding:
    severity: str
    check: str
    file: Path
    line: int | None
    message: str


# ── frontmatter helpers ─────────────────────────────────────────────────────

def _read_frontmatter(path: Path) -> tuple[dict | None, str | None]:
    """Return (frontmatter_dict, raw_fm_text). (None, None) = no frontmatter;
    (None, fm_text) = parse failure (caller decides severity)."""
    p = frontmatter.parse_file(path)
    if p.fm_text is None:
        return None, None
    if p.error:
        return None, p.fm_text
    return p.metadata, p.fm_text


def _allowed(path: Path, config: VaultConfig | None) -> bool:
    return config is None or config.allows(path)


def _folder_pages(folder: Path, config: VaultConfig | None) -> list[Path]:
    if not _allowed(folder, config):
        return []
    return [path for path in sorted(folder.glob("*.md")) if _allowed(path, config)]


def _source_pages(wiki_root: Path, config: VaultConfig | None) -> list[Path]:
    return _folder_pages(wiki_root / "sources", config)


def _all_wiki_pages(wiki_root: Path, config: VaultConfig | None = None) -> list[Path]:
    """All entity + source + theme + index pages."""
    pages = []
    for d_name in (*(config.entity_dirs if config else _ENTITY_DIRS), "sources"):
        pages.extend(_folder_pages(wiki_root / d_name, config))
    root_index = wiki_root / "index.md"
    if _allowed(root_index, config) and root_index.exists():
        pages.append(root_index)
    return pages


def _entity_pages(wiki_root: Path, config: VaultConfig | None = None) -> list[Path]:
    pages = []
    for d_name in (config.entity_dirs if config else _ENTITY_DIRS):
        pages.extend(_folder_pages(wiki_root / d_name, config))
    return pages


def _build_canonical_index(wiki_root: Path, config: VaultConfig | None = None) -> dict[str, str]:
    """Map every alias (and page stem) → canonical stem.

    Used by broken-wikilink and touches-orphan to verify references resolve.
    Includes entity-page stems + aliases, source-page stems, and root wiki pages
    (index, log, overview). First-write-wins on collisions.
    """
    canonical_index: dict[str, str] = {}

    # Entity pages: stem + aliases_en + aliases_cn
    for page in _entity_pages(wiki_root, config):
        canonical = page.stem
        canonical_index.setdefault(canonical, canonical)
        fm, _ = _read_frontmatter(page)
        if not fm:
            continue
        for field in ("aliases", "aliases_en", "aliases_cn"):
            for alias in _strings(fm.get(field)):
                if isinstance(alias, str) and alias.strip():
                    canonical_index.setdefault(alias.strip(), canonical)

    # Source pages: stem only (no aliases on sources)
    for page in _source_pages(wiki_root, config):
        canonical_index.setdefault(page.stem, page.stem)

    # Root wiki pages: index, log, overview
    for name in ("index", "log", "overview"):
        p = wiki_root / f"{name}.md"
        if _allowed(p, config) and p.exists():
            canonical_index.setdefault(name, name)

    # Index literal filenames and qualified paths; never reduce a missing path
    # to its basename, which would hide broken references to other folders.
    for page in _all_wiki_pages(wiki_root, config) + [wiki_root / "log.md", wiki_root / "overview.md"]:
        if not _allowed(page, config) or not page.is_file():
            continue
        relative = page.relative_to(wiki_root).as_posix()
        prefix = config.wiki.relative_to(config.root).as_posix() if config else "wiki"
        for key in (page.name, relative, "wiki/" + relative, prefix + "/" + relative):
            canonical_index.setdefault(key, page.stem)
            canonical_index.setdefault(key.removesuffix(".md"), page.stem)

    # Raw clippings are also valid Obsidian citation targets. Read paths only.
    vault_root = config.root if config else wiki_root.parent
    raw = config.raw if config else vault_root / "raw"
    raw_dirs = [raw]
    if raw == vault_root / "raw":
        raw_dirs.append(vault_root / "raw-CN")
    for folder in raw_dirs:
        if not _allowed(folder, config):
            continue
        for page in sorted(folder.rglob("*.md")):
            if not _allowed(page, config):
                continue
            relative = page.relative_to(vault_root).as_posix()
            for key in (page.stem, page.name, relative, relative.removesuffix(".md")):
                canonical_index.setdefault(key, page.stem)

    return canonical_index


# ── Check 1: yaml-validity ──────────────────────────────────────────────────

def check_yaml_validity(pages: list[Path]) -> list[LintFinding]:
    findings = []
    for page in pages:
        p = frontmatter.parse_file(page)
        if p.fm_text is None and p.error is None:
            continue  # no frontmatter is fine
        if p.error:
            findings.append(LintFinding(
                severity="CRITICAL", check="yaml-validity",
                file=page, line=None,
                message=f"YAML parse error: {p.error}",
            ))
    return findings


# ── Check 2: duplicate-alias ────────────────────────────────────────────────

def check_duplicate_aliases(wiki_root: Path, *, config: VaultConfig | None = None) -> list[LintFinding]:
    """Aliases appearing on 2+ entity pages with different canonicals."""
    alias_to_pages: dict[str, list[Path]] = {}
    for page in _entity_pages(wiki_root, config):
        fm, _ = _read_frontmatter(page)
        if not fm:
            continue
        seen_on_this_page: set[str] = set()
        for field in ("aliases_en", "aliases_cn"):
            for alias in _strings(fm.get(field)):
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

def check_broken_wikilinks(wiki_root: Path, *, config: VaultConfig | None = None) -> list[LintFinding]:
    canonical_index = _build_canonical_index(wiki_root, config)
    findings = []
    for page in _entity_pages(wiki_root, config):
        text = page.read_text(encoding="utf-8")
        for line_idx, line in enumerate(text.splitlines(), start=1):
            for m in _WIKILINK_RE.finditer(line):
                target = _link_note(m.group(1))
                if not target:
                    continue  # A heading or block within this note.
                if target not in canonical_index:
                    findings.append(LintFinding(
                        severity="WARN", check="broken-wikilink",
                        file=page, line=line_idx,
                        message=f"[[{target}]] does not resolve to any entity page or alias",
                    ))
    return findings


# ── Check 4: case-mismatch-wikilink ─────────────────────────────────────────

def check_case_mismatch_wikilinks(wiki_root: Path, *, config: VaultConfig | None = None) -> list[LintFinding]:
    canonical_index = _build_canonical_index(wiki_root, config)
    lower_to_canonical = {k.lower(): k for k in canonical_index}
    findings = []
    for page in _entity_pages(wiki_root, config):
        text = page.read_text(encoding="utf-8")
        for line_idx, line in enumerate(text.splitlines(), start=1):
            for m in _WIKILINK_RE.finditer(line):
                target = _link_note(m.group(1))
                if not target:
                    continue
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

def check_missing_required_fields(wiki_root: Path, *, config: VaultConfig | None = None) -> list[LintFinding]:
    findings = []
    for page in _entity_pages(wiki_root, config):
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
        if not (has_en or has_cn) and "merged" not in _strings(fm.get("tags")):
            findings.append(LintFinding(
                severity="CRITICAL", check="missing-required-field",
                file=page, line=None,
                message="missing both aliases_en and aliases_cn (entity page must have at least one)",
            ))
    if _source_pages(wiki_root, config):
        for page in _source_pages(wiki_root, config):
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

def check_touches_orphans(wiki_root: Path, *, config: VaultConfig | None = None) -> list[LintFinding]:
    canonical_index = _build_canonical_index(wiki_root, config)
    findings = []
    sources_dir = wiki_root / "sources"
    if not sources_dir.exists():
        return findings
    for page in _source_pages(wiki_root, config):
        fm, _ = _read_frontmatter(page)
        if not fm:
            continue
        for raw in _strings(fm.get("touches")):
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

def check_empty_aliases_non_merged(wiki_root: Path, *, config: VaultConfig | None = None) -> list[LintFinding]:
    findings = []
    for page in _entity_pages(wiki_root, config):
        fm, _ = _read_frontmatter(page)
        if not fm:
            continue
        if "merged" in _strings(fm.get("tags")):
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


# ── Check 8: aliases-drift ──────────────────────────────────────────────────

def check_aliases_drift(wiki_root: Path, *, config: VaultConfig | None = None) -> list[LintFinding]:
    """Detect pages where `aliases:` (Obsidian union) has terms not in `aliases_en` ∪ `aliases_cn`.

    Such terms are invisible to Stage 1 (which reads only the language-specific
    fields) — a silent matching gap. The fix is to promote each drifted term
    into `aliases_en` (if Latin) or `aliases_cn` (if CJK).
    """
    findings = []
    for page in _entity_pages(wiki_root, config):
        fm, _ = _read_frontmatter(page)
        if not fm:
            continue
        if "merged" in _strings(fm.get("tags")):
            continue

        aliases_union = set(_strings(fm.get("aliases")))
        aliases_en = set(_strings(fm.get("aliases_en")))
        aliases_cn = set(_strings(fm.get("aliases_cn")))
        drift = aliases_union - (aliases_en | aliases_cn)
        if drift:
            findings.append(LintFinding(
                severity="WARN", check="aliases-drift",
                file=page, line=None,
                message=f"aliases: has {len(drift)} term(s) not in aliases_en/cn: {sorted(drift)[:5]}",
            ))
        missing = (aliases_en | aliases_cn) - aliases_union
        if missing:
            findings.append(LintFinding(
                severity="WARN", check="aliases-drift", file=page, line=None,
                message=f"aliases: missing {len(missing)} term(s) from aliases_en/cn: {sorted(missing)[:5]}",
            ))
    return findings


# ── Check 9: bom ────────────────────────────────────────────────────────────

def check_bom(pages: list[Path]) -> list[LintFinding]:
    """UTF-8 BOM makes frontmatter invisible to plain utf-8 parsers."""
    findings = []
    for page in pages:
        with page.open("rb") as f:
            if f.read(3) == b"\xef\xbb\xbf":
                findings.append(LintFinding(
                    severity="CRITICAL", check="bom",
                    file=page, line=1,
                    message="file starts with a UTF-8 BOM — strip it (.tools/maintenance/strip_bom.py)",
                ))
    return findings


# ── Check 10: duplicate-key ─────────────────────────────────────────────────

def check_duplicate_keys(pages: list[Path]) -> list[LintFinding]:
    """Duplicate top-level frontmatter keys — YAML keeps the last silently."""
    findings = []
    for page in pages:
        p = frontmatter.parse_file(page)
        if p.duplicate_keys:
            findings.append(LintFinding(
                severity="CRITICAL", check="duplicate-key",
                file=page, line=None,
                message=f"duplicate frontmatter key(s): {p.duplicate_keys}",
            ))
    return findings


# ── Check 11: overview-stale ────────────────────────────────────────────────

def check_overview_stale(wiki_root: Path, today: str | None = None, *, config: VaultConfig | None = None) -> list[LintFinding]:
    """overview.md `updated:` older than 30 days → INFO (curated thesis drifts)."""
    import datetime
    p = wiki_root / "overview.md"
    if not _allowed(p, config) or not p.exists():
        return []
    fm = _read_frontmatter(p)[0]
    upd = (fm or {}).get("updated")
    if not isinstance(upd, (str, datetime.date)):
        return []
    upd_s = upd.isoformat() if isinstance(upd, datetime.date) else upd
    today = today or datetime.date.today().isoformat()
    try:
        d0 = datetime.date.fromisoformat(upd_s)
        d1 = datetime.date.fromisoformat(today)
    except ValueError:
        return []
    if (d1 - d0).days > 30:
        return [LintFinding(severity="INFO", check="overview-stale", file=p, line=None,
                            message=f"overview.md updated {upd_s}, >30 days old — refresh the thesis")]
    return []


# ── Check 12: malformed-relation ────────────────────────────────────────────

def check_malformed_relations(pages: list[Path]) -> list[LintFinding]:
    findings = []
    for p in pages:
        parsed = frontmatter.parse_file(p)
        if not parsed.metadata:
            continue
        rels = parsed.metadata.get("relations")
        if rels is None:
            continue
        ok = isinstance(rels, list) and all(
            isinstance(r, dict) and {"s", "p", "o", "by"} <= r.keys() for r in rels)
        if not ok:
            findings.append(LintFinding(
                severity="CRITICAL", check="malformed-relation",
                file=p, line=None,
                message="relations: not a list of {s,p,o,by} mappings"))
    return findings


# ── Check 13: relation-drift ────────────────────────────────────────────────

def check_relation_drift(pages: list[Path]) -> list[LintFinding]:
    findings = []
    for p in pages:
        parsed = frontmatter.parse_file(p)
        if not parsed.metadata or "relations" not in parsed.metadata:
            continue
        stored = parsed.metadata.get("relations_src_md5")
        current = hashlib.md5(parsed.body.strip("\n").encode("utf-8")).hexdigest()
        if stored != current:
            findings.append(LintFinding(
                severity="WARN", check="relation-drift",
                file=p, line=None,
                message=f"relations_src_md5 {stored} != body md5 {current} (re-extract)"))
    return findings


# ── Aggregator + exit code ──────────────────────────────────────────────────


def check_metadata_validity(wiki_root: Path, *, config: VaultConfig | None = None) -> list[LintFinding]:
    """Check metadata shapes and dates with the writer's shared validator."""
    expected = {folder: ENTITY_TYPES.get(folder) for folder in (config.entity_dirs if config else _ENTITY_DIRS)}
    expected["sources"] = "source"
    findings = []
    for folder, page_type in expected.items():
        for page in _folder_pages(wiki_root / folder, config):
            parsed = frontmatter.parse_file(page)
            if parsed.error:
                continue  # Reported by yaml-validity.
            errors = (["missing frontmatter"] if parsed.metadata is None else
                      frontmatter.validate_metadata(parsed.metadata, page_type))
            for error in errors:
                findings.append(LintFinding("CRITICAL", "metadata-validity", page, None, error))
    return findings

def run_lint(wiki_root: Path, *, config: VaultConfig | None = None) -> list[LintFinding]:
    """Run all 14 checks and return findings sorted by severity then file."""
    if config is not None and wiki_root.resolve() != config.wiki:
        raise ConfigError("Use the configured wiki directory")
    all_pages = _all_wiki_pages(wiki_root, config)
    findings: list[LintFinding] = []
    findings.extend(check_yaml_validity(all_pages))
    findings.extend(check_metadata_validity(wiki_root, config=config))
    findings.extend(check_duplicate_aliases(wiki_root, config=config))
    findings.extend(check_broken_wikilinks(wiki_root, config=config))
    findings.extend(check_case_mismatch_wikilinks(wiki_root, config=config))
    findings.extend(check_missing_required_fields(wiki_root, config=config))
    findings.extend(check_touches_orphans(wiki_root, config=config))
    findings.extend(check_empty_aliases_non_merged(wiki_root, config=config))
    findings.extend(check_aliases_drift(wiki_root, config=config))
    findings.extend(check_bom(all_pages))
    findings.extend(check_duplicate_keys(all_pages))
    findings.extend(check_overview_stale(wiki_root, config=config))
    findings.extend(check_malformed_relations(all_pages))
    findings.extend(check_relation_drift(all_pages))
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
