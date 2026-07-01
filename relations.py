"""Stage 3: typed relation extraction for the 2brain wiki.

Deterministic-first. This module ships the lexicon voter (Aho-Corasick over
predicates.json) and derived-edge joins — the guaranteed floor. spaCy /
GLiREL voters are layered in a follow-up plan.
"""
from __future__ import annotations

from dataclasses import dataclass

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
