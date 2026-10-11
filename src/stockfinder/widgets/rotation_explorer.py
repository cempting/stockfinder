"""Linked regional, sector, and industry rotation widget."""

import pandas as pd
import plotly.express as px
import streamlit as st

from stockfinder.infrastructure.config import (
    CAPITAL_MOVEMENT_PRESETS,
    capital_movement_sessions,
    configured_capital_movement,
    update_capital_movement,
)
from stockfinder.market_overview import (
    industry_confirmation_snapshot,
    industry_movement_changes,
    industry_qualification_snapshot,
    sector_allocation_snapshot,
)
from stockfinder.presentation.dashboard import WidgetSpec
from stockfinder.presentation.dashboard_runtime import DashboardServices
from stockfinder.presentation.navigation import AnalysisContext
from stockfinder.widgets.context_controls import (
    linked_optional_selectbox,
    linked_selectbox,
)


def render_rotation_explorer(
    spec: WidgetSpec,
    context: AnalysisContext,
    services: DashboardServices,
) -> None:
    _capital_movement_control(spec, services)
    _, sectors, industries, _, warning = services.load_scan(
        services.load_mode
    )
    if warning:
        st.caption(warning)
    if industries.empty:
        st.info("No industry rotation data is available.")
        return
    previous_industries, _ = services.get_previous_scan()
    industries = industry_movement_changes(industries, previous_industries)
    industries = industry_qualification_snapshot(industries)

    movement_options = ["All", "Inflow", "Outflow", "Mixed"]
    movement_filter = st.segmented_control(
        "Capital movement",
        movement_options,
        default="All",
        key=f"{spec.widget_id}_movement_state",
    ) or "All"
    movement_filtered = _filter_movement_state(industries, movement_filter)
    state_options = ["All", "Early", "Gaining", "Winning", "Losing", "Mixed"]
    state_filter = st.segmented_control(
        "Established rotation",
        state_options,
        default=str(spec.settings.get("default_state", "All")),
        key=f"{spec.widget_id}_state",
    ) or "All"
    filtered = _filter_rotation_state(movement_filtered, state_filter)
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
    st.markdown("**Changed industries**")
    changed = regional[
        regional["Movement change"].isin(
            ["New", "Newly strengthening", "Strengthening", "Deteriorating"]
        )
    ].copy()
    if changed.empty:
        st.caption("No comparable industry transitions are available yet.")
    else:
        changed["_priority"] = changed["Movement change"].map(
            {
                "Newly strengthening": 0,
                "Strengthening": 1,
                "New": 2,
                "Deteriorating": 3,
            }
        )
        changed = changed.sort_values(
            ["_priority", "Movement liquidity"], ascending=[True, False]
        )
        st.dataframe(
            changed[
                [
                    "Sector",
                    "Industry",
                    "Movement change",
                    "Movement state",
                    "Movement return %",
                    "Movement liquidity",
                    "Movement liquidity change",
                    "Industry qualified",
                    "Industry peer rank",
                ]
            ].head(20),
            hide_index=True,
            width="stretch",
        )
    sector_snapshot = sector_allocation_snapshot(sectors, industries)
    regional_sectors = sector_snapshot[
        sector_snapshot["Region"].astype(str) == region
    ].copy()
    if not regional_sectors.empty and "Members" in regional_sectors:
        st.markdown("**Sector allocation map**")
        movement_flow_column = (
            "Movement flow %"
            if "Movement flow %" in regional_sectors
            else "Flow composite %"
        )
        movement_liquidity_column = (
            "Movement liquidity"
            if "Movement liquidity" in regional_sectors
            else "Liquidity composite"
        )
        sector_figure = px.scatter(
            regional_sectors,
            x="Rotation score",
            y=movement_flow_column,
            size="Members",
            color=movement_liquidity_column,
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
            coloraxis_colorbar_title="Movement",
        )
        st.plotly_chart(
            sector_figure,
            width="stretch",
            key=f"{spec.widget_id}_sector_map",
        )
        st.caption(
            "Bubble size is stock coverage. Flow and color use the active "
            "capital-movement period; rotation score retains multi-horizon evidence."
        )
    sector = linked_optional_selectbox(
        "Sector",
        _ordered_groups(regional, "Sector"),
        "sector",
        context,
        f"{spec.widget_id}_sector",
        spec.follow_context,
        "All sectors",
    )
    selected_sector = regional_sectors[
        regional_sectors["Sector"].astype(str) == sector
    ].head(1) if sector else pd.DataFrame()
    if not selected_sector.empty:
        sector_row = selected_sector.iloc[0]
        st.markdown(
            f"**Sector stance:** {sector_row['Stance']} · "
            f"{float(sector_row['Above rising SMA150 %']):.0f}% breadth · "
            f"{float(sector_row['Flow composite %']):+.1f}% flow"
        )
    sector_industries = industry_confirmation_snapshot(
        regional[
            regional["Sector"].astype(str) == sector
        ] if sector else regional
    )
    industry_order_column = (
        "Movement liquidity"
        if "Movement liquidity" in sector_industries
        else "Rotation score"
    )
    industry = _linked_selectbox(
        "Industry",
        sector_industries.sort_values(industry_order_column, ascending=False)[
            "Industry"
        ].astype(str).tolist(),
        "industry",
        context,
        spec,
    )
    selected_industry = sector_industries[
        sector_industries["Industry"].astype(str) == industry
    ].head(1)
    if (
        sector is None
        and not selected_industry.empty
        and spec.follow_context
    ):
        context.select("sector", str(selected_industry.iloc[0]["Sector"]))
        context.select("industry", industry)

    st.markdown("**Industry confirmation**")
    chart_frame = sector_industries.sort_values(
        industry_order_column, ascending=True
    ).tail(12)
    movement_color_column = (
        "Movement liquidity"
        if "Movement liquidity" in chart_frame
        else "Liquidity composite"
    )
    figure = px.bar(
        chart_frame,
        x=industry_order_column,
        y="Industry",
        color=movement_color_column,
        orientation="h",
        hover_data=[
            "Movement change",
            "Confirmation",
            "Movement return %",
            "Movement volume change %",
            "Movement flow %",
            "Above rising SMA150 %",
            "Members",
        ],
        color_continuous_scale=["#c84b31", "#e7c65c", "#18794e"],
        range_color=[0, 100],
    )
    figure.update_layout(
        height=max(260, 34 * len(chart_frame)),
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
        coloraxis_colorbar_title="Movement",
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
            f"{row['Movement period']} {row['Movement state'].lower()}"
        )
        st.caption(
            f"Peer rank {row['Industry peer rank']} · matches: "
            f"{row['Industry matches']} · failures: {row['Industry failures']} · "
            f"unavailable: {row['Industry unavailable']}"
        )
        movement_return, movement_liquidity, movement_flow, breadth = st.columns(4)
        movement_return.metric(
            f"{row['Movement period']} return",
            f"{float(row['Movement return %']):+.1f}%",
        )
        movement_liquidity.metric(
            "Movement liquidity",
            f"{float(row['Movement liquidity']) / 10:.1f}/10",
        )
        movement_flow.metric(
            "Directional flow", f"{float(row['Movement flow %']):+.1f}%"
        )
        breadth.metric("Breadth", f"{float(row['Above rising SMA150 %']):.0f}%")
    with st.expander("Industry evidence table"):
        columns = [
            "Industry",
            "Movement period",
            "Movement state",
            "Movement change",
            "Movement return %",
            "Movement liquidity",
            "Movement volume change %",
            "Movement flow %",
            "Industry qualified",
            "Industry matches",
            "Industry failures",
            "Industry unavailable",
            "Industry evidence %",
            "Industry peer rank",
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


def _capital_movement_control(
    spec: WidgetSpec, services: DashboardServices
) -> None:
    config = services.get_analysis_config()
    movement = configured_capital_movement(config)
    current_period = str(movement["period"])
    current_sessions = capital_movement_sessions(config)
    period_options = (*CAPITAL_MOVEMENT_PRESETS, "Custom")
    selected = st.segmented_control(
        "Capital-movement period",
        period_options,
        default=current_period,
        key=f"{spec.widget_id}_movement_period",
    ) or current_period
    custom_sessions = int(movement["custom_sessions"])
    if selected == "Custom":
        custom_sessions = int(
            st.number_input(
                "Custom trading sessions",
                min_value=1,
                max_value=252,
                value=custom_sessions,
                key=f"{spec.widget_id}_movement_custom_sessions",
            )
        )
    changed = selected != current_period or (
        selected == "Custom" and custom_sessions != current_sessions
    )
    if changed and st.button(
        "Apply period",
        icon=":material/calendar_view_day:",
        type="primary",
        key=f"{spec.widget_id}_apply_movement_period",
    ):
        updated = update_capital_movement(config, selected, custom_sessions)
        services.save_analysis_config(updated)
        st.rerun()
    st.caption(
        f"Active: {current_period} · {current_sessions} completed trading "
        f"session{'s' if current_sessions != 1 else ''}"
    )


def _filter_movement_state(industries: pd.DataFrame, state: str) -> pd.DataFrame:
    if state == "All" or "Movement state" not in industries:
        return industries.copy()
    return industries[industries["Movement state"] == state].copy()

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