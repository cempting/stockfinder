"""Focused split-view workflow for industry flows and constituent stocks."""

from collections.abc import Mapping
from typing import Any

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from stockfinder.infrastructure.config import (
    CAPITAL_MOVEMENT_PRESETS,
    capital_movement_sessions,
    configured_capital_movement,
    configured_proxy,
    update_capital_movement,
)
from stockfinder.market_overview import (
    industry_movement_changes,
    industry_qualification_snapshot,
)
from stockfinder.presentation.charting import add_volume_bars, price_volume_subplots
from stockfinder.presentation.dashboard import WidgetSpec
from stockfinder.presentation.dashboard_runtime import DashboardServices
from stockfinder.presentation.navigation import AnalysisContext
from stockfinder.screening import evaluate_stock_rules, rank_stocks
from stockfinder.widgets.context_controls import (
    linked_optional_selectbox,
    linked_selectbox,
)

PATTERNS = (
    "Consolidation",
    "Breakout",
    "Near SMA50",
    "Above SMA50",
    "Above SMA150",
    "Positive volume spike",
)
INDUSTRY_PATTERN_COLUMNS = {
    "Consolidation": "Pattern consolidation",
    "Breakout": "Pattern breakout",
    "Near SMA50": "Pattern near SMA50",
    "Above SMA50": "Pattern above SMA50",
    "Above SMA150": "Pattern above SMA150",
    "Positive volume spike": "Pattern volume spike",
}
STOCK_PATTERN_COLUMNS = {
    "Consolidation": "Consolidation base",
    "Near SMA50": "Near SMA50",
    "Above SMA50": "Price above SMA50",
    "Above SMA150": "Price above SMA150",
    "Positive volume spike": "Volume Evidence",
}


def filter_flow_evidence(
    frame: pd.DataFrame,
    *,
    direction: str,
    patterns: tuple[str, ...],
    entity: str,
) -> pd.DataFrame:
    """Apply explicit direction and pattern filters to industry or stock rows."""
    result = frame.copy()
    if direction != "All" and "Movement state" in result:
        result = result[result["Movement state"] == direction]
    mapping = (
        INDUSTRY_PATTERN_COLUMNS if entity == "industry" else STOCK_PATTERN_COLUMNS
    )
    for pattern in patterns:
        if entity == "stock" and pattern == "Breakout":
            if "Setup state" not in result:
                return result.iloc[0:0]
            result = result[
                result["Setup state"].astype(str).str.contains(
                    "breakout", case=False, na=False
                )
            ]
            continue
        column = mapping.get(pattern)
        if column is None or column not in result:
            return result.iloc[0:0]
        result = result[result[column].fillna(False).astype(bool)]
    return result


def order_flow_evidence(frame: pd.DataFrame, direction: str) -> pd.DataFrame:
    """Put strongest inflows first and strongest outflows first when requested."""
    if frame.empty or "Movement liquidity" not in frame:
        return frame.copy()
    return frame.sort_values(
        "Movement liquidity",
        ascending=direction == "Outflow",
        na_position="last",
    )


def render_capital_flow_workspace(
    spec: WidgetSpec,
    context: AnalysisContext,
    services: DashboardServices,
) -> None:
    universe, _, industries, candidates, warning = services.load_scan(
        services.load_mode
    )
    if warning:
        st.caption(warning)
    if industries.empty:
        st.info("No industry flow evidence is available.")
        return

    previous_industries, _ = services.get_previous_scan()
    industries = industry_movement_changes(industries, previous_industries)
    industries = industry_qualification_snapshot(industries)
    controls, evidence = st.columns([3, 9], gap="large")

    with controls:
        st.markdown("**Find**")
        _compact_movement_control(spec, services)
        view = st.segmented_control(
            "View",
            ("Industries", "Stocks"),
            default="Industries",
            key=f"{spec.widget_id}_view",
        ) or "Industries"
        direction = st.segmented_control(
            "Money flow",
            ("Inflow", "Outflow", "All"),
            default="Inflow",
            key=f"{spec.widget_id}_direction",
        ) or "Inflow"
        regions = _ordered_values(industries, "Region")
        region = linked_selectbox(
            "Region",
            regions,
            "region",
            context,
            f"{spec.widget_id}_region",
            spec.follow_context,
        )
        regional = industries[industries["Region"].astype(str) == region]
        sector = linked_optional_selectbox(
            "Sector",
            _ordered_values(regional, "Sector"),
            "sector",
            context,
            f"{spec.widget_id}_sector",
            spec.follow_context,
            "All sectors",
        )
        scoped = (
            regional[regional["Sector"].astype(str) == sector]
            if sector
            else regional
        )
        patterns = tuple(
            st.multiselect(
                "Patterns",
                PATTERNS,
                key=f"{spec.widget_id}_patterns",
                placeholder="Any pattern",
            )
        )
        filtered_industries = order_flow_evidence(
            filter_flow_evidence(
                scoped,
                direction=direction,
                patterns=patterns,
                entity="industry",
            ),
            direction,
        )
        if filtered_industries.empty:
            st.warning("No industries match these filters.")
            return
        industry = linked_selectbox(
            "Industry",
            filtered_industries["Industry"].astype(str).tolist(),
            "industry",
            context,
            f"{spec.widget_id}_industry",
            spec.follow_context,
        )
        selected_industry = filtered_industries[
            filtered_industries["Industry"].astype(str) == industry
        ].iloc[0]

        selected_symbol = None
        evaluated = pd.DataFrame()
        if view == "Stocks":
            st.markdown("**Stock filters**")
            profile_name = st.selectbox(
                "Rule profile",
                tuple(services.get_analysis_config()["rule_profiles"]),
                key=f"{spec.widget_id}_profile",
            )
            evaluated = _evaluated_stocks(
                candidates,
                selected_industry,
                services.get_analysis_config()["rule_profiles"][profile_name],
                services,
            )
            evaluated = order_flow_evidence(
                filter_flow_evidence(
                    evaluated,
                    direction=direction,
                    patterns=patterns,
                    entity="stock",
                ),
                direction,
            )
            if evaluated.empty:
                st.warning("No stocks match these filters.")
            else:
                selected_symbol = linked_selectbox(
                    "Stock",
                    evaluated["Symbol"].astype(str).tolist(),
                    "instrument",
                    context,
                    f"{spec.widget_id}_stock",
                    spec.follow_context,
                )
                st.button(
                    "Open stock workbench",
                    icon=":material/open_in_new:",
                    width="stretch",
                    key=f"{spec.widget_id}_open_workbench",
                    on_click=_open_stock_workbench,
                )

    with evidence:
        if view == "Industries":
            _render_industry_evidence(
                filtered_industries,
                selected_industry,
                direction,
                services,
            )
        elif not evaluated.empty and selected_symbol:
            _render_stock_evidence(evaluated, selected_symbol, services)


def _evaluated_stocks(
    candidates: pd.DataFrame,
    industry: pd.Series,
    profile: Mapping[str, Any],
    services: DashboardServices,
) -> pd.DataFrame:
    if candidates.empty:
        return candidates.copy()
    mask = (
        (candidates["Region"].astype(str) == str(industry["Region"]))
        & (candidates["Sector"].astype(str) == str(industry["Sector"]))
        & (candidates["Industry"].astype(str) == str(industry["Industry"]))
    )
    contextual = candidates[mask].copy()
    if contextual.empty:
        return contextual
    fundamentals = services.get_candidate_fundamentals(
        tuple(contextual["Symbol"].astype(str))
    )
    if not fundamentals.empty:
        contextual = contextual.merge(fundamentals, on="Symbol", how="left")
    risk = services.get_risk_profiles()
    if "Market risk" not in contextual and not risk.empty:
        contextual = contextual.merge(
            risk[["Symbol", "Market risk", "Risk label", "ATR %"]],
            on="Symbol",
            how="left",
        )
    evaluated = evaluate_stock_rules(
        contextual,
        profile,
        broker_symbols=services.get_broker_symbols(),
    )
    return rank_stocks(evaluated, "Opportunity score")


def _compact_movement_control(
    spec: WidgetSpec, services: DashboardServices
) -> None:
    config = services.get_analysis_config()
    movement = configured_capital_movement(config)
    current_period = str(movement["period"])
    options = (*CAPITAL_MOVEMENT_PRESETS, "Custom")
    selected = st.selectbox(
        "Period",
        options,
        index=options.index(current_period),
        key=f"{spec.widget_id}_movement_period",
    )
    custom_sessions = int(movement["custom_sessions"])
    if selected == "Custom":
        custom_sessions = int(
            st.number_input(
                "Trading sessions",
                min_value=1,
                max_value=252,
                value=custom_sessions,
                key=f"{spec.widget_id}_movement_sessions",
            )
        )
    current_sessions = capital_movement_sessions(config)
    changed = selected != current_period or (
        selected == "Custom" and custom_sessions != current_sessions
    )
    if changed and st.button(
        "Apply period",
        icon=":material/calendar_view_day:",
        width="stretch",
        key=f"{spec.widget_id}_apply_period",
    ):
        services.save_analysis_config(
            update_capital_movement(config, selected, custom_sessions)
        )
        st.rerun()


def _render_industry_evidence(
    industries: pd.DataFrame,
    selected: pd.Series,
    direction: str,
    services: DashboardServices,
) -> None:
    st.markdown(f"### {selected['Industry']}")
    st.caption(
        f"{selected['Region']} · {selected['Sector']} · aggregate member evidence"
    )
    state, liquidity, flow, breadth = st.columns(4)
    state.metric(
        "Money flow",
        str(selected["Movement state"]),
        str(selected["Movement change"]),
    )
    liquidity.metric(
        "Liquidity",
        f"{float(selected['Movement liquidity']) / 10:.1f}/10",
        _delta(selected, "Movement liquidity change"),
    )
    flow.metric(
        "Directional flow",
        f"{float(selected['Movement flow %']):+.1f}%",
        _delta(selected, "Movement flow % change", suffix="%"),
    )
    breadth.metric("Trend breadth", f"{float(selected['Above rising SMA150 %']):.0f}%")

    config = services.get_analysis_config()
    proxy, role = configured_proxy(
        config,
        str(selected["Region"]),
        str(selected["Sector"]),
        str(selected["Industry"]),
    )
    history = services.get_history(proxy, "1y")
    st.plotly_chart(
        _flow_chart(history.data, proxy),
        width="stretch",
        key=f"flow_industry_{proxy}",
    )
    st.caption(
        f"Representative {role}: {proxy} · {history.source}. Industry flow scores "
        "use equal-weight member prices and aggregate dollar volume."
    )
    st.markdown(f"#### {'Outflow' if direction == 'Outflow' else 'Leading'} industries")
    columns = [
        "Industry",
        "Sector",
        "Movement state",
        "Movement change",
        "Movement liquidity",
        "Movement liquidity change",
        "Movement flow %",
        "Above rising SMA150 %",
        "Industry peer rank",
        *INDUSTRY_PATTERN_COLUMNS.values(),
    ]
    st.dataframe(
        industries[[column for column in columns if column in industries]].head(30),
        hide_index=True,
        width="stretch",
    )


def _render_stock_evidence(
    stocks: pd.DataFrame,
    symbol: str,
    services: DashboardServices,
) -> None:
    selected = stocks[stocks["Symbol"].astype(str) == symbol].iloc[0]
    st.markdown(f"### {selected.get('Company', symbol)} · {symbol}")
    setup, opportunity, movement, peer = st.columns(4)
    setup.metric("Setup", str(selected["Setup state"]), str(selected["Profile result"]))
    opportunity.metric(
        "Opportunity",
        f"{float(selected['Opportunity score']) / 10:.1f}/10",
    )
    movement.metric(
        "Money flow",
        str(selected["Movement state"]),
        f"{float(selected['Movement flow %']):+.1f}%",
    )
    peer.metric("Industry rank", str(selected["Stock peer rank"]))
    history = services.get_history(symbol, "1y")
    st.plotly_chart(
        _flow_chart(history.data, symbol),
        width="stretch",
        key=f"flow_stock_{symbol}",
    )
    st.caption(f"Source: {history.source} · price, SMA50, SMA150, and daily volume")
    columns = [
        "Symbol",
        "Company",
        "Profile result",
        "Opportunity score",
        "Stock peer rank",
        "Setup state",
        "Movement state",
        "Movement liquidity",
        "Movement flow %",
        "Consolidation base",
        "Price above SMA50",
        "Price above SMA150",
        "Volume Evidence",
    ]
    st.dataframe(
        stocks[[column for column in columns if column in stocks]].head(50),
        hide_index=True,
        width="stretch",
    )


def _flow_chart(history: pd.DataFrame, symbol: str) -> go.Figure:
    frame = history.tail(252).copy()
    figure = price_volume_subplots()
    if frame.empty or "Close" not in frame:
        figure.update_layout(height=430)
        return figure
    frame["SMA50"] = frame["Close"].rolling(50).mean()
    frame["SMA150"] = frame["Close"].rolling(150).mean()
    figure.add_scatter(x=frame.index, y=frame["Close"], name=symbol, row=1, col=1)
    figure.add_scatter(x=frame.index, y=frame["SMA50"], name="SMA50", row=1, col=1)
    figure.add_scatter(x=frame.index, y=frame["SMA150"], name="SMA150", row=1, col=1)
    add_volume_bars(figure, frame)
    figure.update_layout(
        height=430,
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
        hovermode="x unified",
        legend={"orientation": "h"},
    )
    figure.update_xaxes(rangeslider_visible=False)
    return figure


def _ordered_values(frame: pd.DataFrame, column: str) -> list[str]:
    return (
        frame.assign(**{column: frame[column].astype(str)})
        .groupby(column)["Movement liquidity"]
        .max()
        .sort_values(ascending=False)
        .index.tolist()
    )


def _open_stock_workbench() -> None:
    st.session_state["requested_dashboard"] = "Stock Detail"


def _delta(row: pd.Series, column: str, suffix: str = "") -> str | None:
    value = row.get(column)
    return (
        f"{float(value):+.1f}{suffix}"
        if value is not None and pd.notna(value)
        else None
    )