"""Portable Stage 1 extraction with isolated derived output."""
from __future__ import annotations

import dataclasses
import hashlib
import json
import os
from pathlib import Path

from glassgraph.config import ConfigError, VaultConfig
from glassgraph.core import index, linker


def _json(value) -> str:
    return json.dumps(value, indent=2, ensure_ascii=False)


def _check_output(config: VaultConfig, path: Path, *, directory: bool = False) -> None:
    """Reject redirected output and overlap with canonical directories."""
    if path.resolve() != path or not config.allows(path):
        raise ConfigError("Keep derived output in an unlinked, allowed vault directory")
    for canonical in (config.raw, config.wiki):
        if path.is_relative_to(canonical) or canonical.is_relative_to(path):
            raise ConfigError("Keep derived output separate from canonical input")
    if path.exists() and path.is_dir() != directory:
        raise ConfigError("Use directories and files at their designated derived paths")
    if any(parent.exists() and not parent.is_dir() for parent in path.parents):
        raise ConfigError("Use directories for derived output parents")
    if path.exists() and path.is_file() and path.stat().st_nlink > 1:
        raise ConfigError("Use derived output files without hard links")


def resolve_source(config: VaultConfig, source: str | Path) -> Path:
    """Resolve a current Markdown source inside the configured input scope."""
    if "\0" in os.fspath(source):
        raise ConfigError("Select a source path without null characters")
    source = Path(source)
    selected = source if source.is_absolute() else config.root / source
    if not config.allows(selected):
        raise ConfigError("Select a source outside excluded directories")
    selected = selected.resolve()
    if (selected.suffix.lower() != ".md" or not selected.is_file()
            or not any(selected.is_relative_to(folder)
                       for folder in (config.raw, config.wiki / "sources"))):
        raise ConfigError("Select an existing Markdown source in raw or wiki/sources")
    if not config.wiki.is_dir():
        raise ConfigError("Select an existing configured wiki directory")
    return selected


def disambiguation_path(config: VaultConfig) -> Path:
    """Locate optional portable disambiguation rules without creating state."""
    path = config.root / ".glassgraph/index/disambiguation.yaml"
    if not config.allows(path):
        raise ConfigError("Select disambiguation rules outside excluded directories")
    return path


def suggest(config: VaultConfig, source: str | Path, *, top_n: int = 20) -> str:
    """Propose current alias candidates without reading or writing caches."""
    from glassgraph.core import suggest as ranker

    if top_n < 0:
        raise ConfigError("Use a nonnegative candidate limit")
    selected = resolve_source(config, source)
    body = linker._preprocess(selected.read_text(encoding="utf-8"))
    _, _, aliases = index.compile_index(config.wiki, config=config)
    df = ranker.compute_df_index(config.wiki / "sources", config=config)
    ranked = ranker.rank_candidates(body, known_aliases=set(aliases), df=df, top_n=top_n)
    return ranker.format_report(ranked)


def explain(
    config: VaultConfig,
    source: str | Path,
    *,
    filter_canonical: str | None = None,
    show_suppressed: bool = False,
    context_chars: int = 30,
) -> str:
    """Explain current Stage 1 matches without writing derived state."""
    from glassgraph.core import explain as formatter

    if context_chars < 0:
        raise ConfigError("Use a nonnegative context length")
    selected = resolve_source(config, source)
    rules = disambiguation_path(config)
    automaton, _, _ = index.compile_index(config.wiki, config=config)
    return formatter.explain_file(
        selected, automaton, filter_canonical=filter_canonical,
        show_suppressed=show_suppressed, context_chars=context_chars,
        disambiguation_yaml=rules, strict_disambiguation=True,
    )


def extract(config: VaultConfig, source: str | Path, *, dry_run: bool = False) -> dict:
    """Read one source and return legacy-compatible Stage 1 result fields."""
    selected = resolve_source(config, source)

    index_dir = config.root / ".glassgraph/index"
    cache_dir = config.root / ".glassgraph/cache/extraction"
    relative_source = selected.relative_to(config.root)
    cache = cache_dir / relative_source.parent / (relative_source.name + ".json")
    manifest_path = index_dir / "manifest.json"
    aliases_path = index_dir / "aliases.json"
    for target in (index_dir, cache_dir):
        _check_output(config, target, directory=True)
    for target in (manifest_path, aliases_path, cache):
        _check_output(config, target)
    disambiguation = disambiguation_path(config)

    automaton, manifest, aliases = index.compile_index(config.wiki, config=config)
    # Match the legacy text writer's platform newlines before computing its SHA.
    aliases_json = _json(aliases).replace("\n", os.linesep)
    manifest_sha = hashlib.sha256(aliases_json.encode("utf-8")).hexdigest()[:16]
    result = linker.extract_file(selected, automaton, manifest_sha, disambiguation,
                                 strict_disambiguation=True)
    data = dataclasses.asdict(result)
    for optional in ("vector_entities", "vector_manifest_sha"):
        data.pop(optional)
    if not dry_run:
        index_dir.mkdir(parents=True, exist_ok=True)
        cache.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(_json(manifest), encoding="utf-8")
        aliases_path.write_text(aliases_json, encoding="utf-8", newline="")
        cache.write_text(_json(data), encoding="utf-8")
    return data
