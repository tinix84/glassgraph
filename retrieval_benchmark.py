"""Compatibility import for the packaged evidence and benchmark authority."""
import sys

import frontmatter  # Bootstrap the package in an uninstalled source checkout.
from glassgraph.core import retrieval_benchmark as _implementation

sys.modules[__name__] = _implementation


def __getattr__(name):
    return getattr(_implementation, name)
