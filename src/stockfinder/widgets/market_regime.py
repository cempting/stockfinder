"""Market risk and configured control-plan widget."""

import streamlit as st

from stockfinder.analysis import classify_market_regime
from stockfinder.market_overview import (
    downside_control_response,
    downside_risk_snapshot,
)
from stockfinder.presentation.dashboard import WidgetSpec
from stockfinder.presentation.dashboard_runtime import DashboardServices
from stockfinder.presentation.navigation import AnalysisContext


def render_market_regime(
    spec: WidgetSpec,
    context: AnalysisContext,
    services: DashboardServices,
) -> None:
    del context
    symbols = tuple(
        spec.settings.get("symbols", ("SPY", "IWM", "HYG", "IEF", "UUP", "^VIX"))
    )
    histories = {
        symbol: services.get_history(symbol, "1y").data for symbol in symbols
    }
    regime = classify_market_regime(histories)
    control_key = {
        "Risk-on": "supportive",
        "Mixed": "neutral",
        "Risk-off": "defensive",
    }.get(regime.label, "defensive")
    control = services.get_analysis_config()["market_controls"][control_key]

    regime_column, exposure_column, risk_column = st.columns(3)
    regime_column.metric("Regime", regime.label, f"{regime.score}/4 signals")
    exposure_column.metric(
        "Maximum exposure", f"{control['max_gross_exposure_pct']:.0f}%"
    )
    risk_column.metric(
        "Risk per position", f"{control['risk_per_position_pct']:.2f}%"
    )
    st.markdown(f"**New-entry policy:** {control['new_entry_policy']}")
    downside = downside_risk_snapshot(histories)
    if not downside.empty:
        active = downside[downside["Active"]]
        response, action = downside_control_response(len(active))
        st.markdown(f"**Stress response:** {response} · {action}")
        if not active.empty:
            st.warning("Active triggers: " + ", ".join(active["Metric"]))
    with st.expander("Evidence"):
        for name, passed in regime.checks.items():
            st.write(f"{'Pass' if passed else 'Defensive'} · {name}")
        if not downside.empty:
            st.markdown("**Downside escalation triggers**")
            evidence = downside.copy()
            evidence["Status"] = evidence["Active"].map(
                {True: "Active", False: "Clear"}
            )
            st.dataframe(
                evidence[["Metric", "Current", "Trigger", "Status"]],
                hide_index=True,
                width="stretch",
            )
    st.caption(
        "Controls are configurable research guardrails. News and social sentiment "
        "are not yet included in the regime score."
    )