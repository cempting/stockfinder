"""Streamlit Community Cloud entry point."""

import sys
from pathlib import Path


def run() -> None:
    source_root = Path(__file__).resolve().parent / "src"
    if str(source_root) not in sys.path:
        sys.path.insert(0, str(source_root))

    from stockfinder.ui import main

    main()


run()
