"""Build and cache the Aho-Corasick alias trie from wiki entity pages."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import ahocorasick
from glassgraph.config import ConfigError, VaultConfig
from glassgraph.core import frontmatter

logger = logging.getLogger(__name__)

ENTITY_DIRS = ("companies", "technologies", "products", "markets", "themes")


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _pages(wiki_root: Path, config: VaultConfig | None = None):
    for name in config.entity_dirs if config else ENTITY_DIRS:
        directory = wiki_root / name
        if config:
            yield from config.markdown_files(directory)
        else:
            yield from sorted(directory.glob("*.md"))


def _page_shas(wiki_root: Path, config: VaultConfig | None = None) -> dict[str, str]:
    shas: dict[str, str] = {}
    for page in _pages(wiki_root, config):
        rel = str(page.relative_to(config.root if config else wiki_root.parent))
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
    if not isinstance(tags, list) or any(not isinstance(tag, str) for tag in tags):
        raise ConfigError("Use string tags in entity metadata")
    if "merged" in tags:
        return canonical, []

    def _coerce(val) -> list[str]:
        if not val:
            return []
        if isinstance(val, str):
            return [val]
        if not isinstance(val, list) or any(not isinstance(alias, str) for alias in val):
            raise ConfigError("Use string aliases in entity metadata")
        return val

    en = _coerce(fm.get("aliases_en"))
    cn = _coerce(fm.get("aliases_cn"))
    seen: dict[str, None] = {}
    for a in [canonical] + en + cn:
        if a and a.strip():
            seen[a.strip()] = None
    return canonical, list(seen)


def is_stale(
    wiki_root: Path,
    manifest_path: Path,
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


def alias_pages(
    wiki_root: Path,
    *,
    config: VaultConfig | None = None,
) -> dict[str, Path]:
    """Return each alias and its first eligible owner in dictionary order."""
    owners: dict[str, Path] = {}
    for page in _pages(wiki_root, config):
        canonical, aliases = _parse_aliases(page)
        for alias in aliases:
            if alias in owners:
                if owners[alias].stem != canonical:
                    logger.warning("alias collision: '%s' → '%s' and '%s', keeping first", alias, owners[alias].stem, canonical)
                continue
            owners[alias] = page
    return owners


def compile_index(
    wiki_root: Path,
    *,
    config: VaultConfig | None = None,
) -> tuple[ahocorasick.Automaton, dict, dict[str, str]]:
    """Compile the alias trie and index records without writing files."""
    alias_map = {alias: page.stem for alias, page in alias_pages(wiki_root, config=config).items()}
    pairs = list(alias_map.items())

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
        "page_shas": _page_shas(wiki_root, config),
    }
    return automaton, manifest, alias_map


def build_index(
    wiki_root: Path,
    manifest_path: Path,
    aliases_path: Path,
) -> ahocorasick.Automaton:
    """Rebuild the legacy index and write its manifest and alias dictionary."""
    automaton, manifest, alias_map = compile_index(wiki_root)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    aliases_path.write_text(json.dumps(alias_map, indent=2, ensure_ascii=False), encoding="utf-8")

    return automaton


def get_automaton(
    wiki_root: Path,
    manifest_path: Path,
    aliases_path: Path,
) -> ahocorasick.Automaton:
    """Return automaton, always rebuilding from source (sub-second for <1k entity pages)."""
    return build_index(wiki_root, manifest_path, aliases_path)
