"""SQLite persistence for user-owned research data."""

import json
import shutil
import sqlite3
from contextlib import closing
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from tempfile import mkdtemp
from uuid import uuid4

import pandas as pd

from stockfinder.runtime import application_data_dir


class MarketHistoryCache:
    """Persist last-known-good daily OHLCV histories by symbol."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = (
            Path(path) if path is not None else application_data_dir() / "market"
        )
        self.path.mkdir(parents=True, exist_ok=True)

    def _path_for(self, symbol: str) -> Path:
        safe_symbol = symbol.upper().replace("/", "_").replace("^", "INDEX_")
        return self.path / f"{safe_symbol}.parquet"

    def load(self, symbol: str) -> pd.DataFrame | None:
        path = self._path_for(symbol)
        if not path.exists():
            return None
        try:
            frame = pd.read_parquet(path)
            if frame.empty or "Close" not in frame:
                return None
            return frame.sort_index()
        except (OSError, ValueError):
            return None

    def save(self, symbol: str, history: pd.DataFrame) -> None:
        if history.empty:
            return
        path = self._path_for(symbol)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            history.sort_index().to_parquet(temporary)
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def merge(self, symbol: str, history: pd.DataFrame) -> pd.DataFrame:
        cached = self.load(symbol)
        frames = [frame for frame in (cached, history) if frame is not None]
        merged = pd.concat(frames).sort_index()
        merged = merged[~merged.index.duplicated(keep="last")]
        self.save(symbol, merged)
        return merged

    def is_fresh(self, symbol: str, max_age_hours: float) -> bool:
        path = self._path_for(symbol)
        if not path.exists():
            return False
        age_seconds = datetime.now(UTC).timestamp() - path.stat().st_mtime
        return age_seconds <= max_age_hours * 60 * 60


class CompanyProfileCache:
    """Persist last-known-good provider profiles as atomic JSON files."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = (
            Path(path)
            if path is not None
            else application_data_dir() / "profiles"
        )
        self.path.mkdir(parents=True, exist_ok=True)

    def _path_for(self, symbol: str) -> Path:
        safe_symbol = symbol.upper().replace("/", "_").replace("^", "INDEX_")
        return self.path / f"{safe_symbol}.json"

    def load(self, symbol: str) -> dict | None:
        path = self._path_for(symbol)
        if not path.exists():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) and payload else None
        except (OSError, json.JSONDecodeError):
            return None

    def save(self, symbol: str, profile: dict) -> None:
        if not profile:
            return
        path = self._path_for(symbol)
        temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(json.dumps(profile, default=str), encoding="utf-8")
            temporary.replace(path)
        finally:
            if temporary.exists():
                temporary.unlink()

    def is_fresh(self, symbol: str, max_age_hours: float) -> bool:
        path = self._path_for(symbol)
        if not path.exists():
            return False
        age_seconds = datetime.now(UTC).timestamp() - path.stat().st_mtime
        return age_seconds <= max_age_hours * 60 * 60


@dataclass(frozen=True)
class ScanSnapshot:
    """The last complete broad-market scan and its provenance."""

    universe: pd.DataFrame
    sectors: pd.DataFrame
    industries: pd.DataFrame
    candidates: pd.DataFrame
    completed_at: datetime
    source: str
    coverage: float
    mode: str
    model_version: str
    warning: str | None = None
    risk_profiles: pd.DataFrame = field(default_factory=pd.DataFrame)


class ScanSnapshotStore:
    """Atomically persist the latest successful market scan."""

    def __init__(self, path: str | Path = "data/latest_scan") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def save(self, snapshot: ScanSnapshot) -> None:
        temporary = Path(mkdtemp(prefix="scan-", dir=self.path.parent))
        try:
            for name in (
                "universe",
                "sectors",
                "industries",
                "candidates",
                "risk_profiles",
            ):
                getattr(snapshot, name).to_parquet(temporary / f"{name}.parquet")
            (temporary / "metadata.json").write_text(
                json.dumps(
                    {
                        "completed_at": snapshot.completed_at.astimezone(
                            UTC
                        ).isoformat(),
                        "source": snapshot.source,
                        "coverage": snapshot.coverage,
                        "mode": snapshot.mode,
                        "model_version": snapshot.model_version,
                        "warning": snapshot.warning,
                    }
                ),
                encoding="utf-8",
            )
            backup = self.path.with_name(f"{self.path.name}.previous")
            if backup.exists():
                shutil.rmtree(backup)
            if self.path.exists():
                self.path.replace(backup)
            temporary.replace(self.path)
            if backup.exists():
                shutil.rmtree(backup)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def load(self) -> ScanSnapshot | None:
        metadata_path = self.path / "metadata.json"
        if not metadata_path.exists():
            return None
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            risk_path = self.path / "risk_profiles.parquet"
            return ScanSnapshot(
                universe=pd.read_parquet(self.path / "universe.parquet"),
                sectors=pd.read_parquet(self.path / "sectors.parquet"),
                industries=pd.read_parquet(self.path / "industries.parquet"),
                candidates=pd.read_parquet(self.path / "candidates.parquet"),
                completed_at=datetime.fromisoformat(metadata["completed_at"]),
                source=metadata["source"],
                coverage=float(metadata["coverage"]),
                mode=metadata["mode"],
                model_version=metadata.get("model_version", ""),
                warning=metadata.get("warning"),
                risk_profiles=(
                    pd.read_parquet(risk_path) if risk_path.exists() else pd.DataFrame()
                ),
            )
        except (OSError, ValueError, KeyError, json.JSONDecodeError):
            return None


class Repository:
    """Persist watchlist and portfolio records in a local SQLite database."""

    def __init__(self, path: str | Path = "data/stockfinder.db") -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        return connection

    def _initialize(self) -> None:
        with closing(self._connect()) as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS watchlist (
                    symbol TEXT PRIMARY KEY,
                    notes TEXT NOT NULL DEFAULT '',
                    entry_price REAL,
                    target_price REAL,
                    stop_price REAL,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS positions (
                    symbol TEXT PRIMARY KEY,
                    quantity REAL NOT NULL CHECK (quantity > 0),
                    entry_price REAL NOT NULL CHECK (entry_price > 0),
                    entry_date TEXT,
                    updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            connection.commit()

    def save_watchlist(
        self,
        symbol: str,
        notes: str = "",
        entry_price: float | None = None,
        target_price: float | None = None,
        stop_price: float | None = None,
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO watchlist
                    (symbol, notes, entry_price, target_price, stop_price)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    notes = excluded.notes,
                    entry_price = excluded.entry_price,
                    target_price = excluded.target_price,
                    stop_price = excluded.stop_price,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (symbol.upper(), notes, entry_price, target_price, stop_price),
            )
            connection.commit()

    def delete_watchlist(self, symbol: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM watchlist WHERE symbol = ?", (symbol,))
            connection.commit()

    def watchlist(self) -> pd.DataFrame:
        with closing(self._connect()) as connection:
            return pd.read_sql_query(
                "SELECT * FROM watchlist ORDER BY updated_at DESC", connection
            )

    def save_position(
        self, symbol: str, quantity: float, entry_price: float, entry_date: str
    ) -> None:
        with closing(self._connect()) as connection:
            connection.execute(
                """
                INSERT INTO positions (symbol, quantity, entry_price, entry_date)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    quantity = excluded.quantity,
                    entry_price = excluded.entry_price,
                    entry_date = excluded.entry_date,
                    updated_at = CURRENT_TIMESTAMP
                """,
                (symbol.upper(), quantity, entry_price, entry_date),
            )
            connection.commit()

    def delete_position(self, symbol: str) -> None:
        with closing(self._connect()) as connection:
            connection.execute("DELETE FROM positions WHERE symbol = ?", (symbol,))
            connection.commit()

    def positions(self) -> pd.DataFrame:
        with closing(self._connect()) as connection:
            return pd.read_sql_query(
                "SELECT * FROM positions ORDER BY updated_at DESC", connection
            )
