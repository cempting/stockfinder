"""Render configured dashboard widgets into responsive Streamlit rows."""

import streamlit as st

from stockfinder.dashboard import DashboardSpec, WidgetSpec
from stockfinder.dashboard_runtime import DashboardServices
from stockfinder.navigation import AnalysisContext
from stockfinder.widget_registry import WidgetRegistry


def render_dashboard(
    dashboard: DashboardSpec,
    registry: WidgetRegistry,
    context: AnalysisContext,
    services: DashboardServices,
) -> None:
    """Render a dashboard while respecting each widget's configured width."""
    if dashboard.description:
        st.caption(dashboard.description)
    breadcrumb = context.breadcrumb()
    if breadcrumb:
        st.markdown("**Context:** " + " / ".join(breadcrumb))

    for row in _widget_rows(dashboard.widgets):
        columns = st.columns([widget.width for widget in row])
        for column, widget in zip(columns, row, strict=True):
            with column:
                st.subheader(widget.title)
                registry.resolve(widget.widget_type)(widget, context, services)


def _widget_rows(widgets: tuple[WidgetSpec, ...]) -> tuple[tuple[WidgetSpec, ...], ...]:
    rows: list[tuple[WidgetSpec, ...]] = []
    current: list[WidgetSpec] = []
    used_width = 0
    for widget in widgets:
        if current and used_width + widget.width > 12:
            rows.append(tuple(current))
            current = []
            used_width = 0
        current.append(widget)
        used_width += widget.width
    if current:
        rows.append(tuple(current))
    return tuple(rows)