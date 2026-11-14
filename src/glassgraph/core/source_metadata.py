"""Shared legacy touches parsing with strict portable-input checks."""
from __future__ import annotations

import re
from pathlib import Path

from glassgraph.config import ConfigError
from glassgraph.core import frontmatter


WIKILINK_RE = re.compile(r"^\[\[(.+?)(\|.+?)?\]\]$")


def strip_wikilink(entry: str) -> str:
    """Strip the legacy whole-entry wikilink wrapper and optional display text."""
    match = WIKILINK_RE.match(entry.strip())
    return match.group(1) if match else entry.strip()


def string_entries(value, *, strict: bool, field: str) -> list:
    """Keep legacy scalar/list forms while rejecting unusable strict inputs."""
    if strict:
        if value is None:
            return []
        if not isinstance(value, str) and (
                not isinstance(value, list) or any(not isinstance(item, str) for item in value)):
            raise ConfigError(f"Use a string or list of strings for {field}")
    else:
        value = value or []
    return [value] if isinstance(value, str) else value


def parse_touches(source_page: Path, *, strict: bool = False) -> list[str]:
    """Read touches using the shared parser and existing name normalization."""
    parsed = frontmatter.parse_file(source_page)
    if strict and parsed.error:
        raise ConfigError("Read valid source frontmatter before clustering")
    metadata = parsed.metadata or {}
    raw = string_entries(metadata.get("touches"), strict=strict, field="touches")
    return [strip_wikilink(str(item)) for item in raw if item]
