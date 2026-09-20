"""Compatibility alias for :mod:`stockfinder.infrastructure.runtime`."""
import sys

from stockfinder.infrastructure import runtime as _implementation

sys.modules[__name__] = _implementation
