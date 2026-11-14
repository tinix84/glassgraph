"""Validated page rendering and compatibility writes through shared writer policy."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

import yaml

from glassgraph.config import ConfigError, VaultConfig
from glassgraph.wiki import schema

FIELD_ORDER = [
    "type", "aliases", "aliases_en", "aliases_cn", "tags", "created", "updated",
    "sources", "country", "kind", "category", "vendor", "released",
    "thesis", "status",
    "source_url", "source_lang", "source_created", "source_kind", "ingested",
    "touches", "summary",
    "relations", "relations_src_md5",
]


class ValidationError(Exception):
    def __init__(self, errors: list[str]):
        super().__init__("; ".join(errors))
        self.errors = errors


def serialize_frontmatter(meta: dict) -> str:
    """Serialize known fields in legacy order, then preserve extra field order."""
    ordered = {k: meta[k] for k in FIELD_ORDER if k in meta}
    ordered.update({k: v for k, v in meta.items() if k not in ordered})
    return yaml.safe_dump(ordered, allow_unicode=True, sort_keys=False,
                          default_flow_style=False, width=10_000)


def render_page(page_type: str, meta: dict, body: str) -> tuple[str, list[str]]:
    """Return complete page text and warnings without changing inputs or files."""
    if not isinstance(meta, dict):
        raise ValidationError(["Supply a metadata object"])
    if not isinstance(body, str):
        raise ValidationError(["Supply a string page body"])
    if not isinstance(page_type, str) or page_type not in schema.PAGE_TYPES:
        raise ValidationError(["Select a supported page type"])
    meta = dict(meta)
    if "relations" in meta:
        meta["relations_src_md5"] = hashlib.md5(body.strip("\n").encode("utf-8")).hexdigest()
    compute_aliases = page_type != "source" or meta.get("aliases_en") or meta.get("aliases_cn")
    if compute_aliases:
        # The union is computed. Validate its input lists before computing it.
        meta["aliases"] = []
    errors, warnings = schema.validate_meta(meta, page_type)
    if errors:
        raise ValidationError(errors)
    if compute_aliases:
        meta["aliases"] = schema.compute_aliases(meta.get("aliases_en") or [], meta.get("aliases_cn") or [])
    text = "---\n" + serialize_frontmatter(meta) + "---\n\n" + body.lstrip("\n")
    return text, warnings


def write_page(path: Path, page_type: str, meta: dict, body: str) -> list[str]:
    """Preserve the legacy writer API. Portable CLI callers use preview instead."""
    text, warnings = render_page(page_type, meta, body)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return warnings


def _input_path(config: VaultConfig, value: str | Path) -> Path:
    if not os.fspath(value) or "\0" in os.fspath(value):
        raise ConfigError("Supply a nonempty input path without null characters")
    return config.root / value


def preview(config: VaultConfig, target: str | Path, page_type: str,
            meta_path: str | Path, body_path: str | Path) -> tuple[str, list[str]]:
    """Render a proposed configured wiki target without creating it."""
    if not os.fspath(target) or "\0" in os.fspath(target):
        raise ConfigError("Supply a nonempty Markdown target")
    selected = config.root / target
    if not config.allows(selected):
        raise ConfigError("Select a target outside excluded directories")
    selected = selected.resolve()
    if not selected.is_relative_to(config.wiki) or selected.suffix.lower() != ".md":
        raise ConfigError("Select a Markdown target inside the configured wiki")
    if selected.exists() and not selected.is_file():
        raise ConfigError("Select a file target")
    meta_path = _input_path(config, meta_path)
    body_path = _input_path(config, body_path)
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        raise ConfigError("Read a valid metadata JSON file") from None
    body = body_path.read_text(encoding="utf-8-sig")
    return render_page(page_type, meta, body)


def main() -> None:
    """Retain the legacy direct-write command for the compatibility adapter."""
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--type", required=True, choices=schema.PAGE_TYPES)
    parser.add_argument("--path", required=True)
    parser.add_argument("--meta", required=True, help="JSON file with frontmatter metadata")
    parser.add_argument("--body", required=True, help="Markdown file with the page body")
    args = parser.parse_args()
    try:
        meta = json.loads(Path(args.meta).read_text(encoding="utf-8-sig"))
        body = Path(args.body).read_text(encoding="utf-8-sig")
        warnings = write_page(Path(args.path), args.type, meta, body)
    except ValidationError as error:
        print("VALIDATION FAILED — nothing written:", file=sys.stderr)
        for message in error.errors:
            print(f"  - {message}", file=sys.stderr)
        raise SystemExit(1)
    except (OSError, UnicodeError, ValueError) as error:
        print(f"write-page: {error}", file=sys.stderr)
        raise SystemExit(2)
    for warning in warnings:
        print(f"WARN: {warning}")
    print(f"written | {args.path}")
