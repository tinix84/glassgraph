"""Span-level debugging output for Stage 1 entity extraction.

Reuses `linker.extract()` and `linker._preprocess()` to produce a human-readable
listing of every hit (and optionally suppressed candidates) with surrounding
context. Intended for answering 'why did this match?' / 'why didn't this match?'
without modifying the production pipeline.
"""
from __future__ import annotations

from pathlib import Path

import ahocorasick

from glassgraph.core import linker


def format_hit(body: str, start: int, end: int, canonical: str, alias: str, context_chars: int = 30) -> str:
    """Format one hit line + a context line (body[start - N : end + N + 1] with ellipsis markers)."""
    matched = body[start:end + 1]
    ctx_start = max(0, start - context_chars)
    ctx_end = min(len(body), end + 1 + context_chars)
    ctx = body[ctx_start:ctx_end].replace("\n", " ")
    leading = "..." if ctx_start > 0 else ""
    trailing = "..." if ctx_end < len(body) else ""
    return (
        f"[{start}:{end + 1}]   {matched!r} → {canonical}  via {alias!r}\n"
        f"            context: {leading}{ctx}{trailing}"
    )


def explain_file(
    raw_path: Path,
    automaton: ahocorasick.Automaton,
    filter_canonical: str | None = None,
    show_suppressed: bool = False,
    context_chars: int = 30,
    disambiguation_yaml: Path | None = None,
    *,
    strict_disambiguation: bool = False,
) -> str:
    """Return formatted multi-line string explaining every Stage 1 hit in raw_path."""
    body, hits, warnings = linker.scan_file(
        raw_path, automaton, disambiguation_yaml,
        strict_disambiguation=strict_disambiguation,
    )

    lines: list[str] = []
    unique_canonicals: set[str] = set()
    for start, end, canonical, alias in hits:
        if filter_canonical and canonical != filter_canonical:
            continue
        unique_canonicals.add(canonical)
        lines.append(format_hit(body, start, end, canonical, alias, context_chars))

    if show_suppressed and warnings:
        lines.append("")
        lines.append("=== SUPPRESSED (disambiguation) ===")
        for w in warnings:
            lines.append(f"  {w}")

    lines.append("")
    lines.append(f"Summary: {len(hits)} hits, {len(unique_canonicals)} unique canonicals, {len(warnings)} disambiguation warnings")
    return "\n".join(lines) + "\n"
