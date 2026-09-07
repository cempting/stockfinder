"""Command-line launcher for the Stockfinder Streamlit application."""

import subprocess
import sys
from pathlib import Path


def main() -> int:
    """Launch the Streamlit application with the active Python interpreter."""
    ui_path = Path(__file__).with_name("ui.py")
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(ui_path)])


if __name__ == "__main__":
    from stockfinder.ui import main as streamlit_main

    streamlit_main()
