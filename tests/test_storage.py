import sqlite3
from datetime import UTC, datetime

import pandas as pd
import pytest

from stockfinder.runtime import application_data_dir
from stockfinder.storage import (
    CompanyProfileCache,
    GettexInstrumentStore,
    MarketHistoryCache,
    Repository,
    ScanSnapshot,
    ScanSnapshotStore,
)


def test_watchlist_round_trip(tmp_path) -> None:
    repository = Repository(tmp_path / "stockfinder.db")

    repository.save_watchlist("nvda", "Strong growth", 100.0, 130.0, 92.0)
    row = repository.watchlist().iloc[0]

    assert row["symbol"] == "NVDA"
    assert row["notes"] == "Strong growth"
    assert row["target_price"] == 130.0

    repository.save_watchlist("nvda", "Updated", 105.0, None, 95.0)
    updated = repository.watchlist().iloc[0]
    assert updated["notes"] == "Updated"
    assert pd.isna(updated["target_price"])

    repository.delete_watchlist("NVDA")
    assert repository.watchlist().empty


def test_market_history_cache_merges_and_restores_last_known_data(tmp_path) -> None:
    cache = MarketHistoryCache(tmp_path / "market")
    first = pd.DataFrame(
        {"Close": [100.0, 101.0], "Volume": [1000, 1100]},
        index=pd.date_range("2026-01-01", periods=2),
    )
    update = pd.DataFrame(
        {"Close": [102.0, 103.0], "Volume": [1200, 1300]},
        index=pd.date_range("2026-01-02", periods=2),
    )

    merged = cache.merge("TEST", first)
    merged = cache.merge("TEST", update)
    restored = MarketHistoryCache(tmp_path / "market").load("TEST")

    assert merged["Close"].tolist() == [100.0, 102.0, 103.0]
    assert restored is not None
    assert restored.equals(merged)
    assert cache.is_fresh("TEST", 1)


def test_application_data_dir_honors_cloud_mount(monkeypatch, tmp_path) -> None:
    cloud_data = tmp_path / "cloud-data"
    monkeypatch.setenv("STOCKFINDER_DATA_DIR", str(cloud_data))

    assert application_data_dir() == cloud_data
    assert cloud_data.is_dir()


def test_company_profile_cache_persists_json(tmp_path) -> None:
    cache = CompanyProfileCache(tmp_path / "profiles")
    profile = {"longName": "Test Corp", "marketCap": 1_000_000}

    cache.save("TEST", profile)

    assert CompanyProfileCache(tmp_path / "profiles").load("TEST") == profile
    assert cache.is_fresh("TEST", 1)


def test_gettex_store_imports_common_broker_symbol_columns(tmp_path) -> None:
    store = GettexInstrumentStore(tmp_path / "gettex.csv")

    imported = store.import_csv(b"Ticker;Name\naapl;Apple\nSAP.DE;SAP\naapl;Apple\n")

    assert imported["Symbol"].tolist() == ["AAPL", "SAP.DE"]
    assert GettexInstrumentStore(tmp_path / "gettex.csv").load().equals(imported)


def test_gettex_store_rejects_csv_without_symbol_column(tmp_path) -> None:
    store = GettexInstrumentStore(tmp_path / "gettex.csv")

    with pytest.raises(ValueError, match="Symbol"):
        store.import_csv(b"ISIN;Name\nDE0007164600;SAP\n")


def test_position_round_trip_and_delete(tmp_path) -> None:
    repository = Repository(tmp_path / "stockfinder.db")

    repository.save_position("msft", 4.0, 420.0, "2026-08-27", "EUR")
    assert repository.positions().iloc[0]["symbol"] == "MSFT"
    assert repository.positions().iloc[0]["currency"] == "EUR"

    repository.save_position("msft", 5.0, 410.0, "2026-08-28")
    updated = repository.positions().iloc[0]
    assert updated["quantity"] == 5.0
    assert updated["entry_price"] == 410.0

    repository.delete_position("MSFT")
    assert repository.positions().empty


def test_repository_migrates_legacy_positions_to_usd(tmp_path) -> None:
    path = tmp_path / "stockfinder.db"
    with sqlite3.connect(path) as connection:
        connection.execute(
            "CREATE TABLE positions (symbol TEXT PRIMARY KEY, quantity REAL, "
            "entry_price REAL, entry_date TEXT, updated_at TEXT)"
        )
        connection.execute(
            "INSERT INTO positions VALUES ('AAPL', 2, 100, '2026-01-01', 'now')"
        )

    repository = Repository(path)

    assert repository.positions().iloc[0]["currency"] == "USD"


def test_scan_snapshot_round_trip(tmp_path) -> None:
    store = ScanSnapshotStore(tmp_path / "latest_scan")
    completed_at = datetime(2026, 8, 30, 18, 0, tzinfo=UTC)
    snapshot = ScanSnapshot(
        universe=pd.DataFrame({"Symbol": ["AAPL"]}),
        sectors=pd.DataFrame({"Sector": ["Technology"]}),
        industries=pd.DataFrame({"Industry": ["Software"]}),
        candidates=pd.DataFrame({"Symbol": ["PATH"], "Setup score": [82.0]}),
        completed_at=completed_at,
        source="Test source",
        coverage=97.5,
        mode="extended",
        model_version="test-v1",
        warning="One symbol missing",
        risk_profiles=pd.DataFrame(
            {"Symbol": ["AAPL"], "Market risk": [35.0], "Last price": [250.0]}
        ),
    )

    store.save(snapshot)
    loaded = store.load()

    assert loaded is not None
    assert loaded.completed_at == completed_at
    assert loaded.source == "Test source"
    assert loaded.coverage == 97.5
    assert loaded.mode == "extended"
    assert loaded.model_version == "test-v1"
    pd.testing.assert_frame_equal(loaded.candidates, snapshot.candidates)
    pd.testing.assert_frame_equal(loaded.risk_profiles, snapshot.risk_profiles)


def test_scan_snapshot_loads_without_legacy_risk_profiles(tmp_path) -> None:
    store = ScanSnapshotStore(tmp_path / "latest_scan")
    snapshot = ScanSnapshot(
        universe=pd.DataFrame({"Symbol": ["AAPL"]}),
        sectors=pd.DataFrame(),
        industries=pd.DataFrame(),
        candidates=pd.DataFrame(),
        completed_at=datetime(2026, 8, 30, 18, 0, tzinfo=UTC),
        source="Legacy source",
        coverage=100,
        mode="standard",
        model_version="legacy",
    )
    store.save(snapshot)
    (store.path / "risk_profiles.parquet").unlink()

    loaded = store.load()

    assert loaded is not None
    assert loaded.risk_profiles.empty