"""Runtime paths and environment configuration."""

import os
from pathlib import Path
from tempfile import gettempdir


def application_data_dir() -> Path:
    """Return the writable application-state directory for local or cloud use."""
    configured = os.environ.get("STOCKFINDER_DATA_DIR")
    path = Path(configured).expanduser() if configured else Path("data")
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".write-test"
        probe.touch()
        probe.unlink()
        return path
    except OSError:
        fallback = Path(gettempdir()) / "stockfinder"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback
