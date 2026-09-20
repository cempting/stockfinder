"""Configurable portfolio and watchlist alert center."""

import pandas as pd
import streamlit as st

from stockfinder.infrastructure.config import configured_alert_rules, update_alert_rules
from stockfinder.portfolio import portfolio_alerts, portfolio_exposure_snapshot
from stockfinder.presentation.dashboard import WidgetSpec
from stockfinder.presentation.dashboard_runtime import DashboardServices
from stockfinder.presentation.navigation import AnalysisContext


def render_alert_center(
    spec: WidgetSpec,
    context: AnalysisContext,
    services: DashboardServices,
) -> None:
    config = services.get_analysis_config()
    rules = configured_alert_rules(config)
    _render_rule_editor(spec.widget_id, config, rules, services)

    positions = services.get_positions()
    watchlist = services.get_watchlist()
    risk_profiles = services.get_risk_profiles()
    exposure = portfolio_exposure_snapshot(
        positions,
        risk_profiles,
        pd.DataFrame(),
        1.0,
    )
    alerts = portfolio_alerts(exposure, watchlist, risk_profiles, rules)
    if alerts.empty:
        st.success("No cached-data alerts are active.")
    else:
        critical, warning, review = st.columns(3)
        counts = alerts["Severity"].value_counts()
        critical.metric("Critical", int(counts.get("Critical", 0)))
        warning.metric("Warning", int(counts.get("Warning", 0)))
        review.metric("Review", int(counts.get("Review", 0)))
        for row in alerts.itertuples(index=False):
            message = f"{row.Symbol} · {row.Category} · {row.Message}"
            if row.Severity == "Critical":
                st.error(message)
            elif row.Severity == "Warning":
                st.warning(message)
            else:
                st.info(message)
        selected_symbol = st.selectbox(
            "Inspect alert symbol",
            alerts["Symbol"].drop_duplicates().tolist(),
            key=f"{spec.widget_id}_symbol",
        )
        if st.button(
            "Inspect",
            icon=":material/search:",
            key=f"{spec.widget_id}_inspect",
        ):
            context.select("instrument", selected_symbol)
            st.rerun()
    st.caption(
        "Evaluated from the latest cached broad scan. Symbols without cached "
        "quotes cannot trigger price or safety alerts; no background notifications "
        "are sent."
    )


def _render_rule_editor(
    widget_id: str,
    config: dict,
    rules: dict[str, float],
    services: DashboardServices,
) -> None:
    with st.expander("Alert thresholds"):
        with st.form(f"{widget_id}_rules"):
            concentration, safety, loss, proximity = st.columns(4)
            max_allocation = concentration.number_input(
                "Maximum position %",
                min_value=0.0,
                max_value=100.0,
                value=rules["max_position_allocation_pct"],
            )
            minimum_safety = safety.number_input(
                "Minimum safety",
                min_value=0.0,
                max_value=100.0,
                value=rules["minimum_position_safety"],
            )
            loss_trigger = loss.number_input(
                "Loss trigger %",
                min_value=0.0,
                max_value=100.0,
                value=rules["position_loss_pct"],
            )
            entry_tolerance = proximity.number_input(
                "Entry tolerance %",
                min_value=0.0,
                max_value=100.0,
                value=rules["watchlist_entry_tolerance_pct"],
            )
            if st.form_submit_button("Save thresholds", icon=":material/save:"):
                updated = update_alert_rules(
                    config,
                    {
                        "max_position_allocation_pct": float(max_allocation),
                        "minimum_position_safety": float(minimum_safety),
                        "position_loss_pct": float(loss_trigger),
                        "watchlist_entry_tolerance_pct": float(entry_tolerance),
                    },
                )
                services.save_analysis_config(updated)
                st.rerun()