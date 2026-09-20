"""Runtime dependencies supplied to dashboard widgets."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pandas as pd

from stockfinder.analysis import AnalysisResult
from stockfinder.data import DataResult

ScanResult = tuple[DataResult, Any, Any, Any, str | None]


@dataclass(frozen=True)
class DashboardServices:
    """Explicit service boundary between widgets and the application shell."""

    get_history: Callable[[str, str], DataResult]
    analyze_security: Callable[[str], AnalysisResult]
    load_scan: Callable[[str], ScanResult]
    get_analysis_config: Callable[[], dict[str, Any]]
    save_analysis_config: Callable[[dict[str, Any]], dict[str, Any]]
    get_broker_symbols: Callable[[], set[str]]
    get_risk_profiles: Callable[[], pd.DataFrame]
    get_candidate_fundamentals: Callable[[tuple[str, ...]], pd.DataFrame]
    get_positions: Callable[[], pd.DataFrame]
    get_watchlist: Callable[[], pd.DataFrame]
    save_position: Callable[[str, float, float, str, str], None]
    delete_position: Callable[[str], None]
    save_watchlist: Callable[
        [str, str, float | None, float | None, float | None], None
    ]
    delete_watchlist: Callable[[str], None]
    get_active_rule_profile: Callable[[], str]
    load_mode: str