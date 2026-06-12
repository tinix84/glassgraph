"""Single shared frontmatter parser for the 2brain wiki.

Every consumer (linker, lint, index, graph, stage2, comparison, wikilib,
maintenance) parses page frontmatter through this module. It handles the
failure modes that previously broke pages silently:

- UTF-8 BOM: tolerated and reported via `had_bom` (plain `utf-8` parsers
  treated BOM'd files as having no frontmatter at all).
- CRLF and LF line endings.
- Strict delimiters: the block starts at line 1 with exactly `---` and ends
  at the next line that is exactly `---` (no `----` horizontal rules, no
  `\\n---` matches inside YAML strings).
- Duplicate top-level keys: PyYAML keeps the last silently; we report them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

# The one shared wikilink regex (target group 1, optional |display ignored)
WIKILINK_RE = re.compile(r"\[\[([^\[\]\|]+?)(?:\|[^\[\]]+)?\]\]")

_BOM = "﻿"
_DELIM_RE = re.compile(r"^---\s*$")


@dataclass
class ParsedPage:
    metadata: dict | None        # None = no frontmatter, or parse error (see error)
    body: str                    # text after the closing delimiter (whole text if no block)
    fm_text: str | None          # raw YAML between delimiters (None if no block)
    error: str | None            # parse-failure message, None if OK or no block
    duplicate_keys: list[str] = field(default_factory=list)
    had_bom: bool = False


class _DupKeyLoader(yaml.SafeLoader):
    """SafeLoader that records duplicate mapping keys instead of silently keeping the last."""


def _construct_mapping(loader: _DupKeyLoader, node, deep=False):
    keys = [loader.construct_object(k, deep=deep) for k, _ in node.value]
    dupes = sorted({k for k in keys if isinstance(k, str) and keys.count(k) > 1})
    if dupes:
        existing = getattr(loader, "duplicate_keys", [])
        loader.duplicate_keys = sorted(set(existing) | set(dupes))
    return yaml.SafeLoader.construct_mapping(loader, node, deep=deep)


_DupKeyLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _construct_mapping
)


def parse(text: str) -> ParsedPage:
    had_bom = text.startswith(_BOM)
    if had_bom:
        text = text[len(_BOM):]

    lines = text.split("\n")
    if not lines or not _DELIM_RE.match(lines[0].rstrip("\r")):
        return ParsedPage(None, text, None, None, had_bom=had_bom)

    for i in range(1, len(lines)):
        if _DELIM_RE.match(lines[i].rstrip("\r")):
            fm_text = "\n".join(lines[1:i])
            body = "\n".join(lines[i + 1:])
            loader = _DupKeyLoader(fm_text)
            try:
                meta = loader.get_single_data()
            except yaml.YAMLError as e:
                return ParsedPage(None, body, fm_text, str(e), had_bom=had_bom)
            finally:
                loader.dispose()
            dupes = getattr(loader, "duplicate_keys", [])
            if meta is None:
                meta = {}
            if not isinstance(meta, dict):
                return ParsedPage(None, body, fm_text,
                                  "frontmatter is not a mapping", had_bom=had_bom)
            return ParsedPage(meta, body, fm_text, None,
                              duplicate_keys=dupes, had_bom=had_bom)

    return ParsedPage(None, text, None,
                      "frontmatter delimiter --- not closed", had_bom=had_bom)


def parse_file(path: Path) -> ParsedPage:
    # plain utf-8 (not utf-8-sig) so a BOM survives into parse() and is reported
    return parse(path.read_text(encoding="utf-8"))
