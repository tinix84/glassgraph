"""Validated page rendering and compatibility writes through shared writer policy."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path

import yaml

from glassgraph.config import ConfigError, ENTITY_TYPES, VaultConfig
from glassgraph.core import frontmatter
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
    """Preserve the legacy writer API. Portable CLI callers use preview or apply instead."""
    text, warnings = render_page(page_type, meta, body)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")
    return warnings


class AdmissionError(Exception):
    """Report why an apply request may not write its target."""

    def __init__(self, reasons: list[str]):
        super().__init__("; ".join(reasons))
        self.reasons = reasons


def _input_path(config: VaultConfig, value: str | Path) -> Path:
    if not os.fspath(value) or "\0" in os.fspath(value):
        raise ConfigError("Supply a nonempty input path without null characters")
    return config.root / value


def _target(config: VaultConfig, target: str | Path) -> Path:
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
    return selected


def _render_inputs(config: VaultConfig, page_type: str, meta_path: str | Path,
                   body_path: str | Path) -> tuple[dict, str, list[str]]:
    meta_path = _input_path(config, meta_path)
    body_path = _input_path(config, body_path)
    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8-sig"))
    except json.JSONDecodeError:
        raise ConfigError("Read a valid metadata JSON file") from None
    body = body_path.read_text(encoding="utf-8-sig")
    text, warnings = render_page(page_type, meta, body)
    return meta, text, warnings


def preview(config: VaultConfig, target: str | Path, page_type: str,
            meta_path: str | Path, body_path: str | Path) -> tuple[str, list[str]]:
    """Render a proposed configured wiki target without creating it."""
    _target(config, target)
    _, text, warnings = _render_inputs(config, page_type, meta_path, body_path)
    return text, warnings


def _relative(config: VaultConfig, page: Path) -> str:
    return page.resolve().relative_to(config.root).as_posix()


def _canonical_target(config: VaultConfig, target: Path, page_type: str) -> tuple[Path, list[str]]:
    """Return the target in the configured folder spelling, or the folder refusal reasons."""
    folder = target.parent
    name = folder.name.casefold()
    if folder.parent != config.wiki:
        return target, ["Place the page directly in the sources folder or a configured entity folder"]
    if page_type == "source":
        if name != "sources":
            return target, ["Place source pages directly in the sources folder"]
        spelling = "sources"
    else:
        spelling = next((d for d in config.entity_dirs if d.casefold() == name), None)
        if spelling is None:
            return target, [f"Place {page_type} pages directly in a configured entity folder"]
        known = ENTITY_TYPES.get(name)
        if known is not None and known != page_type:
            return target, [f"The {folder.name} folder accepts only {known} pages"]
    # Scanners read only the configured spelling. A case-sensitive filesystem must not get a second folder.
    canonical = config.wiki / spelling / target.name
    if not config.allows(canonical):
        raise ConfigError("Select a target outside excluded directories")
    return canonical, []


def _alias_reasons(config: VaultConfig, target: Path, meta: dict) -> list[str]:
    # Import here: the legacy writer adapter must not need the alias trie dependency.
    from glassgraph.core import index
    from glassgraph.core.lookup import resolve_alias
    owners = index.alias_owners(config.wiki, config=config)
    names = [target.stem, *schema.compute_aliases(meta.get("aliases_en") or [], meta.get("aliases_cn") or [])]
    reasons = []
    for name in dict.fromkeys(names):
        owner = resolve_alias(name, owners)
        if owner is not None:
            reasons.append(f"Alias {name!r} already resolves to {_relative(config, owner.page)}")
    return reasons


def _source_url_reasons(config: VaultConfig, meta: dict) -> tuple[list[str], list[str]]:
    url = meta.get("source_url")
    if not isinstance(url, str) or not url.strip():
        return [], []
    reasons, skipped = [], 0
    for page in config.markdown_files(config.wiki / "sources"):
        try:
            parsed = frontmatter.parse_file(page)
        except UnicodeDecodeError:
            skipped += 1
            continue
        if parsed.error:
            skipped += 1
            continue
        other = (parsed.metadata or {}).get("source_url")
        if isinstance(other, str) and other.strip() == url.strip():
            reasons.append(f"source_url is already used by {_relative(config, page)}")
    warnings = [f"duplicate source_url check skipped {skipped} unparsable source page(s)"] if skipped else []
    return reasons, warnings


def admit(config: VaultConfig, target: Path, page_type: str, meta: dict, *,
          overwrite: bool = False) -> tuple[Path, bool, list[str]]:
    """Admit a resolved absolute target, or raise AdmissionError with every refusal reason.

    Return the target in the configured folder spelling, whether it exists, and warnings.
    Alias and source_url checks apply only to new pages. An overwrite skips them.
    """
    target, reasons = _canonical_target(config, target, page_type)
    warnings: list[str] = []
    exists = target.exists()
    if exists:
        if not overwrite:
            reasons.append("The target exists. Use --overwrite to replace it")
    elif page_type == "source":
        url_reasons, warnings = _source_url_reasons(config, meta)
        reasons += url_reasons
    else:
        reasons += _alias_reasons(config, target, meta)
    if reasons:
        raise AdmissionError(reasons)
    return target, exists, warnings


def _move_new(source: Path, target: Path) -> None:
    """Move a file into place. Raise FileExistsError if the target exists."""
    if os.name == "nt":
        os.rename(source, target)  # Windows rename never replaces an existing file.
    else:
        os.link(source, target)  # POSIX rename replaces a file. A hard link does not.


def _store(target: Path, text: str, *, replace: bool) -> None:
    """Write a complete, synced temporary file, then move it into place.

    Without replace, a page that appears during the write is kept. A failure removes
    the temporary file and the folders that this call created.
    """
    created = [folder for folder in (target.parent, *target.parent.parents) if not folder.exists()]
    target.parent.mkdir(parents=True, exist_ok=True)
    # A short fixed name keeps long target names inside the filename length limit.
    temporary = target.parent / f".gg-{secrets.token_hex(8)}.tmp"
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        if replace:
            os.replace(temporary, target)
        else:
            try:
                _move_new(temporary, target)
            except FileExistsError:
                raise AdmissionError(["The target appeared during the write. Nothing was replaced"]) from None
    except BaseException:
        temporary.unlink(missing_ok=True)
        for folder in created:
            with contextlib.suppress(OSError):
                folder.rmdir()
        raise
    temporary.unlink(missing_ok=True)


def apply(config: VaultConfig, target: str | Path, page_type: str, meta_path: str | Path,
          body_path: str | Path, *, overwrite: bool = False) -> tuple[Path, list[str]]:
    """Render, admit, and write one configured wiki page. Return its path and warnings."""
    selected = _target(config, target)
    meta, text, warnings = _render_inputs(config, page_type, meta_path, body_path)
    selected, exists, admitted = admit(config, selected, page_type, meta, overwrite=overwrite)
    _store(selected, text, replace=exists)
    return selected, warnings + admitted


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
