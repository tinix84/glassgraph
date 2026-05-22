"""Shared pytest fixtures for the comparison test suite."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parents[1]  # .tools/comparison/


def _load(name: str) -> object:
    """Load a sibling module via importlib (matches entity_linker convention)."""
    if name in sys.modules:
        return sys.modules[name]
    src = _HERE / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def load_graphify_mod():
    return _load("load_graphify")


@pytest.fixture(scope="session")
def load_ours_mod():
    return _load("load_ours")


@pytest.fixture(scope="session")
def metrics_mod():
    return _load("metrics")
