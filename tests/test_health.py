import json
import sqlite3
from datetime import UTC, datetime, timedelta

import pandas as pd

from stockfinder.health import evaluate_health, health_exit_code, main
from stockfinder.infrastructure.config import default_analysis_config
from stockfinder.infrastructure.storage import ScanSnapshot, ScanSnapshotStore


def _save_snapshot(path, completed_at: datetime, coverage: float = 95.0) -> None:
    frame = pd.DataFrame({"Symbol": ["TEST"]})
    ScanSnapshotStore(path / "latest_scan").save(
        ScanSnapshot(
            universe=frame,
            sectors=pd.DataFrame({"Sector": ["Technology"]}),
            industries=pd.DataFrame({"Industry": ["Software"]}),
            candidates=pd.DataFrame(),
            completed_at=completed_at,
            source="Test",
            coverage=coverage,
            mode="standard",
            model_version="test-v1",
            risk_profiles=pd.DataFrame(
                {"Symbol": ["TEST"], "Last price": [100.0]}
            ),
        )
    )


def test_health_reports_valid_persistent_state(tmp_path) -> None:
    now = datetime(2026, 9, 20, 12, tzinfo=UTC)
    _save_snapshot(tmp_path, now - timedelta(hours=12))
    (tmp_path / "analysis_config.json").write_text(
        json.dumps(default_analysis_config()), encoding="utf-8"
    )
    with sqlite3.connect(tmp_path / "stockfinder.db") as connection:
        connection.execute("CREATE TABLE state (value TEXT)")

    checks = evaluate_health(tmp_path, now=now)

    assert health_exit_code(checks) == 0
    assert {check.status for check in checks} == {"OK"}


def test_health_fails_stale_low_coverage_snapshot(tmp_path) -> None:
    now = datetime(2026, 9, 20, 12, tzinfo=UTC)
    _save_snapshot(tmp_path, now - timedelta(hours=120), coverage=70.0)

    checks = evaluate_health(tmp_path, now=now)

    assert health_exit_code(checks) == 2
    failed = {check.name for check in checks if check.status == "FAIL"}
    assert failed == {"Scan freshness", "History coverage"}


def test_health_surfaces_snapshot_warning(tmp_path) -> None:
    now = datetime(2026, 9, 20, 12, tzinfo=UTC)
    _save_snapshot(tmp_path, now)
    store = ScanSnapshotStore(tmp_path / "latest_scan")
    snapshot = store.load()
    assert snapshot is not None
    store.save(
        ScanSnapshot(
            **{
                **snapshot.__dict__,
                "warning": "Some provider batches had gaps",
            }
        )
    )

    checks = evaluate_health(tmp_path, now=now)

    assert health_exit_code(checks) == 1
    assert checks[-1] == checks[-1].__class__(
        "Snapshot warning", "WARN", "Some provider batches had gaps"
    )


def test_health_cli_emits_json_and_failure_exit(monkeypatch, tmp_path, capsys) -> None:
    monkeypatch.setenv("STOCKFINDER_DATA_DIR", str(tmp_path))

    assert main(["--json"]) == 2

    payload = json.loads(capsys.readouterr().out)
    assert payload["status"] == "FAIL"
    assert payload["exit_code"] == 2