"""Read-only PreToolUse gate for proposed wiki Write and Edit operations."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from glassgraph.config import ConfigError, load_config
from glassgraph.core import frontmatter

EXEMPT_NAMES = {"index.md", "log.md", "overview.md"}
PAGE_TYPES = {"company", "technology", "product", "theme", "source"}
_TOUCH_RE = re.compile(r"^\[\[[^\[\]]+\]\]$")


def resulting_content(tool_name: str, tool_input: dict) -> str | None:
    """Return proposed text, or None for an Edit that cannot match."""
    if tool_name == "Write":
        content = tool_input.get("content", "")
        if not isinstance(content, str):
            raise ConfigError("Supply string content for Write")
        return content
    if tool_name == "Edit":
        old = tool_input.get("old_string", "")
        new = tool_input.get("new_string", "")
        replace_all = tool_input.get("replace_all", False)
        if not isinstance(old, str) or not isinstance(new, str) or type(replace_all) is not bool:
            raise ConfigError("Supply string Edit values and a boolean replace_all")
        try:
            current = Path(tool_input.get("file_path", "")).read_text(encoding="utf-8")
        except FileNotFoundError:
            return None
        if not old or old not in current:
            return None
        return current.replace(old, new) if replace_all else current.replace(old, new, 1)
    return None


def check(content: str) -> list[str]:
    """Apply the legacy structural gate through the shared parser."""
    errors: list[str] = []
    if content.startswith("\ufeff"):
        errors.append("content starts with a UTF-8 BOM — write plain UTF-8")
    parsed = frontmatter.parse(content)
    if parsed.error:
        errors.append(f"frontmatter YAML error: {parsed.error}")
        return errors
    if parsed.metadata is None:
        errors.append("wiki page has no frontmatter block (every wiki page needs one)")
        return errors
    if parsed.duplicate_keys:
        errors.append(f"duplicate frontmatter key(s): {parsed.duplicate_keys}")
    ptype = parsed.metadata.get("type")
    if not isinstance(ptype, str) or ptype not in PAGE_TYPES:
        errors.append(f"type: {ptype!r} is not one of {sorted(PAGE_TYPES)}")
    touches = parsed.metadata.get("touches")
    if touches is not None:
        if not isinstance(touches, list) or not all(
                isinstance(t, str) and _TOUCH_RE.match(t.strip()) for t in touches):
            errors.append('touches: must be a block list of quoted "[[Entity]]" strings'
                          " (touches: [] if empty) — see CLAUDE.md ingest contract")
    rels = parsed.metadata.get("relations")
    if rels is not None and not (
            isinstance(rels, list) and all(
                isinstance(r, dict) and {"s", "p", "o", "by"} <= r.keys() for r in rels)):
        errors.append("relations: must be a list of {s,p,o,by} mappings")
    return errors


def _target(data: dict, tool_input: dict) -> Path:
    value = tool_input.get("file_path", "")
    cwd = data.get("cwd", str(Path.cwd()))
    if not isinstance(value, str) or not value or "\0" in value:
        raise ConfigError("Supply a nonempty file_path")
    if not isinstance(cwd, str) or not cwd or "\0" in cwd or not Path(cwd).is_absolute():
        raise ConfigError("Supply an absolute payload cwd")
    return Path(cwd) / value


def _in_scope(path: Path, root: str | Path | None) -> bool:
    # New Write targets can have parents that do not exist yet.
    start = path.absolute().parent
    while not start.exists() and start != start.parent:
        start = start.parent
    config = load_config(root, start=start)
    lexical = path.absolute()
    resolved = path.resolve()
    if not lexical.is_relative_to(config.wiki) and not resolved.is_relative_to(config.wiki):
        return False
    if not resolved.is_relative_to(config.wiki):
        raise ConfigError("Keep wiki targets inside the configured wiki")
    if not config.allows(lexical):
        return False
    parts = resolved.relative_to(config.wiki).parts
    return ".archive" not in {part.lower() for part in parts}


def run(data: object, root: str | Path | None = None, *, legacy: bool = False) -> int:
    """Validate one payload without changing its target or any vault state."""
    if not isinstance(data, dict) or data.get("tool_name") not in ("Write", "Edit"):
        return 0
    tool_input = data.get("tool_input")
    if not isinstance(tool_input, dict):
        return 0
    try:
        if legacy:
            value = tool_input.get("file_path", "")
            if not isinstance(value, str) or "\0" in value:
                raise ConfigError("Supply a string file_path")
            path = Path(value)
        else:
            path = _target(data, tool_input)
        if path.suffix.lower() != ".md" or path.name in EXEMPT_NAMES:
            return 0
        if legacy:
            parts = {part.lower() for part in path.parts}
            scoped = "wiki" in parts and ".archive" not in parts
        else:
            scoped = _in_scope(path, root)
        if not scoped:
            return 0
        content = resulting_content(data["tool_name"], {**tool_input, "file_path": str(path)})
        if content is None:
            return 0
        errors = check(content)
        if not errors:
            return 0
        guidance = ("Fix the frontmatter and retry, or use .tools/wikilib/write_page.py.\n"
                    if legacy else "Fix the frontmatter and retry.\n")
        sys.stderr.write("WIKI WRITE BLOCKED — invalid frontmatter:\n"
                         + "".join(f"  - {e}\n" for e in errors)
                         + guidance)
        return 2
    except (ConfigError, OSError, UnicodeError, ValueError) as error:
        print(f"glassgraph hook: {error}", file=sys.stderr)
        return 2


def from_stdin(root: str | Path | None = None, *, legacy: bool = False) -> int:
    """Read the hook envelope and return the admission status."""
    try:
        data = json.load(sys.stdin)
    except (ValueError, UnicodeError):
        return 0
    return run(data, root, legacy=legacy)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", help="Vault directory")
    args = parser.parse_args(argv)
    return from_stdin(args.root)


if __name__ == "__main__":
    raise SystemExit(main())
