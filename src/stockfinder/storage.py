"""Compatibility alias for :mod:`stockfinder.infrastructure.storage`."""
import sys

from stockfinder.infrastructure import storage as _implementation

sys.modules[__name__] = _implementation
