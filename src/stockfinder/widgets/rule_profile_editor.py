"""Editable screening-profile controls for modular dashboards."""

import streamlit as st

from stockfinder.config import (
    PROFILE_COMPOSITION_PRESETS,
    apply_profile_composition_preset,
    configured_rule_profile,
    update_rule_profile,
)
from stockfinder.dashboard import WidgetSpec
from stockfinder.dashboard_runtime import DashboardServices
from stockfinder.navigation import AnalysisContext


def render_rule_profile_editor(
    spec: WidgetSpec,
    context: AnalysisContext,
    services: DashboardServices,
) -> None:
    del context
    config = services.get_analysis_config()
    profile_names = tuple(config["rule_profiles"])
    profile_name = st.selectbox(
        "Profile to edit",
        profile_names,
        key=f"{spec.widget_id}_profile",
    )
    profile = configured_rule_profile(config["rule_profiles"][profile_name])
    preset_column, apply_column = st.columns([3, 1])
    preset_name = preset_column.selectbox(
        "Composition preset",
        tuple(PROFILE_COMPOSITION_PRESETS),
        key=f"{spec.widget_id}_preset",
    )
    if apply_column.button(
        "Apply",
        icon=":material/tune:",
        key=f"{spec.widget_id}_apply_preset",
    ):
        updated = apply_profile_composition_preset(config, profile_name, preset_name)
        services.save_analysis_config(updated)
        st.rerun()
    with st.form(f"{spec.widget_id}_form"):
        setup, volatility = st.columns(2)
        minimum_setup = setup.number_input(
            "Minimum setup score",
            min_value=0,
            max_value=100,
            value=int(profile["minimum_setup_score"]),
        )
        maximum_volatility = volatility.number_input(
            "Maximum annualized volatility %",
            min_value=0,
            max_value=100,
            value=int(profile["maximum_volatility_pct"]),
        )
        safety, fundamental = st.columns(2)
        minimum_safety = safety.number_input(
            "Minimum safety score",
            min_value=0,
            max_value=100,
            value=int(profile["minimum_safety_score"]),
        )
        minimum_fundamental = fundamental.number_input(
            "Minimum fundamental score",
            min_value=0,
            max_value=100,
            value=int(profile["minimum_fundamental_score"]),
        )
        require_sma150 = st.checkbox(
            "Require price above SMA150",
            value=bool(profile["require_above_sma150"]),
        )
        st.markdown("**Weighted composition**")
        weighted_enabled = st.toggle(
            "Require minimum weighted score",
            value=bool(profile["weighted_score_enabled"]),
        )
        weighted_minimum = st.number_input(
            "Minimum weighted score",
            min_value=0,
            max_value=100,
            value=int(profile["minimum_weighted_score"]),
        )
        setup_weight, safety_weight, fundamental_weight, trend_weight = st.columns(4)
        setup_weight_value = setup_weight.number_input(
            "Setup weight",
            min_value=0,
            max_value=100,
            value=int(profile["setup_weight"]),
        )
        safety_weight_value = safety_weight.number_input(
            "Safety weight",
            min_value=0,
            max_value=100,
            value=int(profile["safety_weight"]),
        )
        fundamental_weight_value = fundamental_weight.number_input(
            "Fundamental weight",
            min_value=0,
            max_value=100,
            value=int(profile["fundamental_weight"]),
        )
        trend_weight_value = trend_weight.number_input(
            "Trend weight",
            min_value=0,
            max_value=100,
            value=int(profile["trend_weight"]),
        )
        weight_total = (
            setup_weight_value
            + safety_weight_value
            + fundamental_weight_value
            + trend_weight_value
        )
        st.caption(
            "Weights are normalized across available evidence. Current total: "
            f"{weight_total}"
        )
        submitted = st.form_submit_button("Save profile", type="primary")
    if submitted:
        try:
            updated = update_rule_profile(
                config,
                profile_name,
                {
                    "minimum_setup_score": minimum_setup,
                    "maximum_volatility_pct": maximum_volatility,
                    "minimum_safety_score": minimum_safety,
                    "minimum_fundamental_score": minimum_fundamental,
                    "require_above_sma150": require_sma150,
                    "weighted_score_enabled": weighted_enabled,
                    "minimum_weighted_score": weighted_minimum,
                    "setup_weight": setup_weight_value,
                    "safety_weight": safety_weight_value,
                    "fundamental_weight": fundamental_weight_value,
                    "trend_weight": trend_weight_value,
                },
            )
            services.save_analysis_config(updated)
            st.success(f"Saved {profile_name} profile.")
        except ValueError as error:
            st.error(str(error))