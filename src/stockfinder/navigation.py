"""Compatibility alias for :mod:`stockfinder.presentation.navigation`."""

import sys

from stockfinder.presentation import navigation as _implementation

sys.modules[__name__] = _implementation