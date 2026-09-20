"""Generic stock, ETF, and index analysis widget."""

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from stockfinder.presentation.charting import add_volume_bars, price_volume_subplots
from stockfinder.presentation.dashboard import WidgetSpec
from stockfinder.presentation.dashboard_runtime import DashboardServices
from stockfinder.presentation.navigation import AnalysisContext


def render_instrument_analysis(
    spec: WidgetSpec,
    context: AnalysisContext,
    services: DashboardServices,
) -> None:
    configured_symbol = str(spec.settings.get("default_symbol", "SPY"))
    default_symbol = (
        context.get("instrument") if spec.follow_context else None
    ) or configured_symbol
    input_key = f"{spec.widget_id}_symbol"
    linked_context_key = f"{input_key}_linked_context"
    if (
        spec.follow_context
        and context.get("instrument")
        and st.session_state.get(linked_context_key) != default_symbol
    ):
        st.session_state[input_key] = default_symbol
        st.session_state[linked_context_key] = default_symbol
    elif input_key not in st.session_state:
        st.session_state[input_key] = default_symbol
    symbol = st.text_input(
        "Ticker or index symbol",
        key=input_key,
    ).strip().upper()
    if not symbol:
        st.info("Enter a stock, ETF, or index symbol.")
        return
    if spec.follow_context and symbol != context.get("instrument"):
        context.select("instrument", symbol)

    with st.spinner(f"Analyzing {symbol}..."):
        result = services.analyze_security(symbol)
    profile = result.profile.data
    st.markdown(f"**{profile.get('longName', symbol)} · {symbol}**")
    price, quality, safety, technical = st.columns(4)
    price.metric("Price", f"{result.latest_price:,.2f}", f"{result.daily_change:+.2f}%")
    quality.metric("Quality", f"{_score(result.analysis.quality.value):.1f}/10")
    safety.metric("Safety", f"{_safety(result.analysis.risk.value):.1f}/10")
    technical.metric("Technical", f"{_score(result.analysis.technical.value):.1f}/10")

    figure = _instrument_figure(result.history.data.tail(252).copy())
    st.plotly_chart(figure, width="stretch", key=f"{spec.widget_id}_price")
    source = result.history.source
    st.caption(f"Source: {source} · quality, risk, and technical scores stay separate")


def _instrument_figure(history: pd.DataFrame) -> go.Figure:
    """Plot price trends and aligned daily trading volume."""
    history["SMA50"] = history["Close"].rolling(50).mean()
    history["SMA150"] = history["Close"].rolling(150).mean()
    figure = price_volume_subplots()
    figure.add_scatter(
        x=history.index, y=history["Close"], name="Price", row=1, col=1
    )
    figure.add_scatter(
        x=history.index, y=history["SMA50"], name="SMA50", row=1, col=1
    )
    figure.add_scatter(
        x=history.index, y=history["SMA150"], name="SMA150", row=1, col=1
    )
    add_volume_bars(figure, history)
    figure.update_layout(
        height=470,
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
        hovermode="x unified",
        legend={"orientation": "h"},
    )
    figure.update_xaxes(rangeslider_visible=False)
    return figure


def _score(value: float) -> float:
    return round(max(1.0, min(10.0, value / 10)), 1)


def _safety(value: float) -> float:
    return round(max(1.0, min(10.0, 10 - value / 10)), 1)