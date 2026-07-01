"""Stage 3: typed relation extraction for the 2brain wiki.

Deterministic-first. This module ships the lexicon voter (Aho-Corasick over
predicates.json) and derived-edge joins — the guaranteed floor. spaCy /
GLiREL voters are layered in a follow-up plan.
"""
from __future__ import annotations

import importlib.util as _ilu
import json
import re
import sys as _sys
from dataclasses import dataclass
from pathlib import Path

PREDICATES: dict[str, dict] = {
    "vendor_of":     {"source": "derived",   "symmetric": False, "gated": False},
    "mentions":      {"source": "derived",   "symmetric": False, "gated": False},
    "evidence_for":  {"source": "derived",   "symmetric": False, "gated": False},
    "uses":          {"source": "extracted", "symmetric": False, "gated": True},
    "implements":    {"source": "extracted", "symmetric": False, "gated": True},
    "achieves_spec": {"source": "extracted", "symmetric": False, "gated": True},
    "supplies":      {"source": "extracted", "symmetric": False, "gated": True},
    "succeeds":      {"source": "extracted", "symmetric": False, "gated": True},
    "competes_with": {"source": "extracted", "symmetric": True,  "gated": True},
    "partners_with": {"source": "extracted", "symmetric": True,  "gated": True},
}
DERIVED = frozenset(p for p, s in PREDICATES.items() if s["source"] == "derived")
EXTRACTED = frozenset(p for p, s in PREDICATES.items() if s["source"] == "extracted")
SYMMETRIC = frozenset(p for p, s in PREDICATES.items() if s["symmetric"])


@dataclass(frozen=True)
class Relation:
    s: str
    p: str
    o: str
    by: str


def canonical(rel: Relation) -> Relation:
    """Symmetric predicates: reorder endpoints so s <= o. Directed: unchanged."""
    if rel.p in SYMMETRIC and rel.s > rel.o:
        return Relation(s=rel.o, p=rel.p, o=rel.s, by=rel.by)
    return rel


_DIRECTIONS = {"subject_to_object", "object_to_subject"}


@dataclass(frozen=True)
class LexEntry:
    trigger: str
    predicate: str
    subj_type: str
    obj_type: str
    direction: str


def load_lexicon(path) -> list[LexEntry]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    entries: list[LexEntry] = []
    for i, e in enumerate(raw):
        pred = e["predicate"]
        if pred not in PREDICATES:
            raise ValueError(f"predicates.json[{i}]: unknown predicate {pred!r}")
        if e["direction"] not in _DIRECTIONS:
            raise ValueError(f"predicates.json[{i}]: bad direction {e['direction']!r}")
        entries.append(LexEntry(
            trigger=e["trigger"].lower(), predicate=pred,
            subj_type=e["subj_type"], obj_type=e["obj_type"],
            direction=e["direction"]))
    return entries


def _load_frontmatter():
    if "frontmatter" in _sys.modules:
        return _sys.modules["frontmatter"]
    src = Path(__file__).resolve().parent / "frontmatter.py"
    spec = _ilu.spec_from_file_location("frontmatter", src)
    mod = _ilu.module_from_spec(spec)
    _sys.modules["frontmatter"] = mod
    spec.loader.exec_module(mod)
    return mod


_fm = _load_frontmatter()
_SUBSECTION_RE = re.compile(r"^###\s+.*mentioned", re.IGNORECASE)
_KEYX_RE = re.compile(r"^##\s+Key extractions", re.IGNORECASE)
_H2_RE = re.compile(r"^##\s+")
_BULLET_RE = re.compile(r"^-\s+\[\[([^\[\]\|]+?)(?:\|[^\[\]]+)?\]\]\s*[—-]\s*(.*)$")


@dataclass(frozen=True)
class Bullet:
    subject: str
    text: str
    links: tuple[str, ...]


def parse_key_extractions(body: str) -> list[Bullet]:
    bullets: list[Bullet] = []
    in_keyx = in_sub = False
    for line in body.split("\n"):
        if _KEYX_RE.match(line):
            in_keyx = True; in_sub = False; continue
        if in_keyx and _H2_RE.match(line):
            break
        if _SUBSECTION_RE.match(line):
            in_sub = True; continue
        if in_keyx and in_sub:
            m = _BULLET_RE.match(line.strip())
            if m:
                subject, text = m.group(1).strip(), m.group(2)
                # WIKILINK_RE has one capturing group → findall returns plain strings
                links = tuple(t.strip() for t in _fm.WIKILINK_RE.findall(text)
                              if t.strip() != subject)
                bullets.append(Bullet(subject, text, links))
    return bullets


def resolve_object(bullet: Bullet, entry: LexEntry, focus: str | None) -> str | None:
    if bullet.links:
        return bullet.links[0]
    return focus


def lexicon_vote(bullets, entry_types: dict[str, str],
                 lexicon: list[LexEntry], focus: str | None) -> list[Relation]:
    out: list[Relation] = []
    for b in bullets:
        subj_type = entry_types.get(b.subject)
        low = b.text.lower()
        for entry in lexicon:
            if entry.trigger not in low:
                continue
            if subj_type is not None and subj_type != entry.subj_type:
                continue
            obj = resolve_object(b, entry, focus)
            if obj is None:
                continue
            if entry.direction == "subject_to_object":
                s, o = b.subject, obj
            else:
                s, o = obj, b.subject
            rel = canonical(Relation(f"[[{s}]]", entry.predicate, f"[[{o}]]", "lexicon"))
            if rel not in out:
                out.append(rel)
    return out
