from datetime import UTC, datetime

import pandas as pd

from stockfinder.runtime import application_data_dir
from stockfinder.storage import (
    CompanyProfileCache,
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


def test_position_round_trip_and_delete(tmp_path) -> None:
    repository = Repository(tmp_path / "stockfinder.db")

    repository.save_position("msft", 4.0, 420.0, "2026-08-27")
    assert repository.positions().iloc[0]["symbol"] == "MSFT"

    repository.delete_position("MSFT")
    assert repository.positions().empty


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