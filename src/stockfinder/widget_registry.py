"""Compatibility alias for :mod:`stockfinder.presentation.widget_registry`."""

import sys

from stockfinder.presentation import widget_registry as _implementation

sys.modules[__name__] = _implementation