"""Reusable broad-market scan orchestration for UI and scheduled jobs."""

import argparse
import fcntl
import json
import os
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from typing import IO

import pandas as pd

from stockfinder.analysis import (
    breakout_candidates,
    broad_rotation_scan,
    build_market_risk_profiles,
    classify_rotation_state,
)
from stockfinder.data import DataResult, get_batch_histories, get_global_universe
from stockfinder.infrastructure.config import AnalysisConfigStore, geography_column
from stockfinder.infrastructure.runtime import application_data_dir
from stockfinder.infrastructure.storage import ScanSnapshot, ScanSnapshotStore

MARKET_SCAN_VERSION = "2026-09-promising-evidence-v12"
ProgressCallback = Callable[[str, int, int, int], None]


class RefreshAlreadyRunningError(RuntimeError):
    """Raised when a scheduled refresh already owns the process lock."""


@contextmanager
def refresh_process_lock(path: str | Path) -> Iterator[None]:
    """Hold a nonblocking advisory lock for one scheduled refresh process."""
    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    handle: IO[str] = lock_path.open("a+", encoding="utf-8")
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RefreshAlreadyRunningError(
                f"Another market refresh owns {lock_path}"
            ) from error
        handle.seek(0)
        handle.truncate()
        handle.write(
            json.dumps(
                {
                    "pid": os.getpid(),
                    "started_at": datetime.now(UTC).isoformat(),
                }
            )
        )
        handle.flush()
        yield
    finally:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def refresh_market_scan(
    config: dict,
    load_mode: str,
    store: ScanSnapshotStore,
    *,
    as_of: date | None = None,
    universe_loader: Callable[[date | None], DataResult] = get_global_universe,
    history_loader: Callable[[tuple[str, ...], str], DataResult] = (
        get_batch_histories
    ),
    progress: ProgressCallback | None = None,
) -> ScanSnapshot:
    """Fetch, calculate, and atomically persist one complete market scan."""
    if load_mode not in {"standard", "extended"}:
        raise ValueError("load_mode must be standard or extended")
    period = "2y" if load_mode == "extended" else "1y"
    chunk_size = 100 if load_mode == "extended" else 200
    _notify(progress, "Loading market universe", 0, 0, 0)
    universe_result = apply_geography_dimension(universe_loader(as_of), config)
    symbols = tuple(universe_result.data["Symbol"].astype(str))
    histories: dict[str, pd.DataFrame] = {}
    provider_warnings = []
    for offset in range(0, len(symbols), chunk_size):
        chunk = symbols[offset : offset + chunk_size]
        result = history_loader(chunk, period)
        histories.update(result.data)
        if result.warning:
            provider_warnings.append(result.warning)
        _notify(
            progress,
            "Loading price history",
            min(offset + len(chunk), len(symbols)),
            len(symbols),
            len(histories),
        )

    _notify(progress, "Aggregating sectors and industries", 0, 0, len(histories))
    sectors, industries = broad_rotation_scan(universe_result.data, histories)
    industries = ensure_rotation_columns(industries)
    industry_groups = set(
        industries[["Region", "Sector", "Industry"]].itertuples(
            index=False, name=None
        )
    )
    _notify(progress, "Building stock candidates", 0, 0, len(histories))
    candidates = breakout_candidates(
        universe_result.data, histories, industry_groups
    )
    _notify(progress, "Building risk profiles", 0, 0, len(histories))
    risk_profiles = build_market_risk_profiles(histories)
    coverage = len(histories) / max(1, len(symbols)) * 100
    provider_note = " · Some provider batches had gaps" if provider_warnings else ""
    warning = (
        f"History coverage: {len(histories):,}/{len(symbols):,} "
        f"({coverage:.1f}%){provider_note}"
    )
    snapshot = ScanSnapshot(
        universe=universe_result.data,
        sectors=sectors,
        industries=industries,
        candidates=candidates,
        completed_at=datetime.now(UTC),
        source=universe_result.source,
        coverage=coverage,
        mode=load_mode,
        model_version=market_scan_model_version(config),
        warning=warning,
        risk_profiles=risk_profiles,
    )
    store.save(snapshot)
    _notify(progress, "Complete", len(symbols), len(symbols), len(histories))
    return snapshot


def market_scan_model_version(config: dict) -> str:
    """Return the scan version including its configured geography dimension."""
    return f"{MARKET_SCAN_VERSION}-{config['geography_dimension']}"


def apply_geography_dimension(
    universe_result: DataResult, config: dict
) -> DataResult:
    """Apply listing-region or company-domicile grouping to a universe result."""
    frame = universe_result.data.copy()
    frame["Listing region"] = frame["Region"]
    if geography_column(config) == "Country":
        frame["Region"] = frame["Country"].replace({"": "Unknown"}).fillna(
            "Unknown"
        )
    return DataResult(
        frame,
        universe_result.source,
        universe_result.retrieved_at,
        universe_result.is_fallback,
        universe_result.warning,
    )


def ensure_rotation_columns(industries: pd.DataFrame) -> pd.DataFrame:
    """Backfill rotation fields for snapshots produced by earlier models."""
    required = {
        "Momentum change",
        "Liquidity change",
        "Recent flow %",
        "Rotation state",
    }
    if industries.empty:
        return industries
    frame = industries.copy()

    def normalized(column: str, low: float, high: float) -> pd.Series:
        return (100 * (frame[column] - low) / (high - low)).clip(0, 100)

    if not required.issubset(frame.columns):
        frame["Momentum change"] = (
            (
                normalized("Return 1W %", -5, 8)
                + normalized("Return 1M %", -10, 15)
            )
            / 2
            - (
                normalized("Return 3M %", -20, 30)
                + normalized("Return 6M %", -30, 50)
            )
            / 2
        ).round(1)
        frame["Liquidity change"] = (
            (frame["Liquidity 1W"] + frame["Liquidity 1M"]) / 2
            - (frame["Liquidity 3M"] + frame["Liquidity 6M"]) / 2
        ).round(1)
        frame["Recent flow %"] = (
            (frame["Flow 1W %"] + frame["Flow 1M %"]) / 2
        ).round(1)
        frame["Rotation state"] = frame.apply(
            lambda row: classify_rotation_state(
                float(row["Momentum change"]),
                float(row["Liquidity change"]),
                float(row["Recent flow %"]),
            ),
            axis=1,
        )
    defaults: dict[str, object] = {
        "Early rotation score": 0.0,
        "Early rotation signal": "Unavailable",
        "Breadth acceleration": 0.0,
        "RS inflection": 0.0,
        "Positive dollar volume": 0.0,
        "Close pressure": 0.0,
    }
    for column, default in defaults.items():
        if column not in frame:
            frame[column] = default
    return frame


def _notify(
    callback: ProgressCallback | None,
    stage: str,
    completed: int,
    total: int,
    usable: int,
) -> None:
    if callback is not None:
        callback(stage, completed, total, usable)


def main(
    argv: list[str] | None = None,
    *,
    refresh: Callable[..., ScanSnapshot] = refresh_market_scan,
) -> int:
    """Refresh and persist a broad-market scan for external schedulers."""
    parser = argparse.ArgumentParser(
        description="Refresh the Stockfinder broad-market snapshot."
    )
    parser.add_argument(
        "--mode",
        choices=("standard", "extended"),
        default="standard",
    )
    parser.add_argument(
        "--minimum-coverage-pct",
        type=float,
        default=90.0,
        help="Return warning exit code 1 when coverage is below this value.",
    )
    arguments = parser.parse_args(argv)
    if not 0 <= arguments.minimum_coverage_pct <= 100:
        parser.error("--minimum-coverage-pct must be between 0 and 100")
    data_dir = application_data_dir()

    def report(stage: str, completed: int, total: int, usable: int) -> None:
        if total:
            print(f"{stage}: {completed:,}/{total:,} · {usable:,} usable")
        else:
            print(stage)

    try:
        with refresh_process_lock(data_dir / ".market-refresh.lock"):
            snapshot = refresh(
                AnalysisConfigStore(data_dir / "analysis_config.json").load(),
                arguments.mode,
                ScanSnapshotStore(data_dir / "latest_scan"),
                as_of=date.today(),
                progress=report,
            )
    except RefreshAlreadyRunningError as error:
        print(f"Market refresh skipped: {error}")
        return 3
    except Exception as error:
        print(f"Market refresh failed: {error}")
        return 2
    print(
        f"Market refresh complete: {len(snapshot.universe):,} listings, "
        f"{len(snapshot.industries):,} industries, "
        f"{snapshot.coverage:.1f}% coverage"
    )
    if snapshot.coverage < arguments.minimum_coverage_pct:
        print(
            f"Coverage below minimum {arguments.minimum_coverage_pct:.1f}%"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())