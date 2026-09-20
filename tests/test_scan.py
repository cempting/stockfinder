from datetime import UTC, datetime

import numpy as np
import pandas as pd
import pytest

from stockfinder.data import DataResult
from stockfinder.infrastructure.config import default_analysis_config
from stockfinder.infrastructure.storage import ScanSnapshot, ScanSnapshotStore
from stockfinder.scan import (
    RefreshAlreadyRunningError,
    main,
    refresh_market_scan,
    refresh_process_lock,
)


def test_refresh_market_scan_builds_and_persists_snapshot(tmp_path) -> None:
    dates = pd.bdate_range("2025-01-01", periods=220)
    universe = pd.DataFrame(
        {
            "Symbol": ["ONE", "TWO"],
            "Name": ["One", "Two"],
            "Region": ["Europe", "Europe"],
            "Country": ["Germany", "France"],
            "Sector": ["Technology", "Technology"],
            "Industry": ["Software", "Software"],
        }
    )
    histories = {
        symbol: pd.DataFrame(
            {
                "High": close + 1,
                "Low": close - 1,
                "Close": close,
                "Volume": np.full(len(dates), 1_000_000),
            },
            index=dates,
        )
        for symbol, close in (
            ("ONE", np.linspace(100, 150, len(dates))),
            ("TWO", np.linspace(90, 130, len(dates))),
        )
    }
    events = []
    store = ScanSnapshotStore(tmp_path / "latest_scan")

    snapshot = refresh_market_scan(
        default_analysis_config(),
        "standard",
        store,
        as_of=datetime(2026, 9, 20, tzinfo=UTC).date(),
        universe_loader=lambda as_of: DataResult(
            universe, "Test universe", datetime.now(UTC)
        ),
        history_loader=lambda symbols, period: DataResult(
            {symbol: histories[symbol] for symbol in symbols},
            "Test histories",
            datetime.now(UTC),
        ),
        progress=lambda *event: events.append(event),
    )

    assert snapshot.coverage == 100.0
    assert snapshot.mode == "standard"
    assert snapshot.model_version.endswith("listing_region")
    assert not snapshot.sectors.empty
    assert not snapshot.industries.empty
    assert len(snapshot.risk_profiles) == 2
    assert store.load() is not None
    assert events[-1] == ("Complete", 2, 2, 2)


def test_refresh_cli_returns_warning_for_low_coverage(
    monkeypatch, tmp_path, capsys
) -> None:
    monkeypatch.setenv("STOCKFINDER_DATA_DIR", str(tmp_path))

    def fake_refresh(config, mode, store, **kwargs) -> ScanSnapshot:
        del config, store
        kwargs["progress"]("Loading price history", 7, 10, 7)
        return ScanSnapshot(
            universe=pd.DataFrame({"Symbol": ["TEST"]}),
            sectors=pd.DataFrame({"Sector": ["Technology"]}),
            industries=pd.DataFrame({"Industry": ["Software"]}),
            candidates=pd.DataFrame(),
            completed_at=datetime.now(UTC),
            source="Test",
            coverage=70.0,
            mode=mode,
            model_version="test",
        )

    assert main(["--minimum-coverage-pct", "90"], refresh=fake_refresh) == 1

    output = capsys.readouterr().out
    assert "7/10 · 7 usable" in output
    assert "Coverage below minimum 90.0%" in output


def test_refresh_process_lock_rejects_overlapping_job(tmp_path) -> None:
    lock_path = tmp_path / ".market-refresh.lock"

    with refresh_process_lock(lock_path):
        with pytest.raises(RefreshAlreadyRunningError):
            with refresh_process_lock(lock_path):
                pass

    with refresh_process_lock(lock_path):
        assert lock_path.exists()


def test_refresh_cli_returns_overlap_exit_code(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("STOCKFINDER_DATA_DIR", str(tmp_path))
    lock_path = tmp_path / ".market-refresh.lock"

    with refresh_process_lock(lock_path):
        assert main([], refresh=lambda *args, **kwargs: None) == 3

    assert "Another market refresh owns" in capsys.readouterr().out