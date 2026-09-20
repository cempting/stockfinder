"""Compatibility alias for :mod:`stockfinder.infrastructure.config`."""
import sys

from stockfinder.infrastructure import config as _implementation

sys.modules[__name__] = _implementation