"""Compatibility import for the packaged co-occurrence cluster authority."""
import sys
import importlib.util
from pathlib import Path

try:
    from glassgraph.core import cluster as _implementation
except ModuleNotFoundError as error:
    if error.name != "glassgraph":
        raise
    # Bootstrap package code without changing the caller's import path.
    _spec = importlib.util.spec_from_file_location(
        "_glassgraph_cluster_bootstrap", Path(__file__).resolve().with_name("frontmatter.py"),
    )
    _module = importlib.util.module_from_spec(_spec)
    sys.modules[_spec.name] = _module
    _spec.loader.exec_module(_module)
    from glassgraph.core import cluster as _implementation

sys.modules[__name__] = _implementation


def __getattr__(name):
    return getattr(_implementation, name)
