"""Validation rules for 2brain wiki page frontmatter.

Hard ERRORS block a write (they are the failure classes that broke pages:
parse errors, duplicate keys, bad touches shape, missing aliases, bad dates).
WARNINGS are reported but do not block (missing per-type nice-to-have fields).
Keep ERROR rules aligned with entity_linker lint CRITICAL rules.
"""
from __future__ import annotations

import re
from glassgraph.core import frontmatter

PAGE_TYPES = frontmatter.PAGE_TYPES

PREDICATES = frozenset({
    "vendor_of", "mentions", "evidence_for", "used_in", "implements",
    "achieves_spec", "supplies", "succeeds", "competes_with", "partners_with",
})
_WIKILINK_ONLY_RE = re.compile(r"^\[\[[^\[\]]+\]\]$")
_TOUCH_RE = _WIKILINK_ONLY_RE  # Retain compatibility with existing maintenance audits.

# Per-type extras: present-but-empty triggers a WARNING, never an ERROR.
TYPE_FIELDS = {
    "company": ("country", "kind"),
    "technology": ("category",),
    "product": ("vendor", "category", "released"),
    "market": ("sector",),
    "theme": ("thesis", "status"),
    "source": (),
}

def compute_aliases(aliases_en: list, aliases_cn: list) -> list[str]:
    """The `aliases:` union field, order-preserving, deduplicated."""
    seen: dict[str, None] = {}
    for a in list(aliases_en or []) + list(aliases_cn or []):
        if isinstance(a, str) and a.strip():
            seen[a.strip()] = None
    return list(seen)


def validate_meta(meta: dict, page_type: str) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors block the write."""
    errors: list[str] = frontmatter.validate_metadata(meta, page_type)
    warnings: list[str] = []

    if page_type not in PAGE_TYPES:
        return errors, warnings

    tags = meta.get("tags") or []
    if not isinstance(tags, list):
        tags = []

    if page_type != "source":
        en = meta.get("aliases_en") or []
        cn = meta.get("aliases_cn") or []
        if not en and not cn and "merged" not in tags:
            errors.append("aliases: entity page needs at least one of aliases_en/aliases_cn"
                          " (or tags: [merged])")

    for f in TYPE_FIELDS.get(page_type, ()):
        if not meta.get(f):
            warnings.append(f"{f}: missing/empty (recommended for {page_type} pages)")

    rels = meta.get("relations")
    if rels is not None:
        if not isinstance(rels, list):
            errors.append("relations: must be a list of {s,p,o,by} mappings")
        else:
            for i, r in enumerate(rels):
                if not isinstance(r, dict) or {"s", "p", "o", "by"} - r.keys():
                    errors.append(f"relations[{i}]: needs keys s,p,o,by")
                    continue
                if r["p"] not in PREDICATES:
                    errors.append(f"relations[{i}]: unknown predicate {r['p']!r}")
                if not _WIKILINK_ONLY_RE.match(str(r["s"]).strip()):
                    errors.append(f"relations[{i}].s: must be a \"[[wikilink]]\"")
                o_ok = _WIKILINK_ONLY_RE.match(str(r["o"]).strip()) or r["p"] == "achieves_spec"
                if not o_ok:
                    errors.append(f"relations[{i}].o: must be a \"[[wikilink]]\" "
                                  "(literal string allowed only for achieves_spec)")

    return errors, warnings
