"""Deterministic re-linker (Lever B backfill).

Wraps plaintext entity mentions inside Key-extractions bullet *descriptions* as
[[wikilinks]] using the Aho-Corasick alias trie, so the relation voter can
resolve them as objects. Idempotent; skips the bullet subject and any text
already inside an existing [[link]]. Zero-token — reuses linker.extract.
"""
from __future__ import annotations

import importlib.util as _ilu
import re
import sys as _sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent


def _load(name):
    if name in _sys.modules:
        return _sys.modules[name]
    spec = _ilu.spec_from_file_location(name, _HERE / f"{name}.py")
    mod = _ilu.module_from_spec(spec)
    _sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


_rel = _load("relations")
_linker = _load("linker")
_EXISTING_LINK_RE = re.compile(r"\[\[.*?\]\]")


def _relink_description(desc: str, subject: str, automaton, patterns) -> str:
    covered = [(m.start(), m.end()) for m in _EXISTING_LINK_RE.finditer(desc)]
    hits, _ = _linker.extract(desc, automaton, disambiguation_patterns=patterns)
    for start, end, canonical, alias in sorted(hits, key=lambda h: -h[0]):  # right-to-left
        if canonical == subject:
            continue
        if any(start < e and s <= end for s, e in covered):  # overlaps an existing link
            continue
        surface = desc[start:end + 1]
        repl = f"[[{canonical}]]" if surface == canonical else f"[[{canonical}|{surface}]]"
        desc = desc[:start] + repl + desc[end + 1:]
    return desc


def relink_bullets(body: str, automaton, patterns=None) -> str:
    """Return body with Key-extractions bullet descriptions re-linked. Idempotent."""
    patterns = patterns or []
    lines = body.split("\n")
    in_keyx = in_sub = False
    for i, line in enumerate(lines):
        if _rel._KEYX_RE.match(line):
            in_keyx, in_sub = True, False
            continue
        if in_keyx and _rel._H2_RE.match(line):
            in_keyx = in_sub = False
            continue
        if in_keyx and _rel._SUBSECTION_RE.match(line):
            in_sub = True
            continue
        if in_keyx and in_sub:
            stripped = line.lstrip()
            indent = line[:len(line) - len(stripped)]
            m = _rel._BULLET_RE.match(stripped)
            if m:
                new_desc = _relink_description(m.group(2), m.group(1).strip(), automaton, patterns)
                lines[i] = indent + stripped[:m.start(2)] + new_desc
    return "\n".join(lines)
