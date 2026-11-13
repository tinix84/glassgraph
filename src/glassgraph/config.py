"""Shared vault-root discovery and configuration for portable commands."""
from __future__ import annotations

import os
from pathlib import Path, PureWindowsPath
from dataclasses import dataclass
from collections.abc import Iterator
from stat import S_ISREG

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 compatibility.
    import tomli as tomllib

ENTITY_TYPES = {"companies": "company", "technologies": "technology",
                "products": "product", "markets": "market", "themes": "theme"}


class ConfigError(ValueError):
    """Report an invalid vault root or configuration."""


def discover_root(root: str | Path | None = None, *, start: Path | None = None) -> Path:
    """Resolve an explicit root, environment root, or nearest upward marker."""
    selected = root if root is not None else os.environ.get("GLASSGRAPH_ROOT")
    if selected is not None:
        if not os.fspath(selected) or "\0" in os.fspath(selected):
            raise ConfigError("Supply a nonempty vault root")
        resolved = Path(selected).resolve()
        if not resolved.is_dir():
            raise ConfigError("Select an existing vault directory")
        return resolved
    current = Path.cwd() if start is None else Path(start).resolve()
    if not current.is_dir():
        raise ConfigError("Start root discovery from an existing directory")
    for candidate in (current, *current.parents):
        if (candidate / ".glassgraph").is_dir():
            return candidate
    raise ConfigError("Select --root PATH, set GLASSGRAPH_ROOT, or add a .glassgraph directory")


def _inside(root: Path, value: str) -> Path:
    if (not isinstance(value, str) or not value or "\0" in value or Path(value).is_absolute()
            or PureWindowsPath(value).drive):
        raise ConfigError("Use nonempty vault-relative paths")
    path = (root / value).resolve()
    if not path.is_relative_to(root):
        raise ConfigError("Keep configured paths inside the vault")
    return path


@dataclass(frozen=True)
class VaultConfig:
    root: Path
    wiki: Path
    raw: Path
    entity_dirs: tuple[str, ...]
    exclude: tuple[Path, ...]
    zotero_db: Path | None

    def markdown_files(self, directory: Path) -> Iterator[Path]:
        """Scan one configured directory without hiding read failures."""
        if not self.allows(directory):
            return
        try:
            pages = sorted(page for page in directory.iterdir() if page.match("*.md"))
        except FileNotFoundError:
            return
        for page in pages:
            if self.allows(page) and S_ISREG(page.stat().st_mode):
                yield page

    def allows(self, path: Path) -> bool:
        """Exclude configured paths and reject scanned files outside the vault."""
        if any(path.is_relative_to(excluded) for excluded in self.exclude):
            return False
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise ConfigError("Keep scanned files inside the vault")
        return not any(resolved.is_relative_to(excluded) for excluded in self.exclude)


def load_config(root: str | Path | None = None, *, start: Path | None = None) -> VaultConfig:
    """Load optional TOML settings through the shared root resolver."""
    root = discover_root(root, start=start)
    config_path = root / ".glassgraph" / "config.toml"
    if not config_path.resolve().is_relative_to(root):
        raise ConfigError("Keep the configuration file inside the vault")
    try:
        try:
            text = config_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            text = ""
        data = tomllib.loads(text)
    except (OSError, UnicodeError, ValueError):
        raise ConfigError("Read a valid .glassgraph/config.toml file") from None
    paths = data.get("paths", {})
    zotero = data.get("zotero", {})
    if (set(data) - {"paths", "zotero"} or not isinstance(paths, dict)
            or not isinstance(zotero, dict) or set(paths) - {"raw", "wiki", "entity_dirs", "exclude"}
            or set(zotero) - {"db"}):
        raise ConfigError("Use supported paths and zotero configuration fields")
    dirs = paths.get("entity_dirs", list(ENTITY_TYPES))
    excludes = paths.get("exclude", [".temp"])
    if (not isinstance(dirs, list) or any(not isinstance(d, str) or not d
            or d.casefold() in {".", "..", "sources"} or "/" in d or "\\" in d or "\0" in d
            or PureWindowsPath(d).drive for d in dirs)
            or len({d.casefold() for d in dirs}) != len(dirs) or not isinstance(excludes, list)):
        raise ConfigError("Use unique entity directory names and an exclude list")
    db = zotero.get("db")
    if db is not None and (not isinstance(db, str) or not db or "\0" in db):
        raise ConfigError("Supply a nonempty Zotero database path")
    return VaultConfig(root, _inside(root, paths.get("wiki", "wiki")),
                       _inside(root, paths.get("raw", "raw")), tuple(dirs),
                       tuple(_inside(root, value) for value in excludes),
                       (root / db).resolve() if db is not None else None)
