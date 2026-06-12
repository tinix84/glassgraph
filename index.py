"""Build and cache the Aho-Corasick alias trie from wiki entity pages."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import ahocorasick


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

logger = logging.getLogger(__name__)

ENTITY_DIRS = ("companies", "technologies", "products", "themes")
_HERE = Path(__file__).resolve().parent
WIKI_ROOT = _HERE.parents[1] / "wiki"
INDEX_DIR = _HERE.parent / "index"
MANIFEST_PATH = INDEX_DIR / "manifest.json"
ALIASES_PATH = INDEX_DIR / "aliases.json"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _page_shas(wiki_root: Path) -> dict[str, str]:
    shas: dict[str, str] = {}
    for d_name in ENTITY_DIRS:
        d = wiki_root / d_name
        if not d.exists():
            continue
        for page in sorted(d.glob("*.md")):
            rel = str(page.relative_to(wiki_root.parent))
            shas[rel] = _sha256(page)
    return shas


def _parse_aliases(page: Path) -> tuple[str, list[str]]:
    """Return (canonical_stem, [all aliases]) from a wiki entity page.

    Uses aliases_en + aliases_cn. The aliases: field is Obsidian-only and skipped.
    Pages tagged `merged` return an empty alias list — they exist for Obsidian
    backwards-compatibility but should not appear in the Stage 1 trie.
    """
    canonical = page.stem
    p = frontmatter.parse_file(page)
    if p.metadata is None:
        return canonical, [canonical]
    fm = p.metadata
    tags = fm.get("tags") or []
    if isinstance(tags, str):
        tags = [tags]
    if "merged" in tags:
        return canonical, []

    def _coerce(val) -> list[str]:
        if not val:
            return []
        return [val] if isinstance(val, str) else list(val)

    en = _coerce(fm.get("aliases_en"))
    cn = _coerce(fm.get("aliases_cn"))
    seen: dict[str, None] = {}
    for a in [canonical] + en + cn:
        if a and a.strip():
            seen[a.strip()] = None
    return canonical, list(seen)


def is_stale(
    wiki_root: Path = WIKI_ROOT,
    manifest_path: Path = MANIFEST_PATH,
) -> bool:
    """Return True if the index needs rebuilding."""
    if not manifest_path.exists():
        return True
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True
    if manifest.get("pyahocorasick_version") != importlib.metadata.version("pyahocorasick"):
        return True
    return _page_shas(wiki_root) != manifest.get("page_shas", {})


def build_index(
    wiki_root: Path = WIKI_ROOT,
    manifest_path: Path = MANIFEST_PATH,
    aliases_path: Path = ALIASES_PATH,
) -> ahocorasick.Automaton:
    """Build Aho-Corasick automaton from wiki alias pages. Always rebuilds from source."""
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    alias_map: dict[str, str] = {}
    pairs: list[tuple[str, str]] = []  # (alias, canonical)

    for d_name in ENTITY_DIRS:
        d = wiki_root / d_name
        if not d.exists():
            continue
        for page in sorted(d.glob("*.md")):
            canonical, aliases = _parse_aliases(page)
            for alias in aliases:
                if alias in alias_map:
                    if alias_map[alias] != canonical:
                        logger.warning("alias collision: '%s' → '%s' and '%s', keeping first", alias, alias_map[alias], canonical)
                    continue
                alias_map[alias] = canonical
                pairs.append((alias, canonical))

    # Sort longest-first (for logging consistency; dedup is done in linker.py)
    pairs.sort(key=lambda x: -len(x[0]))

    automaton = ahocorasick.Automaton()
    for alias, canonical in pairs:
        automaton.add_word(alias, (canonical, alias))
    if pairs:
        automaton.make_automaton()

    manifest = {
        "pyahocorasick_version": importlib.metadata.version("pyahocorasick"),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "alias_count": len(alias_map),
        "page_shas": _page_shas(wiki_root),
    }
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    aliases_path.write_text(json.dumps(alias_map, indent=2, ensure_ascii=False), encoding="utf-8")

    return automaton


def get_automaton(
    wiki_root: Path = WIKI_ROOT,
    manifest_path: Path = MANIFEST_PATH,
    aliases_path: Path = ALIASES_PATH,
) -> ahocorasick.Automaton:
    """Return automaton, always rebuilding from source (sub-second for <1k entity pages)."""
    return build_index(wiki_root, manifest_path, aliases_path)
