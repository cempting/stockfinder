"""Compatibility alias for :mod:`stockfinder.presentation.dashboard`."""

import sys

from stockfinder.presentation import dashboard as _implementation

sys.modules[__name__] = _implementation