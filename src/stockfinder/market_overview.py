"""Transparent cross-asset and regional market snapshot calculations."""

from collections.abc import Mapping

import numpy as np
import pandas as pd

PERIODS = {"1M %": 21, "3M %": 63, "6M %": 126}
RISK_THRESHOLDS = {
    "Equity drawdown": -10.0,
    "Realized volatility": 25.0,
    "VIX level": 25.0,
    "Credit underperformance": -2.0,
    "Dollar surge": 3.0,
}


def market_snapshot(
    histories: Mapping[str, pd.DataFrame],
    labels: Mapping[str, str],
) -> pd.DataFrame:
    """Summarize momentum, long-term trend, and volatility by instrument."""
    rows = []
    for symbol, label in labels.items():
        history = histories.get(symbol)
        if history is None or history.empty or "Close" not in history:
            continue
        close = history["Close"].dropna()
        if len(close) < 2:
            continue
        sma150 = close.rolling(150).mean()
        above_sma150 = bool(
            len(close) >= 150
            and pd.notna(sma150.iloc[-1])
            and close.iloc[-1] > sma150.iloc[-1]
        )
        rising_sma150 = bool(
            len(close) >= 170
            and pd.notna(sma150.iloc[-20])
            and sma150.iloc[-1] > sma150.iloc[-20]
        )
        returns = {
            name: _period_return(close, sessions)
            for name, sessions in PERIODS.items()
        }
        volatility = float(close.pct_change().dropna().std() * np.sqrt(252) * 100)
        positive_checks = sum(
            value is not None and value > 0 for value in returns.values()
        )
        score = 20 * positive_checks + 20 * above_sma150 + 20 * rising_sma150
        rows.append(
            {
                "Symbol": symbol,
                "Market": label,
                "Last": float(close.iloc[-1]),
                **returns,
                "Above SMA150": above_sma150,
                "Rising SMA150": rising_sma150,
                "Volatility %": round(volatility, 1),
                "Trend score": float(score),
            }
        )
    return pd.DataFrame(rows)


def regional_market_snapshot(
    histories: Mapping[str, pd.DataFrame],
    region_symbols: Mapping[str, str],
    global_symbol: str = "ACWI",
) -> pd.DataFrame:
    """Compare configured regional benchmarks with a global benchmark."""
    labels = {symbol: region for region, symbol in region_symbols.items()}
    snapshot = market_snapshot(histories, labels)
    if snapshot.empty:
        return snapshot
    snapshot = snapshot.rename(columns={"Market": "Region"})
    global_row = snapshot[snapshot["Symbol"] == global_symbol]
    global_return = (
        float(global_row.iloc[0]["3M %"]) if not global_row.empty else None
    )
    snapshot["Relative 3M %"] = (
        snapshot["3M %"] - global_return
        if global_return is not None
        else float("nan")
    )
    return snapshot.sort_values(
        ["Trend score", "Relative 3M %"], ascending=False, na_position="last"
    ).reset_index(drop=True)


def regional_confirmation_snapshot(
    benchmarks: pd.DataFrame,
    industries: pd.DataFrame,
) -> pd.DataFrame:
    """Combine regional benchmark leadership with internal participation evidence."""
    if benchmarks.empty:
        return benchmarks.copy()
    required = {
        "Region",
        "Above rising SMA150 %",
        "Liquidity composite",
        "Rotation score",
    }
    result = benchmarks.copy()
    if industries.empty or not required.issubset(industries.columns):
        result["Confirmation"] = "Benchmark only"
        return result

    internals = (
        industries.assign(Region=industries["Region"].astype(str))
        .groupby("Region", as_index=False)
        .agg(
            **{
                "Industry count": ("Region", "size"),
                "Internal breadth %": ("Above rising SMA150 %", "mean"),
                "Internal liquidity": ("Liquidity composite", "mean"),
                "Internal rotation": ("Rotation score", "mean"),
            }
        )
    )
    result = result.merge(internals, on="Region", how="left")
    result["Confirmation"] = result.apply(_regional_confirmation, axis=1)
    return result


def sector_allocation_snapshot(
    sectors: pd.DataFrame,
    industries: pd.DataFrame,
) -> pd.DataFrame:
    """Add participation and a transparent evidence stance to sector aggregates."""
    if sectors.empty:
        return sectors.copy()
    result = sectors.copy()
    participation_columns = {"Members", "Above rising SMA150 %"}
    industry_columns = {
        "Region",
        "Sector",
        "Members",
        "Above rising SMA150 %",
    }
    if not participation_columns.issubset(result) and industry_columns.issubset(
        industries
    ):
        participation = industries.assign(
            _breadth_members=(
                industries["Above rising SMA150 %"] * industries["Members"]
            )
        )
        participation = participation.groupby(
            ["Region", "Sector"], as_index=False
        ).agg(
            Members=("Members", "sum"),
            _breadth_members=("_breadth_members", "sum"),
        )
        participation["Above rising SMA150 %"] = (
            participation.pop("_breadth_members") / participation["Members"]
        ).round(1)
        result = result.merge(participation, on=["Region", "Sector"], how="left")
    if not participation_columns.issubset(result):
        result["Stance"] = "Insufficient internals"
        return result

    result["Winner %"] = (
        result["Winners"] / result["Industries"].replace(0, np.nan) * 100
    ).round(1)
    result["Stance"] = result.apply(_sector_stance, axis=1)
    return result


def industry_confirmation_snapshot(industries: pd.DataFrame) -> pd.DataFrame:
    """Classify industry rotation using breadth, liquidity, flow, and coverage."""
    if industries.empty:
        return industries.copy()
    required = {
        "Rotation score",
        "Liquidity composite",
        "Flow composite %",
        "Above rising SMA150 %",
        "Members",
    }
    result = industries.copy()
    if not required.issubset(result):
        result["Confirmation"] = "Insufficient internals"
        return result
    result["Confirmation"] = result.apply(_industry_confirmation, axis=1)
    return result


def _industry_confirmation(row: pd.Series) -> str:
    rotation = float(row["Rotation score"])
    liquidity = float(row["Liquidity composite"])
    breadth = float(row["Above rising SMA150 %"])
    flow = float(row["Flow composite %"])
    members = int(row["Members"])
    if (
        rotation >= 65
        and liquidity >= 60
        and breadth >= 60
        and flow > 0
        and members >= 3
    ):
        return "Broad leadership"
    if rotation >= 65 and (liquidity < 50 or breadth < 50 or members < 3):
        return "Thin leadership"
    if rotation >= 55 and breadth >= 50 and flow > 0:
        return "Accumulating"
    if rotation < 40 and breadth < 40 and flow < 0:
        return "Weak"
    return "Mixed"


def _sector_stance(row: pd.Series) -> str:
    rotation = float(row["Rotation score"])
    breadth = float(row["Above rising SMA150 %"])
    flow = float(row["Flow composite %"])
    if rotation >= 65 and breadth >= 60 and flow > 0:
        return "Leadership"
    if rotation >= 65 and breadth < 50:
        return "Narrow strength"
    if rotation >= 55 and breadth >= 50 and flow > 0:
        return "Accumulating"
    if rotation < 40 and breadth < 40 and flow < 0:
        return "Weak"
    return "Mixed"


def _regional_confirmation(row: pd.Series) -> str:
    breadth = row.get("Internal breadth %")
    if pd.isna(breadth):
        return "Benchmark only"
    trend = float(row["Trend score"])
    relative = float(row["Relative 3M %"])
    breadth = float(breadth)
    if trend >= 80 and relative > 0 and breadth >= 60:
        return "Confirmed leader"
    if trend >= 80 and relative > 0:
        return "Narrow leader"
    if trend < 40 and relative < 0 and breadth < 40:
        return "Broad weakness"
    if breadth >= 60 and float(row["Internal rotation"]) >= 60:
        return "Internal recovery"
    return "Mixed"


def downside_risk_snapshot(
    histories: Mapping[str, pd.DataFrame],
) -> pd.DataFrame:
    """Report observable downside-stress triggers without collapsing the evidence."""
    closes = {
        symbol: history["Close"].dropna()
        for symbol, history in histories.items()
        if history is not None and not history.empty and "Close" in history
    }
    observations: list[dict[str, object]] = []

    spy = closes.get("SPY")
    if spy is not None and len(spy) >= 21:
        drawdown = float((spy.iloc[-1] / spy.tail(252).max() - 1) * 100)
        realized_volatility = float(
            spy.pct_change().tail(20).std() * np.sqrt(252) * 100
        )
        observations.extend(
            [
                _risk_observation(
                    "Equity drawdown",
                    drawdown,
                    RISK_THRESHOLDS["Equity drawdown"],
                    "at or below",
                    drawdown <= RISK_THRESHOLDS["Equity drawdown"],
                ),
                _risk_observation(
                    "Realized volatility",
                    realized_volatility,
                    RISK_THRESHOLDS["Realized volatility"],
                    "at or above",
                    realized_volatility >= RISK_THRESHOLDS["Realized volatility"],
                ),
            ]
        )

    vix = closes.get("^VIX")
    if vix is not None and not vix.empty:
        level = float(vix.iloc[-1])
        observations.append(
            _risk_observation(
                "VIX level",
                level,
                RISK_THRESHOLDS["VIX level"],
                "at or above",
                level >= RISK_THRESHOLDS["VIX level"],
            )
        )

    hyg = closes.get("HYG")
    ief = closes.get("IEF")
    if hyg is not None and ief is not None and len(hyg) > 21 and len(ief) > 21:
        relative_credit = _period_return(hyg, 21) - _period_return(ief, 21)
        observations.append(
            _risk_observation(
                "Credit underperformance",
                relative_credit,
                RISK_THRESHOLDS["Credit underperformance"],
                "at or below",
                relative_credit <= RISK_THRESHOLDS["Credit underperformance"],
            )
        )

    dollar = closes.get("UUP")
    if dollar is not None and len(dollar) > 21:
        dollar_return = _period_return(dollar, 21)
        observations.append(
            _risk_observation(
                "Dollar surge",
                dollar_return,
                RISK_THRESHOLDS["Dollar surge"],
                "at or above",
                dollar_return >= RISK_THRESHOLDS["Dollar surge"],
            )
        )
    return pd.DataFrame(observations)


def downside_control_response(active_count: int) -> tuple[str, str]:
    """Map the visible trigger count to a non-discretionary control response."""
    if active_count <= 0:
        return "Normal", "Use the configured regime controls."
    if active_count == 1:
        return "Monitor", "Avoid increasing gross exposure until the trigger clears."
    if active_count <= 3:
        return "Cautious", "Pause new exposure and tighten review of existing stops."
    return "Defensive", "Use the defensive control band until stress recedes."


def _risk_observation(
    metric: str,
    value: float,
    threshold: float,
    direction: str,
    active: bool,
) -> dict[str, object]:
    return {
        "Metric": metric,
        "Current": round(value, 1),
        "Trigger": f"{direction} {threshold:+.1f}",
        "Active": bool(active),
    }


def _period_return(close: pd.Series, sessions: int) -> float | None:
    if len(close) <= sessions:
        return None
    return round(float((close.iloc[-1] / close.iloc[-sessions - 1] - 1) * 100), 1)