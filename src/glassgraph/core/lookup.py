"""Resolve aliases to their owning pages without changing vault state."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TypeVar

from glassgraph.config import ConfigError, ENTITY_TYPES, VaultConfig
from glassgraph.core import index


T = TypeVar("T")


def resolve_alias(name: str, aliases: Mapping[str, T]) -> T | None:
    """Preserve exact matching and the legacy last-key lowercase fallback."""
    result = aliases.get(name)
    if result is None:
        result = {key.lower(): value for key, value in aliases.items()}.get(name.lower())
    return result


def format_found(canonical: str, page_type: str, page: Path) -> str:
    return f"{canonical} | {page_type} | {page}\n"


def format_not_found(name: str) -> str:
    return f"NOT FOUND: '{name}' — no page or alias resolves to it\n"


def lookup(config: VaultConfig, name: str) -> tuple[int, str]:
    """Return a status and report for the current configured alias owner."""
    if not config.wiki.is_dir():
        raise ConfigError("Select an existing configured wiki directory")
    owner = resolve_alias(name, index.alias_owners(config.wiki, config=config))
    if owner is None:
        return 1, format_not_found(name)
    page = owner.page
    page_type = ENTITY_TYPES.get(page.parent.name.casefold())
    if page_type is None:
        page_type = owner.declared_type
        if not isinstance(page_type, str) or page_type not in ENTITY_TYPES.values():
            raise ConfigError("Declare a supported entity type in custom lookup directories")
    return 0, format_found(page.stem, page_type, page)
