"""Pure stock-screening rules shared by dashboard and legacy presentation."""

from collections.abc import Collection, Mapping
from typing import Any

import pandas as pd

from stockfinder.infrastructure.config import configured_rule_profile


def screen_ranked_stocks(
    candidates: pd.DataFrame,
    *,
    region: str | None,
    sector: str | None,
    industry: str | None,
    profile: Mapping[str, Any],
    broker_symbols: Collection[str] = (),
    broker_only: bool = False,
    ranking: str = "Setup score",
) -> pd.DataFrame:
    """Filter and rank candidates using context, a rule profile, and tradability."""
    if candidates.empty:
        return candidates.copy()
    frame = candidates.copy()
    mask = pd.Series(True, index=frame.index)
    for column, selected in (
        ("Region", region),
        ("Sector", sector),
        ("Industry", industry),
    ):
        if selected:
            mask &= frame[column].astype(str) == selected

    evaluated = evaluate_stock_rules(
        frame.loc[mask],
        profile,
        broker_symbols=broker_symbols,
        broker_only=broker_only,
    )
    return rank_stocks(evaluated[evaluated["Profile result"] == "Pass"], ranking)


def evaluate_stock_rules(
    candidates: pd.DataFrame,
    profile: Mapping[str, Any],
    *,
    broker_symbols: Collection[str] = (),
    broker_only: bool = False,
) -> pd.DataFrame:
    """Annotate candidates with profile and broker pass/fail evidence."""
    if candidates.empty:
        return candidates.copy()
    frame = candidates.copy()
    configured_profile = configured_rule_profile(dict(profile))

    minimum_setup = float(configured_profile.get("minimum_setup_score", 0))
    maximum_volatility = float(
        configured_profile.get("maximum_volatility_pct", 100)
    )
    minimum_safety = float(configured_profile.get("minimum_safety_score", 0))
    maximum_risk = 100 - minimum_safety
    minimum_fundamental = float(
        configured_profile.get("minimum_fundamental_score", 0)
    )
    normalized_broker_symbols = {
        str(symbol).strip().upper() for symbol in broker_symbols
    }
    frame["Broker availability"] = frame["Symbol"].map(
        lambda symbol: (
            "Not verified"
            if not normalized_broker_symbols
            else (
                "Available"
                if str(symbol).upper() in normalized_broker_symbols
                else "Not available"
            )
        )
    )
    weighted = frame.apply(
        lambda row: _weighted_profile_score(row, configured_profile),
        axis=1,
        result_type="expand",
    )
    weighted.columns = ["Weighted score", "Weighted data %"]
    frame[["Weighted score", "Weighted data %"]] = weighted
    frame["Rule failures"] = frame.apply(
        lambda row: "; ".join(
            _stock_rule_failures(
                row,
                minimum_setup=minimum_setup,
                maximum_volatility=maximum_volatility,
                maximum_risk=maximum_risk,
                minimum_fundamental=minimum_fundamental,
                require_above_sma150=bool(
                    configured_profile.get("require_above_sma150", False)
                ),
                weighted_score_enabled=bool(
                    configured_profile["weighted_score_enabled"]
                ),
                minimum_weighted_score=float(
                    configured_profile["minimum_weighted_score"]
                ),
                broker_only=broker_only,
            )
        ),
        axis=1,
    )
    frame["Profile result"] = frame["Rule failures"].map(
        lambda failures: "Pass" if not failures else "Excluded"
    )
    return frame


def _stock_rule_failures(
    row: pd.Series,
    *,
    minimum_setup: float,
    maximum_volatility: float,
    maximum_risk: float,
    minimum_fundamental: float,
    require_above_sma150: bool,
    weighted_score_enabled: bool,
    minimum_weighted_score: float,
    broker_only: bool,
) -> list[str]:
    failures = []
    setup = row.get("Setup score")
    if pd.isna(setup) or float(setup) < minimum_setup:
        failures.append(f"Setup < {minimum_setup:g}")
    volatility = row.get("Volatility %")
    if pd.isna(volatility) or float(volatility) > maximum_volatility:
        failures.append(f"Volatility > {maximum_volatility:g}%")
    risk = row.get("Market risk")
    if pd.notna(risk) and float(risk) > maximum_risk:
        failures.append(f"Safety < {100 - maximum_risk:g}")
    trend = row.get("Price above SMA150")
    if require_above_sma150 and (pd.isna(trend) or not bool(trend)):
        failures.append("Below SMA150")
    quality = row.get("Quality")
    if pd.notna(quality) and float(quality) < minimum_fundamental:
        failures.append(f"Quality < {minimum_fundamental:g}")
    weighted_score = row.get("Weighted score")
    if weighted_score_enabled and (
        pd.isna(weighted_score) or float(weighted_score) < minimum_weighted_score
    ):
        failures.append(f"Weighted score < {minimum_weighted_score:g}")
    if broker_only and row.get("Broker availability") != "Available":
        failures.append("Broker unavailable")
    return failures


def _weighted_profile_score(
    row: pd.Series,
    profile: Mapping[str, Any],
) -> tuple[float, float]:
    risk = row.get("Market risk")
    trend = row.get("Price above SMA150")
    safety_value = 100 - float(risk) if pd.notna(risk) else None
    trend_value = (100.0 if bool(trend) else 0.0) if pd.notna(trend) else None
    components = (
        (row.get("Setup score"), float(profile["setup_weight"])),
        (safety_value, float(profile["safety_weight"])),
        (row.get("Quality"), float(profile["fundamental_weight"])),
        (trend_value, float(profile["trend_weight"])),
    )
    total_weight = sum(weight for _, weight in components)
    available = [
        (float(value), weight)
        for value, weight in components
        if value is not None and pd.notna(value) and weight > 0
    ]
    available_weight = sum(weight for _, weight in available)
    if available_weight <= 0 or total_weight <= 0:
        return float("nan"), 0.0
    score = sum(value * weight for value, weight in available) / available_weight
    return round(score, 1), round(available_weight / total_weight * 100, 1)


def rank_stocks(stocks: pd.DataFrame, ranking: str) -> pd.DataFrame:
    """Order candidate evidence by one supported decision criterion."""
    if stocks.empty:
        return stocks.copy()
    if ranking == "Nearest SMA50":
        return stocks.loc[
            stocks["Distance to SMA50 %"].abs().sort_values().index
        ].copy()
    column, ascending = {
        "Setup score": ("Setup score", False),
        "Longest heartbeat base": ("Base sessions", False),
        "Fastest-rising SMA50": ("SMA50 slope 20D %", False),
        "Strongest volume interest": ("Volume trend ratio", False),
        "Highest safety": ("Market risk", True),
        "Weighted profile score": ("Weighted score", False),
    }[ranking]
    return stocks.sort_values(column, ascending=ascending, na_position="last")