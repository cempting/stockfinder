"""Read-only operational health checks for persistent Stockfinder state."""

import argparse
import json
import sqlite3
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from stockfinder.config import validate_analysis_config
from stockfinder.runtime import application_data_dir
from stockfinder.storage import ScanSnapshotStore


@dataclass(frozen=True)
class HealthCheck:
    """One operational check with a scheduler-friendly severity."""

    name: str
    status: str
    detail: str


def evaluate_health(
    data_dir: str | Path,
    *,
    now: datetime | None = None,
    max_scan_age_hours: float = 96.0,
    minimum_coverage_pct: float = 90.0,
) -> tuple[HealthCheck, ...]:
    """Evaluate persistent application state without mutating it or fetching data."""
    path = Path(data_dir)
    current_time = now or datetime.now(UTC)
    checks = [
        _configuration_check(path / "analysis_config.json"),
        _database_check(path / "stockfinder.db"),
    ]
    snapshot = ScanSnapshotStore(path / "latest_scan").load()
    if snapshot is None:
        checks.append(HealthCheck("Market scan", "FAIL", "No readable snapshot"))
        return tuple(checks)

    completed_at = snapshot.completed_at
    if completed_at.tzinfo is None:
        completed_at = completed_at.replace(tzinfo=UTC)
    age_delta = current_time.astimezone(UTC) - completed_at.astimezone(UTC)
    age_hours = age_delta.total_seconds() / 3600
    if age_hours > max_scan_age_hours:
        age_status = "FAIL"
    elif age_hours > max_scan_age_hours / 2:
        age_status = "WARN"
    else:
        age_status = "OK"
    checks.append(
        HealthCheck(
            "Scan freshness",
            age_status,
            f"{age_hours:.1f}h old; limit {max_scan_age_hours:.1f}h",
        )
    )

    coverage = float(snapshot.coverage)
    coverage_status = "OK" if coverage >= minimum_coverage_pct else "FAIL"
    checks.append(
        HealthCheck(
            "History coverage",
            coverage_status,
            f"{coverage:.1f}%; minimum {minimum_coverage_pct:.1f}%",
        )
    )
    required_frames = {
        "universe": snapshot.universe,
        "sectors": snapshot.sectors,
        "industries": snapshot.industries,
    }
    empty = [name for name, frame in required_frames.items() if frame.empty]
    checks.append(
        HealthCheck(
            "Snapshot tables",
            "FAIL" if empty else "OK",
            "Empty: " + ", ".join(empty) if empty else "Required tables readable",
        )
    )
    checks.append(
        HealthCheck(
            "Risk profiles",
            "WARN" if snapshot.risk_profiles.empty else "OK",
            (
                "No cached risk profiles"
                if snapshot.risk_profiles.empty
                else f"{len(snapshot.risk_profiles):,} profiles"
            ),
        )
    )
    checks.append(
        HealthCheck(
            "Model version",
            "WARN" if not snapshot.model_version else "OK",
            snapshot.model_version or "Missing model version",
        )
    )
    if snapshot.warning:
        checks.append(HealthCheck("Snapshot warning", "WARN", snapshot.warning))
    return tuple(checks)


def health_exit_code(checks: tuple[HealthCheck, ...]) -> int:
    """Map checks to 0 healthy, 1 warning, or 2 failure."""
    statuses = {check.status for check in checks}
    if "FAIL" in statuses:
        return 2
    return 1 if "WARN" in statuses else 0


def _configuration_check(path: Path) -> HealthCheck:
    if not path.exists():
        return HealthCheck("Configuration", "OK", "Using packaged defaults")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        validate_analysis_config(payload)
        return HealthCheck("Configuration", "OK", "Validated")
    except (OSError, json.JSONDecodeError, TypeError, ValueError) as error:
        return HealthCheck("Configuration", "FAIL", str(error))


def _database_check(path: Path) -> HealthCheck:
    if not path.exists():
        return HealthCheck("Research database", "WARN", "Not created yet")
    try:
        uri = f"file:{path.resolve()}?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            result = connection.execute("PRAGMA quick_check").fetchone()
        detail = str(result[0]) if result else "No integrity result"
        return HealthCheck(
            "Research database",
            "OK" if detail == "ok" else "FAIL",
            detail,
        )
    except sqlite3.Error as error:
        return HealthCheck("Research database", "FAIL", str(error))


def main(argv: list[str] | None = None) -> int:
    """Print operational health and return a severity-based exit code."""
    parser = argparse.ArgumentParser(description="Check Stockfinder persisted state.")
    parser.add_argument("--json", action="store_true", help="Emit JSON output")
    parser.add_argument("--max-scan-age-hours", type=float, default=96.0)
    parser.add_argument("--minimum-coverage-pct", type=float, default=90.0)
    arguments = parser.parse_args(argv)
    checks = evaluate_health(
        application_data_dir(),
        max_scan_age_hours=arguments.max_scan_age_hours,
        minimum_coverage_pct=arguments.minimum_coverage_pct,
    )
    exit_code = health_exit_code(checks)
    if arguments.json:
        print(
            json.dumps(
                {
                    "status": ("FAIL", "WARN", "OK")[2 - exit_code],
                    "exit_code": exit_code,
                    "checks": [asdict(check) for check in checks],
                },
                indent=2,
            )
        )
    else:
        for check in checks:
            print(f"{check.status:<4} {check.name}: {check.detail}")
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())