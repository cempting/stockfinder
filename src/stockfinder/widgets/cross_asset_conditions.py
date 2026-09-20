"""Broad cross-asset market conditions widget."""

import plotly.express as px
import streamlit as st

from stockfinder.dashboard import WidgetSpec
from stockfinder.dashboard_runtime import DashboardServices
from stockfinder.market_overview import market_snapshot
from stockfinder.navigation import AnalysisContext

DEFAULT_ASSETS = {
    "SPY": "US large-cap equities",
    "IWM": "US small-cap equities",
    "HYG": "High-yield credit",
    "IEF": "Intermediate Treasuries",
    "TLT": "Long-duration Treasuries",
    "UUP": "US dollar",
    "GLD": "Gold",
    "DBC": "Broad commodities",
    "^VIX": "Equity volatility",
}


def render_cross_asset_conditions(
    spec: WidgetSpec,
    context: AnalysisContext,
    services: DashboardServices,
) -> None:
    del context
    labels = dict(spec.settings.get("assets", DEFAULT_ASSETS))
    histories = {
        symbol: services.get_history(symbol, "1y").data for symbol in labels
    }
    snapshot = market_snapshot(histories, labels)
    if snapshot.empty:
        st.info("No cross-asset data is available.")
        return

    heatmap = snapshot.set_index("Market")[["1M %", "3M %", "6M %"]]
    figure = px.imshow(
        heatmap,
        aspect="auto",
        color_continuous_scale=["#b9472f", "#f4e8b8", "#16734a"],
        color_continuous_midpoint=0,
        labels={"x": "Horizon", "y": "Asset", "color": "Return %"},
    )
    figure.update_layout(
        height=350,
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
    )
    st.plotly_chart(figure, width="stretch", key=f"{spec.widget_id}_heatmap")

    indexed = snapshot.set_index("Symbol")
    credit = _relative_return(indexed, "HYG", "IEF")
    small_caps = _relative_return(indexed, "IWM", "SPY")
    vix = indexed.loc["^VIX", "1M %"] if "^VIX" in indexed.index else None
    credit_column, breadth_column, volatility_column = st.columns(3)
    credit_column.metric(
        "Credit vs Treasuries · 3M",
        _percent(credit),
        "Supportive" if credit is not None and credit > 0 else "Defensive",
    )
    breadth_column.metric(
        "Small caps vs SPY · 3M",
        _percent(small_caps),
        "Broadening" if small_caps is not None and small_caps > 0 else "Narrow",
    )
    volatility_column.metric(
        "VIX · 1M",
        _percent(vix),
        "Falling" if vix is not None and vix < 0 else "Rising",
        delta_color="inverse",
    )
    st.caption(
        "Rates, credit, currency, commodity, and volatility proxies provide market "
        "context. Macro releases, central-bank events, news, and sentiment still "
        "require dedicated providers."
    )


def _relative_return(snapshot, first: str, second: str) -> float | None:
    if first not in snapshot.index or second not in snapshot.index:
        return None
    first_return = snapshot.loc[first, "3M %"]
    second_return = snapshot.loc[second, "3M %"]
    if first_return is None or second_return is None:
        return None
    return float(first_return - second_return)


def _percent(value: object) -> str:
    return "Unavailable" if value is None else f"{float(value):+.1f}%"