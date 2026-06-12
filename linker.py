"""Aho-Corasick entity extraction: scan, dedup, disambiguation, result types."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator

import ahocorasick
import yaml


def _load_frontmatter():
    import importlib.util, sys
    from pathlib import Path
    if "frontmatter" in sys.modules:
        return sys.modules["frontmatter"]
    src = Path(__file__).resolve().parent / "frontmatter.py"
    spec = importlib.util.spec_from_file_location("frontmatter", src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["frontmatter"] = mod
    spec.loader.exec_module(mod)
    return mod


frontmatter = _load_frontmatter()

# \W excludes underscore in Python's Unicode mode; explicit _ makes underscore a boundary too
_BOUNDARY_RE = re.compile(r"[\W_]", re.UNICODE)
# CJK Unified Ideographs — boundary rules relaxed inside CJK runs
_CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")


def _is_cjk(s: str) -> bool:
    return bool(_CJK_RE.search(s))


def _is_boundary(ch: str) -> bool:
    """True if ch is a word-boundary character (or empty = start/end of string).

    CJK ideographs count as boundaries: Chinese prose embeds Latin terms with
    no spaces (用SiC器件), so a CJK neighbor must not block a Latin-edge match.
    """
    if not ch:
        return True
    if _CJK_RE.match(ch):
        return True
    return bool(_BOUNDARY_RE.match(ch))


# ── Text preprocessing ────────────────────────────────────────────────────────

def strip_fenced(lines) -> Iterator[str]:
    """Strip fenced code blocks (``` or ~~~). Copied from tinix84_twin/vault.py."""
    fence_re = re.compile(r"^(`{3,}|~{3,})")
    fence_char: str | None = None
    fence_len: int = 0
    for line in lines:
        m = fence_re.match(line)
        if m:
            ch = m.group(1)[0]
            ln = len(m.group(1))
            if fence_char is None:
                fence_char, fence_len = ch, ln
                continue
            if ch == fence_char and ln >= fence_len:
                fence_char, fence_len = None, 0
                continue
        if fence_char is not None:
            continue
        yield line


def _preprocess(text: str) -> str:
    """Strip frontmatter and fenced blocks; return plain string for scanning."""
    body = frontmatter.parse(text).body
    lines = body.splitlines()
    return "\n".join(strip_fenced(lines))


# ── Aho-Corasick scan + greedy dedup ─────────────────────────────────────────

def _load_disambiguation(yaml_path: Path | None) -> list[str]:
    if yaml_path is None or not yaml_path.exists():
        return []
    try:
        entries = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or []
        return [e["pattern"].lower() for e in entries if isinstance(e, dict) and "pattern" in e]
    except (yaml.YAMLError, OSError):
        return []


def extract(
    body: str,
    automaton: ahocorasick.Automaton,
    disambiguation_patterns: list[str] | None = None,
) -> tuple[list[tuple[int, int, str, str]], list[str]]:
    """Scan body for entity hits.

    Returns:
        hits: list of (start, end, canonical, alias) — end is inclusive
        warnings: disambiguation suppression messages
    """
    if not body or len(automaton) == 0:
        return [], []
    if disambiguation_patterns is None:
        disambiguation_patterns = []

    # 1. Raw Aho-Corasick scan with boundary check
    raw: list[tuple[int, int, str, str]] = []
    for end_idx, (canonical, alias) in automaton.iter(body):
        start_idx = end_idx - len(alias) + 1
        before = body[start_idx - 1] if start_idx > 0 else ""
        after = body[end_idx + 1] if end_idx + 1 < len(body) else ""
        # Per-edge boundary: a CJK edge of the alias needs no boundary; a
        # Latin edge needs a boundary char (CJK neighbors count as boundaries).
        ok_before = bool(_CJK_RE.match(alias[0])) or _is_boundary(before)
        ok_after = bool(_CJK_RE.match(alias[-1])) or _is_boundary(after)
        if ok_before and ok_after:
            raw.append((start_idx, end_idx, canonical, alias))

    # 2. Greedy sweep: leftmost first, longest first (end is inclusive, so length = end-start+1; offset doesn't affect sort order)
    raw.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    kept: list[tuple[int, int, str, str]] = []
    cursor = 0
    for start, end, canonical, alias in raw:
        if start >= cursor:
            kept.append((start, end, canonical, alias))
            cursor = end + 1

    # 3. Disambiguation filter
    hits: list[tuple[int, int, str, str]] = []
    warnings: list[str] = []
    for start, end, canonical, alias in kept:
        # Suppress if body text at this position starts with a blocklist pattern
        # (handles "Tesla" matched inside "Tesla coil" context)
        suppressed = next(
            (p for p in disambiguation_patterns
             if body[start:start + len(p)].lower() == p),
            None,
        )

        if suppressed:
            warnings.append(
                f"Suppressed '{body[start:end+1]}' → '{canonical}' "
                f"(matched disambiguation pattern '{suppressed}')"
            )
        else:
            hits.append((start, end, canonical, alias))

    return hits, warnings


# ── Result types ──────────────────────────────────────────────────────────────

@dataclass
class EntityHit:
    canonical: str
    aliases_matched: list[str] = field(default_factory=list)
    count: int = 0
    confidence: str = "dict"  # "dict" for Stage 1; "vector" reserved for Stage 2


@dataclass
class VectorHit:
    """A Stage 2 (BGE-M3) match — semantic similarity to an entity page."""
    canonical: str
    cosine: float
    rank: int
    confidence: str = "vector"


@dataclass
class ExtractionResult:
    source: str
    extracted_at: str
    manifest_sha: str
    entities: list[EntityHit]
    disambiguation_warnings: list[str]
    vector_entities: list[VectorHit] | None = None
    vector_manifest_sha: str | None = None


def build_result(
    source: str,
    manifest_sha: str,
    hits: list[tuple[int, int, str, str]],
    warnings: list[str],
) -> ExtractionResult:
    """Aggregate raw hits into an ExtractionResult."""
    by_canonical: dict[str, EntityHit] = {}
    for _, _, canonical, alias in hits:
        if canonical not in by_canonical:
            by_canonical[canonical] = EntityHit(canonical=canonical)
        eh = by_canonical[canonical]
        eh.count += 1
        if alias not in eh.aliases_matched:
            eh.aliases_matched.append(alias)

    entities = sorted(by_canonical.values(), key=lambda e: -e.count)
    return ExtractionResult(
        source=source,
        extracted_at=datetime.now(timezone.utc).isoformat(),
        manifest_sha=manifest_sha,
        entities=entities,
        disambiguation_warnings=warnings,
    )


def extract_file(
    raw_path: Path,
    automaton: ahocorasick.Automaton,
    manifest_sha: str,
    disambiguation_yaml: Path | None = None,
) -> ExtractionResult:
    """Full pipeline: read raw file → preprocess → extract → build result."""
    text = raw_path.read_text(encoding="utf-8")
    body = _preprocess(text)
    patterns = _load_disambiguation(disambiguation_yaml)
    hits, warnings = extract(body, automaton, disambiguation_patterns=patterns)
    return build_result(str(raw_path), manifest_sha, hits, warnings)
