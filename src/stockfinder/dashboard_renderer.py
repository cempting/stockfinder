"""Compatibility alias for :mod:`stockfinder.presentation.dashboard_renderer`."""

import sys

from stockfinder.presentation import dashboard_renderer as _implementation

sys.modules[__name__] = _implementation