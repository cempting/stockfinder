"""Configured regional benchmark comparison and context selector."""

import pandas as pd
import plotly.express as px
import streamlit as st

from stockfinder.dashboard import WidgetSpec
from stockfinder.dashboard_runtime import DashboardServices
from stockfinder.market_overview import (
    regional_confirmation_snapshot,
    regional_market_snapshot,
)
from stockfinder.navigation import AnalysisContext
from stockfinder.widgets.context_controls import linked_selectbox


def render_regional_markets(
    spec: WidgetSpec,
    context: AnalysisContext,
    services: DashboardServices,
) -> None:
    config = services.get_analysis_config()
    region_symbols = {
        region: str(mapping["benchmark"])
        for region, mapping in config["regional_proxies"].items()
    }
    histories = {
        symbol: services.get_history(symbol, "1y").data
        for symbol in set(region_symbols.values())
    }
    global_symbol = region_symbols.get("Global", "ACWI")
    snapshot = regional_market_snapshot(histories, region_symbols, global_symbol)
    if snapshot.empty:
        st.info("No regional benchmark data is available.")
        return
    _, _, industries, _, warning = services.load_scan(services.load_mode)
    if warning:
        st.caption(warning)
    snapshot = regional_confirmation_snapshot(snapshot, industries)

    chart = snapshot[snapshot["Region"] != "Global"].copy()
    figure = px.bar(
        chart.sort_values("3M %"),
        x="3M %",
        y="Region",
        color="Relative 3M %",
        orientation="h",
        hover_data=[
            "Symbol",
            "1M %",
            "6M %",
            "Trend score",
            "Volatility %",
            "Confirmation",
        ],
        color_continuous_scale=["#b9472f", "#f4e8b8", "#16734a"],
        color_continuous_midpoint=0,
    )
    figure.update_layout(
        height=300,
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
        coloraxis_colorbar_title="vs Global",
    )
    st.plotly_chart(figure, width="stretch", key=f"{spec.widget_id}_chart")

    regions = chart["Region"].astype(str).tolist()
    selected = linked_selectbox(
        "Analyze region",
        regions,
        "region",
        context,
        f"{spec.widget_id}_region",
        spec.follow_context,
    )
    available_regions = _scan_regions(industries)
    if selected not in available_regions:
        st.caption(
            f"{selected} benchmark evidence is available, but the current stock "
            "universe has no matching regional classification."
        )

    row = snapshot[snapshot["Region"] == selected].iloc[0]
    momentum, relative, trend = st.columns(3)
    momentum.metric("3M return", f"{float(row['3M %']):+.1f}%")
    relative.metric("Vs global · 3M", f"{float(row['Relative 3M %']):+.1f}%")
    trend.metric("Trend evidence", f"{float(row['Trend score']) / 10:.1f}/10")
    st.markdown(f"**Participation:** {row['Confirmation']}")
    if pd.notna(row.get("Internal breadth %")):
        st.caption(
            f"{float(row['Internal breadth %']):.0f}% internal breadth · "
            f"{float(row['Internal liquidity']) / 10:.1f}/10 liquidity · "
            f"{float(row['Internal rotation']) / 10:.1f}/10 rotation across "
            f"{int(row['Industry count'])} industries"
        )
    with st.expander("Regional evidence table"):
        columns = [
            "Region",
            "Symbol",
            "3M %",
            "Relative 3M %",
            "Trend score",
            "Confirmation",
            "Internal breadth %",
            "Internal liquidity",
            "Internal rotation",
            "Industry count",
        ]
        st.dataframe(
            snapshot[[column for column in columns if column in snapshot]],
            hide_index=True,
            width="stretch",
        )


def _scan_regions(industries: pd.DataFrame) -> set[str]:
    if industries.empty or "Region" not in industries:
        return set()
    return set(industries["Region"].dropna().astype(str))