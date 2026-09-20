"""Compatibility alias for :mod:`stockfinder.presentation.widget_help`."""

import sys

from stockfinder.presentation import widget_help as _implementation

sys.modules[__name__] = _implementation