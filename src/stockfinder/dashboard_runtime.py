"""Compatibility alias for :mod:`stockfinder.presentation.dashboard_runtime`."""

import sys

from stockfinder.presentation import dashboard_runtime as _implementation

sys.modules[__name__] = _implementation