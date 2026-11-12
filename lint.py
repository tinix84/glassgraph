"""Compatibility import for the packaged deterministic lint authority."""
import sys

import frontmatter  # Bootstrap an uninstalled source checkout.
from glassgraph.core import lint as _implementation

sys.modules[__name__] = _implementation


def __getattr__(name):
    return getattr(_implementation, name)
