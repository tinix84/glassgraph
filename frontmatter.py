"""Compatibility import for legacy scripts; rules live in glassgraph.core."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

try:
    from glassgraph.core import frontmatter as _implementation
except ModuleNotFoundError as error:
    if error.name != "glassgraph":
        raise
    # Bootstrap an uninstalled source checkout without changing sys.path.
    _package = Path(__file__).resolve().parent / "src" / "glassgraph"
    _spec = importlib.util.spec_from_file_location(
        "glassgraph", _package / "__init__.py",
        submodule_search_locations=[str(_package)],
    )
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["glassgraph"] = _module
    _spec.loader.exec_module(_module)
    from glassgraph.core import frontmatter as _implementation

PAGE_TYPES = _implementation.PAGE_TYPES
SOURCE_REQUIRED = _implementation.SOURCE_REQUIRED
WIKILINK_RE = _implementation.WIKILINK_RE
ParsedPage = _implementation.ParsedPage
parse = _implementation.parse
parse_file = _implementation.parse_file
validate_metadata = _implementation.validate_metadata
