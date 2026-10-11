"""Scan-friendly security fundamentals, forward evidence, and risk scoreboard."""

from datetime import UTC, datetime
from typing import Any

import pandas as pd
import streamlit as st

from stockfinder.presentation.dashboard import WidgetSpec
from stockfinder.presentation.dashboard_runtime import DashboardServices
from stockfinder.presentation.navigation import AnalysisContext


def security_scoreboard_frame(
    profile: dict[str, Any],
    history: pd.DataFrame,
    *,
    latest_price: float,
    atr: float,
) -> pd.DataFrame:
    """Return reported and calculated evidence without filling missing values."""
    close = history.get("Close", pd.Series(dtype=float)).dropna()
    volume = history.get("Volume", pd.Series(dtype=float)).dropna()
    volatility = (
        float(close.pct_change().dropna().std() * (252**0.5) * 100)
        if len(close) > 1
        else None
    )
    drawdown = (
        float((close / close.cummax() - 1).min() * 100) if not close.empty else None
    )
    dollar_volume = (
        float((close * volume.reindex(close.index)).tail(20).mean())
        if not close.empty and not volume.empty
        else None
    )
    earnings_timestamp = profile.get("earningsTimestampStart")
    earnings_date = (
        datetime.fromtimestamp(float(earnings_timestamp), UTC).date().isoformat()
        if isinstance(earnings_timestamp, (int, float))
        else None
    )
    rows = [
        ("Growth", "Revenue growth", profile.get("revenueGrowth"), "Reported"),
        ("Growth", "Earnings growth", profile.get("earningsGrowth"), "Reported"),
        ("Quality", "Gross margin", profile.get("grossMargins"), "Reported"),
        ("Quality", "Operating margin", profile.get("operatingMargins"), "Reported"),
        ("Quality", "Profit margin", profile.get("profitMargins"), "Reported"),
        ("Quality", "Return on equity", profile.get("returnOnEquity"), "Reported"),
        ("Quality", "Return on assets", profile.get("returnOnAssets"), "Reported"),
        (
            "Cash flow",
            "Operating cash flow",
            profile.get("operatingCashflow"),
            "Reported",
        ),
        ("Cash flow", "Free cash flow", profile.get("freeCashflow"), "Reported"),
        ("Balance sheet", "Debt to equity", profile.get("debtToEquity"), "Reported"),
        ("Balance sheet", "Current ratio", profile.get("currentRatio"), "Reported"),
        ("Valuation", "Trailing P/E", profile.get("trailingPE"), "Reported"),
        ("Valuation", "Forward P/E", profile.get("forwardPE"), "Estimate"),
        ("Valuation", "Price to book", profile.get("priceToBook"), "Reported"),
        (
            "Forward / event",
            "Analyst mean target",
            profile.get("targetMeanPrice"),
            "Opinion",
        ),
        (
            "Forward / event",
            "Recommendation",
            profile.get("recommendationKey"),
            "Opinion",
        ),
        ("Forward / event", "Next earnings", earnings_date, "Reported event"),
        ("Market risk", "Realized volatility %", volatility, "Calculated"),
        ("Market risk", "Maximum drawdown %", drawdown, "Calculated"),
        (
            "Market risk",
            "ATR %",
            atr / latest_price * 100 if latest_price else None,
            "Calculated",
        ),
        (
            "Trading liquidity",
            "20-session average dollar volume",
            dollar_volume,
            "Calculated",
        ),
        ("Jurisdiction", "Country", profile.get("country"), "Reported"),
        ("Jurisdiction", "Currency", profile.get("currency"), "Reported"),
        ("Jurisdiction", "Exchange", profile.get("exchange"), "Reported"),
    ]
    return pd.DataFrame(
        [
            {
                "Category": category,
                "Measure": measure,
                "Value": value,
                "Evidence type": evidence_type,
                "Status": "Available" if _available(value) else "Unavailable",
            }
            for category, measure, value, evidence_type in rows
        ]
    )


def render_security_scoreboard(
    spec: WidgetSpec,
    context: AnalysisContext,
    services: DashboardServices,
) -> None:
    symbol = (
        context.get("instrument") if spec.follow_context else None
    ) or str(spec.settings.get("default_symbol", "SPY"))
    result = services.analyze_security(symbol)
    frame = security_scoreboard_frame(
        result.profile.data,
        result.history.data,
        latest_price=result.latest_price,
        atr=result.atr,
    )
    available = int((frame["Status"] == "Available").sum())
    st.caption(
        f"{symbol} · {available}/{len(frame)} measures available · missing "
        "evidence is not scored as neutral"
    )
    display = frame.copy()
    display["Value"] = display["Value"].map(_display_value)
    st.dataframe(
        display,
        hide_index=True,
        width="stretch",
        column_config={"Value": st.column_config.TextColumn(width="medium")},
    )
    st.caption(
        f"Profile source: {result.profile.source} · market source: "
        f"{result.history.source} · estimates and analyst targets are opinions"
    )


def _available(value: object) -> bool:
    if value is None or value == "":
        return False
    try:
        return not bool(pd.isna(value))
    except (TypeError, ValueError):
        return True


def _display_value(value: object) -> str:
    if not _available(value):
        return "Unavailable"
    if isinstance(value, float):
        return f"{value:,.2f}"
    return str(value)