"""Portfolio valuation and concentration calculations."""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class PortfolioExposure:
    """Valuation, risk, and allocation evidence for recorded positions."""

    positions: pd.DataFrame
    sectors: pd.DataFrame
    regions: pd.DataFrame
    total_market_value: float
    total_pnl: float
    gross_exposure_pct: float
    largest_position_pct: float
    weighted_safety: float
    missing_quotes: int
    missing_fx: int
    base_currency: str


ALERT_COLUMNS = ("Severity", "Category", "Symbol", "Message")


def portfolio_alerts(
    exposure: PortfolioExposure,
    watchlist: pd.DataFrame,
    risk_profiles: pd.DataFrame,
    rules: dict[str, float],
) -> pd.DataFrame:
    """Evaluate portfolio and watchlist alerts from cached market evidence."""
    alerts: list[dict[str, Any]] = []
    _position_alerts(alerts, exposure.positions, rules)
    _watchlist_alerts(alerts, watchlist, risk_profiles, rules)
    if not alerts:
        return pd.DataFrame(columns=ALERT_COLUMNS)
    severity_order = {"Critical": 0, "Warning": 1, "Review": 2}
    result = pd.DataFrame(alerts)
    result["_order"] = result["Severity"].map(severity_order)
    return (
        result.sort_values(["_order", "Category", "Symbol"])
        .drop(columns="_order")
        .reset_index(drop=True)
    )


def portfolio_exposure_snapshot(
    positions: pd.DataFrame,
    risk_profiles: pd.DataFrame,
    universe: pd.DataFrame,
    account_value: float,
    fx_rates: Mapping[str, float] | None = None,
    base_currency: str = "USD",
) -> PortfolioExposure:
    """Enrich stored positions with cached quotes and classification evidence."""
    if positions.empty:
        return PortfolioExposure(
            positions=pd.DataFrame(),
            sectors=pd.DataFrame(),
            regions=pd.DataFrame(),
            total_market_value=0.0,
            total_pnl=0.0,
            gross_exposure_pct=0.0,
            largest_position_pct=0.0,
            weighted_safety=float("nan"),
            missing_quotes=0,
            missing_fx=0,
            base_currency=base_currency.upper(),
        )

    detail = positions.copy()
    detail["symbol"] = detail["symbol"].astype(str).str.upper()
    if "currency" not in detail:
        detail["currency"] = base_currency
    detail["currency"] = (
        detail["currency"].fillna(base_currency).astype(str).str.upper()
    )
    profiles = _risk_profile_columns(risk_profiles)
    classifications = _classification_columns(universe)
    detail = detail.merge(profiles, on="symbol", how="left")
    detail = detail.merge(classifications, on="symbol", how="left")
    detail["quantity"] = pd.to_numeric(detail["quantity"], errors="coerce")
    detail["entry_price"] = pd.to_numeric(detail["entry_price"], errors="coerce")
    detail["last_price"] = pd.to_numeric(detail["last_price"], errors="coerce")
    detail["local_cost"] = detail["quantity"] * detail["entry_price"]
    detail["local_market_value"] = detail["quantity"] * detail["last_price"]
    normalized_rates = {
        str(currency).upper(): float(rate)
        for currency, rate in (fx_rates or {}).items()
    }
    normalized_rates[base_currency.upper()] = 1.0
    detail["fx_rate"] = detail["currency"].map(normalized_rates)
    detail["cost"] = detail["local_cost"] * detail["fx_rate"]
    detail["market_value"] = detail["local_market_value"] * detail["fx_rate"]
    detail["pnl"] = detail["market_value"] - detail["cost"]
    detail.attrs["base_currency"] = base_currency.upper()

    quoted = detail[detail["market_value"].notna()]
    total_market_value = float(quoted["market_value"].sum())
    detail["allocation_%"] = np.where(
        total_market_value > 0,
        detail["market_value"] / total_market_value * 100,
        np.nan,
    )
    safety = 100 - pd.to_numeric(detail["market_risk"], errors="coerce")
    weighted = detail["market_value"].where(safety.notna())
    weighted_safety = (
        float((safety * weighted).sum() / weighted.sum())
        if weighted.notna().any() and float(weighted.sum()) > 0
        else float("nan")
    )
    gross_exposure = (
        total_market_value / account_value * 100 if account_value > 0 else float("nan")
    )
    largest_position = (
        float(detail["allocation_%"].max()) if total_market_value > 0 else 0.0
    )
    return PortfolioExposure(
        positions=detail,
        sectors=_allocation_frame(detail, "Sector", total_market_value),
        regions=_allocation_frame(detail, "Region", total_market_value),
        total_market_value=total_market_value,
        total_pnl=float(quoted["pnl"].sum()),
        gross_exposure_pct=float(gross_exposure),
        largest_position_pct=largest_position,
        weighted_safety=weighted_safety,
        missing_quotes=int(detail["last_price"].isna().sum()),
        missing_fx=int(
            (detail["last_price"].notna() & detail["fx_rate"].isna()).sum()
        ),
        base_currency=base_currency.upper(),
    )


def fx_conversion_symbols(source_currency: str, base_currency: str) -> tuple[str, str]:
    """Return Yahoo Finance direct and inverse FX symbols."""
    source = source_currency.upper()
    base = base_currency.upper()
    return f"{source}{base}=X", f"{base}{source}=X"


def latest_conversion_rate(
    source_currency: str,
    base_currency: str,
    direct_history: pd.DataFrame,
    inverse_history: pd.DataFrame,
) -> tuple[float | None, str | None]:
    """Resolve a positive direct or inverse close into base currency units."""
    source = source_currency.upper()
    base = base_currency.upper()
    if source == base:
        return 1.0, "same currency"
    direct_symbol, inverse_symbol = fx_conversion_symbols(source, base)
    direct = _latest_positive_close(direct_history)
    if direct is not None:
        return direct, direct_symbol
    inverse = _latest_positive_close(inverse_history)
    if inverse is not None:
        return 1 / inverse, inverse_symbol
    return None, None


def _latest_positive_close(history: pd.DataFrame) -> float | None:
    if history.empty or "Close" not in history:
        return None
    close = pd.to_numeric(history["Close"], errors="coerce").dropna()
    if close.empty or float(close.iloc[-1]) <= 0:
        return None
    return float(close.iloc[-1])


def _risk_profile_columns(frame: pd.DataFrame) -> pd.DataFrame:
    columns = {
        "Symbol": "symbol",
        "Last price": "last_price",
        "Market risk": "market_risk",
        "Risk label": "risk_label",
        "ATR %": "atr_%",
    }
    available = [column for column in columns if column in frame]
    if "Symbol" not in available:
        return pd.DataFrame(
            columns=["symbol", "last_price", "market_risk", "risk_label", "atr_%"]
        )
    result = frame[available].rename(columns=columns)
    return result.drop_duplicates("symbol", keep="last")


def _position_alerts(
    alerts: list[dict[str, Any]],
    positions: pd.DataFrame,
    rules: dict[str, float],
) -> None:
    for _, row in positions.iterrows():
        symbol = str(row["symbol"])
        allocation = _number(row.get("allocation_%"))
        if allocation is not None and allocation > rules["max_position_allocation_pct"]:
            _add_alert(
                alerts,
                "Warning",
                "Concentration",
                symbol,
                f"Allocation {allocation:.1f}% exceeds "
                f"{rules['max_position_allocation_pct']:.1f}%.",
            )
        market_risk = _number(row.get("market_risk"))
        if market_risk is not None:
            safety = 100 - market_risk
            if safety < rules["minimum_position_safety"]:
                _add_alert(
                    alerts,
                    "Warning",
                    "Safety",
                    symbol,
                    f"Safety {safety:.1f} is below "
                    f"{rules['minimum_position_safety']:.1f}.",
                )
        entry = _number(row.get("entry_price"))
        last = _number(row.get("last_price"))
        if entry and last is not None:
            loss = (last / entry - 1) * 100
            if loss <= -rules["position_loss_pct"]:
                _add_alert(
                    alerts,
                    "Critical",
                    "Position loss",
                    symbol,
                    f"Return {loss:.1f}% breached -{rules['position_loss_pct']:.1f}%.",
                )


def _watchlist_alerts(
    alerts: list[dict[str, Any]],
    watchlist: pd.DataFrame,
    risk_profiles: pd.DataFrame,
    rules: dict[str, float],
) -> None:
    if watchlist.empty or "symbol" not in watchlist:
        return
    candidates = watchlist.copy()
    candidates["symbol"] = candidates["symbol"].astype(str).str.upper()
    candidates = candidates.merge(
        _risk_profile_columns(risk_profiles)[["symbol", "last_price"]],
        on="symbol",
        how="left",
    )
    for _, row in candidates.iterrows():
        symbol = str(row["symbol"])
        last = _number(row.get("last_price"))
        entry = _number(row.get("entry_price"))
        target = _number(row.get("target_price"))
        stop = _number(row.get("stop_price"))
        if last is None:
            continue
        if stop is not None and last <= stop:
            _add_alert(
                alerts,
                "Critical",
                "Watchlist stop",
                symbol,
                f"Last {last:.2f} is at or below stop {stop:.2f}.",
            )
        if target is not None and last >= target:
            _add_alert(
                alerts,
                "Review",
                "Watchlist target",
                symbol,
                f"Last {last:.2f} reached target {target:.2f}.",
            )
        if entry and abs(last / entry - 1) * 100 <= rules[
            "watchlist_entry_tolerance_pct"
        ]:
            _add_alert(
                alerts,
                "Review",
                "Entry proximity",
                symbol,
                f"Last {last:.2f} is near planned entry {entry:.2f}.",
            )


def _number(value: Any) -> float | None:
    return float(value) if pd.notna(value) else None


def _add_alert(
    alerts: list[dict[str, Any]],
    severity: str,
    category: str,
    symbol: str,
    message: str,
) -> None:
    alerts.append(
        {
            "Severity": severity,
            "Category": category,
            "Symbol": symbol,
            "Message": message,
        }
    )


def _classification_columns(frame: pd.DataFrame) -> pd.DataFrame:
    available = [
        column
        for column in ("Symbol", "Region", "Sector", "Industry")
        if column in frame
    ]
    if "Symbol" not in available:
        return pd.DataFrame(columns=["symbol", "Region", "Sector", "Industry"])
    result = frame[available].rename(columns={"Symbol": "symbol"})
    return result.drop_duplicates("symbol", keep="last")


def _allocation_frame(
    positions: pd.DataFrame,
    dimension: str,
    total_market_value: float,
) -> pd.DataFrame:
    if total_market_value <= 0:
        return pd.DataFrame(columns=[dimension, "Market value", "Allocation %"])
    grouped = (
        positions.assign(**{dimension: positions[dimension].fillna("Unclassified")})
        .groupby(dimension, as_index=False)["market_value"]
        .sum()
        .rename(columns={"market_value": "Market value"})
    )
    grouped["Allocation %"] = grouped["Market value"] / total_market_value * 100
    return grouped.sort_values("Market value", ascending=False).reset_index(drop=True)