"""Risk-budgeted trade planning for the selected instrument."""

from collections.abc import Mapping
from math import ceil

import pandas as pd
import streamlit as st

from stockfinder.analysis import (
    analyze_long_swing_setup,
    calculate_position_plan,
    calculate_reward_risk,
)
from stockfinder.presentation.dashboard import WidgetSpec
from stockfinder.presentation.dashboard_runtime import DashboardServices
from stockfinder.presentation.navigation import AnalysisContext

RISK_PRESETS = {
    "Conservative": {"atr_multiplier": 1.5, "trailing_pct": 6.0, "risk_pct": 0.25},
    "Balanced": {"atr_multiplier": 2.0, "trailing_pct": 9.0, "risk_pct": 0.5},
    "Aggressive": {"atr_multiplier": 2.5, "trailing_pct": 12.0, "risk_pct": 1.0},
}


def suggested_account_value(
    entry_price: float,
    stop_price: float,
    risk_percent: float,
) -> float:
    """Provide a default that can fund ten shares and risk at least one."""
    cash_requirement = entry_price * 10
    one_share_risk_requirement = (entry_price - stop_price) / (risk_percent / 100)
    required = max(100_000.0, cash_requirement, one_share_risk_requirement)
    return float(ceil(required / 1_000) * 1_000)


def candidate_stop_levels(
    *,
    entry_price: float,
    atr: float,
    structural_stop: float,
    sma50: float,
    swing_low: float,
    preset: Mapping[str, float],
) -> dict[str, float]:
    """Build transparent stop candidates for one risk posture."""
    multiplier = float(preset["atr_multiplier"])
    trailing_pct = float(preset["trailing_pct"])
    return {
        f"ATR ({multiplier:.1f}x)": entry_price - multiplier * atr,
        "Structural base stop": structural_stop,
        "50-day average": sma50,
        "Recent 20-day swing low": swing_low,
        "Trailing stop": entry_price * (1 - trailing_pct / 100),
    }


def render_trade_plan(
    spec: WidgetSpec,
    context: AnalysisContext,
    services: DashboardServices,
) -> None:
    symbol = (
        context.get("instrument") if spec.follow_context else None
    ) or str(spec.settings.get("default_symbol", "SPY"))
    with st.spinner(f"Building trade plan for {symbol}..."):
        result = services.analyze_security(symbol)
    setup = analyze_long_swing_setup(result.history.data)
    currency = str(result.profile.data.get("currency") or "units")

    risk_profile = st.segmented_control(
        "Trade risk posture",
        tuple(RISK_PRESETS),
        default="Balanced",
        key=f"{spec.widget_id}_{symbol}_posture",
    ) or "Balanced"
    preset = RISK_PRESETS[risk_profile]
    sma50 = float(result.history.data["Close"].rolling(50).mean().iloc[-1])
    stop_levels = candidate_stop_levels(
        entry_price=setup.suggested_entry,
        atr=result.atr,
        structural_stop=setup.structural_stop,
        sma50=sma50,
        swing_low=result.swing_low,
        preset=preset,
    )

    state, setup_score, atr_percent = st.columns(3)
    state.metric("Swing state", setup.state)
    setup_score.metric("Setup score", f"{setup.score / 10:.1f}/10")
    atr_percent.metric("ATR14", f"{result.atr / result.latest_price * 100:.1f}%")

    level_column = f"Candidate level ({currency})"
    stops = pd.DataFrame(stop_levels.items(), columns=["Method", level_column])
    st.dataframe(
        stops,
        hide_index=True,
        width="stretch",
        column_config={
            level_column: st.column_config.NumberColumn(format="%.2f")
        },
    )

    account, risk, stop_method = st.columns(3)
    selected_stop_method = stop_method.selectbox(
        "Stop method",
        tuple(stop_levels),
        key=f"{spec.widget_id}_{symbol}_stop_method",
    )
    initial_stop = min(
        setup.suggested_entry - 0.01,
        stop_levels[selected_stop_method],
    )
    account_value = account.number_input(
        f"Account value ({currency})",
        min_value=1_000.0,
        value=suggested_account_value(
            setup.suggested_entry,
            max(0.0, initial_stop),
            float(preset["risk_pct"]),
        ),
        step=1_000.0,
        key=f"{spec.widget_id}_{symbol}_{risk_profile}_{selected_stop_method}_account",
    )
    risk_percent = risk.slider(
        "Account risk %",
        min_value=0.25,
        max_value=3.0,
        value=float(preset["risk_pct"]),
        step=0.25,
        key=f"{spec.widget_id}_{symbol}_risk",
    )
    entry_column, stop_column = st.columns(2)
    entry_price = entry_column.number_input(
        "Planned entry",
        min_value=0.01,
        value=round(max(0.01, setup.suggested_entry), 2),
        key=f"{spec.widget_id}_{symbol}_entry",
    )
    default_stop = min(entry_price - 0.01, stop_levels[selected_stop_method])
    stop_price = stop_column.number_input(
        "Planned stop",
        min_value=0.0,
        value=round(max(0.0, default_stop), 2),
        key=f"{spec.widget_id}_{symbol}_{selected_stop_method}_stop",
    )
    try:
        plan = calculate_position_plan(
            account_value,
            risk_percent,
            entry_price,
            stop_price,
        )
    except ValueError as error:
        st.warning(str(error))
        return

    base_low = setup.structural_stop + 0.25 * result.atr
    measured_move = setup.pivot + max(0.0, setup.pivot - base_low)
    target_options = {
        "2R target": entry_price + 2 * plan.risk_per_share,
        "Measured move": measured_move,
    }
    analyst_target = result.profile.data.get("targetMeanPrice")
    if isinstance(analyst_target, (int, float)):
        target_options["Analyst mean target"] = float(analyst_target)
    target_method = st.selectbox(
        "Target method",
        tuple(target_options),
        key=f"{spec.widget_id}_{symbol}_target_method",
    )
    target_price = st.number_input(
        "Planned target",
        min_value=0.01,
        value=round(max(0.01, target_options[target_method]), 2),
        key=f"{spec.widget_id}_{symbol}_{target_method}_target",
    )
    try:
        reward_risk = calculate_reward_risk(entry_price, stop_price, target_price)
    except ValueError as error:
        st.warning(str(error))
        reward_risk = None

    shares, loss, position_value, reward = st.columns(4)
    shares.metric("Shares", f"{plan.shares:,}")
    loss.metric("Planned loss", f"{currency} {plan.planned_loss:,.2f}")
    position_value.metric(
        "Position value", f"{currency} {plan.position_value:,.2f}"
    )
    reward.metric(
        "Reward / risk",
        f"{reward_risk:.2f}R" if reward_risk is not None else "Invalid",
    )
    if reward_risk is not None and reward_risk < 2 - 1e-9:
        st.warning("Planned reward/risk is below the default 2R minimum.")
    st.session_state[f"active_trade_plan_{symbol}"] = {
        "entry": entry_price,
        "stop": stop_price,
        "target": target_price,
        "shares": plan.shares,
        "reward_risk": reward_risk,
    }
    st.caption(
        f"Risk budget {currency} {plan.risk_budget:,.2f} · risk/share "
        f"{currency} {plan.risk_per_share:,.2f} · risk limit "
        f"{plan.risk_limited_shares:,} shares · cash limit "
        f"{plan.capital_limited_shares:,} shares"
    )