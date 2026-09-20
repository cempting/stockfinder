"""Compatibility alias for :mod:`stockfinder.presentation.ui`."""

import sys

from stockfinder.presentation import ui as _implementation

if __name__ == "__main__":
    _implementation.main()
else:
    sys.modules[__name__] = _implementation
