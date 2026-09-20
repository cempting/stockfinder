"""Profile-driven ranked stocks for the selected industry context."""

import pandas as pd
import streamlit as st

from stockfinder.presentation.dashboard import WidgetSpec
from stockfinder.presentation.dashboard_runtime import DashboardServices
from stockfinder.presentation.navigation import AnalysisContext
from stockfinder.screening import (
    evaluate_stock_rules,
    rank_stocks,
    screen_ranked_stocks,
)
from stockfinder.widgets.context_controls import linked_selectbox

RANKING_OPTIONS = (
    "Setup score",
    "Weighted profile score",
    "Highest safety",
    "Nearest SMA50",
    "Longest heartbeat base",
    "Fastest-rising SMA50",
    "Strongest volume interest",
)


def render_ranked_stocks(
    spec: WidgetSpec,
    context: AnalysisContext,
    services: DashboardServices,
) -> None:
    _, _, _, candidates, warning = services.load_scan(services.load_mode)
    if warning:
        st.caption(warning)
    if candidates.empty:
        st.info("No analyzed stocks are available.")
        return

    analysis_config = services.get_analysis_config()
    profile_names = tuple(analysis_config["rule_profiles"])
    active_profile = services.get_active_rule_profile()
    profile_index = (
        profile_names.index(active_profile) if active_profile in profile_names else 0
    )
    profile_name = st.selectbox(
        "Rules",
        profile_names,
        index=profile_index,
        key=f"{spec.widget_id}_profile",
    )
    ranking = st.selectbox(
        "Rank by",
        RANKING_OPTIONS,
        key=f"{spec.widget_id}_ranking",
    )
    broker_symbols = services.get_broker_symbols()
    broker_only = st.toggle(
        "Broker-tradable only",
        value=bool(spec.settings.get("broker_only", False)),
        disabled=not broker_symbols,
        key=f"{spec.widget_id}_broker_only",
        help=(
            "Uses the imported broker symbol list. Disabled until a list has "
            "been imported."
        ),
    )

    contextual = _context_candidates(candidates, context)
    if contextual.empty:
        st.info("Select a region, sector, or industry with available stocks.")
        return
    fundamentals = services.get_candidate_fundamentals(
        tuple(contextual["Symbol"].astype(str))
    )
    if not fundamentals.empty:
        contextual = contextual.merge(fundamentals, on="Symbol", how="left")
    risk_profiles = services.get_risk_profiles()
    if "Market risk" not in contextual and not risk_profiles.empty:
        contextual = contextual.merge(
            risk_profiles[["Symbol", "Market risk", "Risk label", "ATR %"]],
            on="Symbol",
            how="left",
        )

    profile = analysis_config["rule_profiles"][profile_name]
    evaluated = evaluate_stock_rules(
        contextual,
        profile,
        broker_symbols=broker_symbols,
        broker_only=broker_only,
    )
    ranked = screen_ranked_stocks(
        contextual,
        region=context.get("region") if spec.follow_context else None,
        sector=context.get("sector") if spec.follow_context else None,
        industry=context.get("industry") if spec.follow_context else None,
        profile=profile,
        broker_symbols=broker_symbols,
        broker_only=broker_only,
        ranking=ranking,
    )
    if ranked.empty:
        fallback = evaluated
        if broker_only:
            fallback = fallback[fallback["Broker availability"] == "Available"]
        ranked = rank_stocks(fallback, ranking)
        if ranked.empty:
            st.info("No stocks match the selected context and broker filter.")
            return
        st.warning(
            f"No stocks pass the {profile_name} profile. Showing the closest "
            "analyzed candidates for inspection."
        )

    passing_count = int((evaluated["Profile result"] == "Pass").sum())
    st.caption(
        f"{passing_count:,} of {len(contextual):,} analyzed stocks pass the "
        f"{profile_name} profile"
    )
    symbols = ranked["Symbol"].astype(str).tolist()
    linked_selectbox(
        "Inspect candidate",
        symbols,
        "instrument",
        context,
        f"{spec.widget_id}_instrument",
        spec.follow_context,
    )

    display_columns = [
        column
        for column in (
            "Symbol",
            "Company",
            "Profile result",
            "Rule failures",
            "Broker availability",
            "Setup state",
            "Setup score",
            "Weighted score",
            "Weighted data %",
            "Quality",
            "Market risk",
            "Volatility %",
            "Distance to SMA50 %",
        )
        if column in ranked
    ]
    event = st.dataframe(
        ranked[display_columns].head(100),
        hide_index=True,
        width="stretch",
        key=f"{spec.widget_id}_table",
        on_select="rerun",
        selection_mode="single-row",
        column_config={
            "Broker availability": st.column_config.TextColumn("Broker"),
            "Setup score": st.column_config.ProgressColumn(
                min_value=0, max_value=100
            ),
            "Weighted score": st.column_config.ProgressColumn(
                min_value=0, max_value=100
            ),
            "Weighted data %": st.column_config.ProgressColumn(
                "Evidence coverage", min_value=0, max_value=100
            ),
            "Quality": st.column_config.ProgressColumn(min_value=0, max_value=100),
            "Market risk": st.column_config.ProgressColumn(
                "Observed risk", min_value=0, max_value=100
            ),
        },
    )
    rows = list(event.get("selection", {}).get("rows", []))
    if rows and spec.follow_context:
        symbol = str(ranked.iloc[rows[0]]["Symbol"])
        if symbol != context.get("instrument"):
            context.select("instrument", symbol)
            st.rerun()

    rejected = rank_stocks(
        evaluated[evaluated["Profile result"] == "Excluded"], ranking
    )
    with st.expander(f"Excluded candidates ({len(rejected):,})"):
        if rejected.empty:
            st.caption("Every analyzed stock in this context passes the profile.")
        else:
            failure_counts = (
                rejected["Rule failures"].str.split("; ").explode().value_counts()
            )
            st.caption(
                "Failure counts: "
                + " · ".join(
                    f"{reason} ({count:,})"
                    for reason, count in failure_counts.items()
                )
            )
            rejected_columns = [
                column
                for column in (
                    "Symbol",
                    "Company",
                    "Rule failures",
                    "Broker availability",
                    "Setup score",
                    "Weighted score",
                    "Weighted data %",
                    "Quality",
                    "Market risk",
                    "Volatility %",
                )
                if column in rejected
            ]
            st.dataframe(
                rejected[rejected_columns].head(100),
                hide_index=True,
                width="stretch",
            )


def _context_candidates(
    candidates: pd.DataFrame, context: AnalysisContext
) -> pd.DataFrame:
    frame = candidates.copy()
    for column, level in (
        ("Region", "region"),
        ("Sector", "sector"),
        ("Industry", "industry"),
    ):
        selected = context.get(level)
        if selected:
            frame = frame[frame[column].astype(str) == selected]
    return frame