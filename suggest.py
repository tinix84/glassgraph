"""Compatibility import for the packaged alias suggestion authority."""
import sys
import importlib.util
from pathlib import Path

try:
    from glassgraph.core import suggest as _implementation
except ModuleNotFoundError as error:
    if error.name != "glassgraph":
        raise
    # Bootstrap package code without changing the caller's import path.
    _package = Path(__file__).resolve().parent / "src" / "glassgraph"
    _spec = importlib.util.spec_from_file_location(
        "glassgraph", _package / "__init__.py",
        submodule_search_locations=[str(_package)],
    )
    _module = importlib.util.module_from_spec(_spec)
    sys.modules["glassgraph"] = _module
    _spec.loader.exec_module(_module)
    from glassgraph.core import suggest as _implementation

sys.modules[__name__] = _implementation


def __getattr__(name):
    return getattr(_implementation, name)
