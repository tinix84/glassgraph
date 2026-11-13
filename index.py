"""Compatibility import for the packaged Stage 1 authority."""
import sys
import importlib.util
from pathlib import Path

try:
    from glassgraph.core import index as _implementation
except ModuleNotFoundError as error:
    if error.name != "glassgraph":
        raise
    # Bootstrap package code without changing the caller's import path.
    _spec = importlib.util.spec_from_file_location(
        "_glassgraph_index_bootstrap", Path(__file__).resolve().with_name("frontmatter.py"),
    )
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = _module
    _spec.loader.exec_module(_module)
    from glassgraph.core import index as _implementation


def __getattr__(name):
    return getattr(_implementation, name)


WIKI_ROOT = Path(__file__).resolve().parents[1].parent / "wiki"
INDEX_DIR = Path(__file__).resolve().parent.parent / "index"
MANIFEST_PATH = INDEX_DIR / "manifest.json"
ALIASES_PATH = INDEX_DIR / "aliases.json"


def build_index(wiki_root=WIKI_ROOT, manifest_path=MANIFEST_PATH, aliases_path=ALIASES_PATH):
    return _implementation.build_index(wiki_root, manifest_path, aliases_path)


def is_stale(wiki_root=WIKI_ROOT, manifest_path=MANIFEST_PATH):
    return _implementation.is_stale(wiki_root, manifest_path)


def get_automaton(wiki_root=WIKI_ROOT, manifest_path=MANIFEST_PATH, aliases_path=ALIASES_PATH):
    return build_index(wiki_root, manifest_path, aliases_path)
