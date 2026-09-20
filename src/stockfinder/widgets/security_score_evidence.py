"""Independent fundamental, safety, and technical score evidence widgets."""

import pandas as pd
import plotly.express as px
import streamlit as st

from stockfinder.dashboard import WidgetSpec
from stockfinder.dashboard_runtime import DashboardServices
from stockfinder.models import Score
from stockfinder.navigation import AnalysisContext

DIMENSIONS = ("fundamental", "risk", "technical")


def score_evidence_frame(score: Score, *, invert: bool = False) -> pd.DataFrame:
    """Return display-ready score components with higher values always better."""
    rows = [
        {
            "Evidence": name,
            "Score": round(100 - value if invert else value, 1),
        }
        for name, value in score.components.items()
    ]
    return pd.DataFrame(rows, columns=["Evidence", "Score"]).sort_values(
        "Score", ascending=True
    )


def render_security_score_evidence(
    spec: WidgetSpec,
    context: AnalysisContext,
    services: DashboardServices,
) -> None:
    dimension = str(spec.settings.get("dimension", "technical")).lower()
    if dimension not in DIMENSIONS:
        st.error(f"Unsupported score dimension: {dimension}")
        return
    symbol = (
        context.get("instrument") if spec.follow_context else None
    ) or str(spec.settings.get("default_symbol", "SPY"))
    with st.spinner(f"Loading {dimension} evidence for {symbol}..."):
        result = services.analyze_security(symbol)

    score = {
        "fundamental": result.analysis.quality,
        "risk": result.analysis.risk,
        "technical": result.analysis.technical,
    }[dimension]
    invert = dimension == "risk"
    displayed_score = 100 - score.value if invert else score.value
    label = "Safety" if invert else dimension.title()
    delta = f"Observed risk: {score.label}" if invert else score.label
    st.caption(f"{symbol} · component evidence")
    st.metric(
        label,
        f"{max(0.0, min(100.0, displayed_score)) / 10:.1f}/10",
        delta,
        delta_color="inverse" if invert else "normal",
    )
    st.caption(f"Evidence completeness: {score.completeness:.0f}%")

    evidence = score_evidence_frame(score, invert=invert)
    if evidence.empty:
        st.info(f"No {dimension} components are available for {symbol}.")
        return
    figure = px.bar(
        evidence,
        x="Score",
        y="Evidence",
        orientation="h",
        color="Score",
        color_continuous_scale=["#b9472f", "#f4e8b8", "#16734a"],
        range_color=[0, 100],
    )
    figure.update_layout(
        height=max(260, 42 * len(evidence)),
        margin={"l": 0, "r": 0, "t": 10, "b": 0},
        coloraxis_showscale=False,
    )
    figure.update_xaxes(range=[0, 100])
    st.plotly_chart(figure, width="stretch", key=f"{spec.widget_id}_evidence")
    source = (
        result.profile.source
        if dimension == "fundamental"
        else result.history.source
    )
    st.caption(f"Source: {source} · missing inputs reduce completeness")