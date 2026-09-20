"""Linked regional, sector, and industry rotation widget."""

import pandas as pd
import plotly.express as px
import streamlit as st

from stockfinder.dashboard import WidgetSpec
from stockfinder.dashboard_runtime import DashboardServices
from stockfinder.market_overview import (
    industry_confirmation_snapshot,
    sector_allocation_snapshot,
)
from stockfinder.navigation import AnalysisContext
from stockfinder.widgets.context_controls import linked_selectbox


def render_rotation_explorer(
    spec: WidgetSpec,
    context: AnalysisContext,
    services: DashboardServices,
) -> None:
    _, sectors, industries, _, warning = services.load_scan(
        services.load_mode
    )
    if warning:
        st.caption(warning)
    if industries.empty:
        st.info("No industry rotation data is available.")
        return

    state_options = ["All", "Early", "Gaining", "Winning", "Losing", "Mixed"]
    state_filter = st.segmented_control(
        "Rotation state",
        state_options,
        default=str(spec.settings.get("default_state", "Gaining")),
        key=f"{spec.widget_id}_state",
    ) or "All"
    filtered = _filter_rotation_state(industries, state_filter)
    if filtered.empty:
        st.info("No industries match this rotation state.")
        return

    region = _linked_selectbox(
        "Region",
        _ordered_groups(filtered, "Region"),
        "region",
        context,
        spec,
    )
    regional = filtered[filtered["Region"].astype(str) == region]
    sector_snapshot = sector_allocation_snapshot(sectors, industries)
    regional_sectors = sector_snapshot[
        sector_snapshot["Region"].astype(str) == region
    ].copy()
    if not regional_sectors.empty and "Members" in regional_sectors:
        st.markdown("**Sector allocation map**")
        sector_figure = px.scatter(
            regional_sectors,
            x="Rotation score",
            y="Flow composite %",
            size="Members",
            color="Above rising SMA150 %",
            text="Sector",
            hover_data=[
                "Stance",
                "Liquidity composite",
                "Winner %",
                "Industries",
                "Members",
            ],
            color_continuous_scale=["#b9472f", "#f4e8b8", "#16734a"],
            range_color=[0, 100],
        )
        sector_figure.add_hline(y=0, line_dash="dot", line_color="#6b6b63")
        sector_figure.update_traces(textposition="top center")
        sector_figure.update_xaxes(range=[0, 100])
        sector_figure.update_layout(
            height=340,
            margin={"l": 0, "r": 0, "t": 10, "b": 0},
            coloraxis_colorbar_title="Breadth",
        )
        st.plotly_chart(
            sector_figure,
            width="stretch",
            key=f"{spec.widget_id}_sector_map",
        )
        st.caption(
            "Bubble size is stock coverage. The map uses all regional sectors; "
            "the rotation-state control filters the industry drill-down."
        )
    sector = _linked_selectbox(
        "Sector",
        _ordered_groups(regional, "Sector"),
        "sector",
        context,
        spec,
    )
    selected_sector = regional_sectors[
        regional_sectors["Sector"].astype(str) == sector
    ].head(1)
    if not selected_sector.empty:
        sector_row = selected_sector.iloc[0]
        st.markdown(
            f"**Sector stance:** {sector_row['Stance']} · "
            f"{float(sector_row['Above rising SMA150 %']):.0f}% breadth · "
            f"{float(sector_row['Flow composite %']):+.1f}% flow"
        )
    sector_industries = industry_confirmation_snapshot(
        regional[regional["Sector"].astype(str) == sector]
    )
    industry = _linked_selectbox(
        "Industry",
        sector_industries.sort_values("Rotation score", ascending=False)[
            "Industry"
        ].astype(str).tolist(),
        "industry",
        context,
        spec,
    )

    st.markdown("**Industry confirmation**")
    chart_frame = sector_industries.sort_values(
        "Rotation score", ascending=True
    ).tail(12)
    figure = px.bar(
        chart_frame,
        x="Rotation score",
        y="Industry",
        color="Liquidity composite",
        orientation="h",
        hover_data=[
            "Confirmation",
            "Flow composite %",
            "Above rising SMA150 %",
            "Members",
        ],
        color_continuous_scale=["#c84b31", "#e7c65c", "#18794e"],
        range_color=[0, 100],
    )
    figure.update_layout(
        height=max(260, 34 * len(chart_frame)),
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
        coloraxis_colorbar_title="Liquidity",
    )
    st.plotly_chart(figure, width="stretch", key=f"{spec.widget_id}_chart")

    selected = sector_industries[
        sector_industries["Industry"].astype(str) == industry
    ].head(1)
    if not selected.empty:
        row = selected.iloc[0]
        st.markdown(
            f"**Industry stance:** {row['Confirmation']} · "
            f"{int(row['Members'])} stocks · "
            f"{float(row['Flow composite %']):+.1f}% flow"
        )
        score, liquidity, breadth = st.columns(3)
        score.metric("Rotation", f"{float(row['Rotation score']) / 10:.1f}/10")
        liquidity.metric(
            "Liquidity", f"{float(row['Liquidity composite']) / 10:.1f}/10"
        )
        breadth.metric("Breadth", f"{float(row['Above rising SMA150 %']):.0f}%")
    with st.expander("Industry evidence table"):
        columns = [
            "Industry",
            "Confirmation",
            "Rotation state",
            "Rotation score",
            "Liquidity composite",
            "Flow composite %",
            "Above rising SMA150 %",
            "Members",
        ]
        st.dataframe(
            sector_industries[
                [column for column in columns if column in sector_industries]
            ],
            hide_index=True,
            width="stretch",
        )

def _filter_rotation_state(industries: pd.DataFrame, state: str) -> pd.DataFrame:
    if state == "All":
        return industries.copy()
    if state == "Early":
        return industries[
            industries["Early rotation signal"].isin(["Emerging", "Building"])
        ].copy()
    if state == "Winning":
        return industries[industries["Winning"]].copy()
    return industries[industries["Rotation state"] == state].copy()


def _ordered_groups(frame: pd.DataFrame, column: str) -> list[str]:
    """Order context choices by their strongest available rotation evidence."""
    return (
        frame.assign(**{column: frame[column].astype(str)})
        .groupby(column)["Rotation score"]
        .max()
        .sort_values(ascending=False)
        .index.tolist()
    )


def _linked_selectbox(
    label: str,
    options: list[str],
    level: str,
    context: AnalysisContext,
    spec: WidgetSpec,
) -> str:
    return linked_selectbox(
        label,
        options,
        level,
        context,
        f"{spec.widget_id}_{level}",
        spec.follow_context,
    )