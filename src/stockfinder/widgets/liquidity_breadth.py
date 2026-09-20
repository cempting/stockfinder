"""Multi-horizon industry liquidity and breadth widget."""

import plotly.express as px
import streamlit as st

from stockfinder.presentation.dashboard import WidgetSpec
from stockfinder.presentation.dashboard_runtime import DashboardServices
from stockfinder.presentation.navigation import AnalysisContext

HORIZONS = ("1W", "1M", "3M", "6M")


def render_liquidity_breadth(
    spec: WidgetSpec,
    context: AnalysisContext,
    services: DashboardServices,
) -> None:
    del spec
    _, _, industries, _, _ = services.load_scan(services.load_mode)
    if industries.empty:
        st.info("No liquidity data is available.")
        return

    frame = industries.copy()
    region = context.get("region")
    sector = context.get("sector")
    if region:
        frame = frame[frame["Region"].astype(str) == region]
    if sector:
        frame = frame[frame["Sector"].astype(str) == sector]
    if frame.empty:
        st.info("No liquidity data matches the current context.")
        return

    metric = st.segmented_control(
        "Heatmap evidence",
        ["Liquidity", "Directional flow"],
        default="Liquidity",
        key="liquidity_breadth_metric",
    ) or "Liquidity"
    prefix = "Liquidity" if metric == "Liquidity" else "Flow"
    columns = [
        f"{prefix} {horizon}" + (" %" if prefix == "Flow" else "")
        for horizon in HORIZONS
    ]
    ranked = frame.sort_values("Liquidity composite", ascending=False).head(18)
    matrix = ranked.set_index("Industry")[columns]
    figure = px.imshow(
        matrix,
        aspect="auto",
        color_continuous_scale=["#b9472f", "#f4e8b8", "#16734a"],
        color_continuous_midpoint=0 if prefix == "Flow" else 50,
        labels={"x": "Horizon", "y": "Industry", "color": metric},
    )
    figure.update_layout(
        height=max(300, 28 * len(matrix)),
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
    )
    st.plotly_chart(figure, width="stretch", key="liquidity_breadth_heatmap")

    liquidity, flow, breadth = st.columns(3)
    liquidity.metric(
        "Mean liquidity", f"{float(frame['Liquidity composite'].mean()) / 10:.1f}/10"
    )
    flow.metric("Mean flow", f"{float(frame['Flow composite %'].mean()):+.1f}%")
    breadth.metric(
        "Above rising SMA150",
        f"{float(frame['Above rising SMA150 %'].mean()):.0f}%",
    )
    st.caption(
        "Directional flow is inferred from price and volume; it is not reported "
        "ETF subscriptions or institutional transaction data."
    )