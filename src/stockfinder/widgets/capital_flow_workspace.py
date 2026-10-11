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
    update_capital_movement,
)
from stockfinder.infrastructure.market_sources import resolve_market_proxy
from stockfinder.market_overview import (
    industry_movement_changes,
    industry_qualification_snapshot,
)
from stockfinder.presentation.charting import add_volume_bars, price_volume_subplots
from stockfinder.presentation.dashboard import WidgetSpec
from stockfinder.presentation.dashboard_runtime import DashboardServices
from stockfinder.presentation.navigation import AnalysisContext
from stockfinder.screening import evaluate_stock_rules, rank_stocks
from stockfinder.thumbnails import price_sma_thumbnail
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
CHART_PERIODS = {
    "1W": "5d",
    "1M": "1mo",
    "3M": "3mo",
    "6M": "6mo",
    "1Y": "1y",
    "2Y": "2y",
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
        chart_range = st.selectbox(
            "Chart range",
            tuple(CHART_PERIODS),
            index=3,
            key=f"{spec.widget_id}_chart_range",
        )
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
            _render_industry_overview(
                filtered_industries,
                selected_industry,
                direction,
                chart_range,
                services,
            )
        elif not evaluated.empty and selected_symbol:
            _render_stock_evidence(
                evaluated,
                selected_symbol,
                chart_range,
                services,
            )


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
        "Flow period",
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


def industry_score_fields(row: pd.Series) -> dict[str, str]:
    """Format the compact score columns shown beside an industry chart."""
    return {
        "Flow": f"{float(row['Movement flow %']):+.1f}%",
        "Liquidity": f"{float(row['Movement liquidity']) / 10:.1f}/10",
        "Trend": f"{float(row['Rotation score']) / 10:.1f}/10",
        "Breadth": f"{float(row['Above rising SMA150 %']):.0f}%",
        "Volume": f"{float(row['Pattern volume ratio']):.1f}x",
    }


def _render_industry_overview(
    industries: pd.DataFrame,
    selected_industry: pd.Series,
    direction: str,
    chart_range: str,
    services: DashboardServices,
) -> None:
    label = "Outflow" if direction == "Outflow" else "Leading"
    st.markdown(f"**{label} industries · {len(industries):,}**")
    st.caption(
        f"{chart_range} price, SMA50, and volume · aggregate member flow evidence · "
        "all matching industries"
    )
    prepared = []
    selected_resolution = resolve_market_proxy(
        str(selected_industry["Region"]),
        str(selected_industry["Sector"]),
        str(selected_industry["Industry"]),
        dedicated_only=True,
    )
    selected_proxy = selected_resolution[0] if selected_resolution else None
    histories = {}
    if st.button(
        "Refresh selected chart",
        icon=":material/refresh:",
        key="flow_refresh_selected_industry",
        disabled=selected_proxy is None,
    ):
        refreshed = services.refresh_history(
            str(selected_proxy),
            CHART_PERIODS[chart_range],
        )
        histories[str(selected_proxy)] = refreshed
        if refreshed.warning:
            st.warning(refreshed.warning)
        else:
            st.success(f"Updated {selected_proxy} and its persistent cache.")
    for _, row in industries.iterrows():
        resolution = resolve_market_proxy(
            str(row["Region"]),
            str(row["Sector"]),
            str(row["Industry"]),
            dedicated_only=True,
        )
        proxy, role = resolution if resolution else (None, None)
        if proxy is not None and proxy not in histories:
            histories[proxy] = services.get_history(proxy, CHART_PERIODS[chart_range])
        prepared.append((row, proxy, role))

    header = st.columns([3.0, 2.3, 1, 1, 1, 1, 1], gap="small")
    for column, title in zip(
        header,
        ("Chart", "Industry", "Flow", "Liquidity", "Trend", "Breadth", "Volume"),
        strict=True,
    ):
        column.caption(title)

    for position, (row, proxy, role) in enumerate(prepared):
        chart, identity, *score_columns = st.columns(
            [3.0, 2.3, 1, 1, 1, 1, 1],
            gap="small",
            vertical_alignment="center",
        )
        if proxy is not None:
            history = histories[proxy]
            chart.image(price_sma_thumbnail(history.data), width="stretch")
        else:
            chart.caption("Dedicated proxy not configured")
        identity.markdown(f"**{row['Industry']}**")
        proxy_label = f"{proxy} ({role})" if proxy else "Proxy review needed"
        identity.caption(f"{row['Sector']} · {proxy_label} · {row['Movement change']}")
        for score_column, (score_name, value) in zip(
            score_columns,
            industry_score_fields(row).items(),
            strict=True,
        ):
            score_column.markdown(f"**{value}**")
            if position == 0:
                score_column.caption(score_name)
        st.divider()

    sources = sorted({result.source for result in histories.values()})
    source_label = ", ".join(sources) if sources else "No proxy histories loaded"
    st.caption(
        "Charts use unique configured industry ETFs or indices only. Flow scores "
        f"use aggregate member price-volume evidence. Sources: {source_label}."
    )


def _render_stock_evidence(
    stocks: pd.DataFrame,
    symbol: str,
    chart_range: str,
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
    if st.button(
        "Refresh selected chart",
        icon=":material/refresh:",
        key="flow_refresh_selected_stock",
    ):
        history = services.refresh_history(symbol, CHART_PERIODS[chart_range])
        if history.warning:
            st.warning(history.warning)
        else:
            st.success(f"Updated {symbol} and its persistent cache.")
    else:
        history = services.get_history(symbol, CHART_PERIODS[chart_range])
    st.plotly_chart(
        _flow_chart(history.data, symbol),
        width="stretch",
        key=f"flow_stock_{symbol}",
    )
    st.caption(
        f"{chart_range} · Source: {history.source} · price and daily volume; "
        "SMA50 and SMA150 appear when enough history is available"
    )
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
    frame = history.copy()
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