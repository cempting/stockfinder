"""Streamlit controls synchronized with the shared analysis context."""

import streamlit as st

from stockfinder.presentation.navigation import AnalysisContext


def linked_selectbox(
    label: str,
    options: list[str],
    level: str,
    context: AnalysisContext,
    key: str,
    follow_context: bool,
) -> str:
    """Render a selector that adopts external context without writing it back."""
    if not options:
        return ""
    current = context.get(level) if follow_context else None
    marker_key = f"{key}__linked_context"
    if follow_context and context.state.get(marker_key) != current:
        context.state[key] = current if current in options else options[0]
        context.state[marker_key] = current

    selected = st.selectbox(label, options, key=key)
    if follow_context and selected != current:
        context.select(level, selected)
        context.state[marker_key] = selected
    return selected


def linked_optional_selectbox(
    label: str,
    options: list[str],
    level: str,
    context: AnalysisContext,
    key: str,
    follow_context: bool,
    all_label: str,
) -> str | None:
    """Render a linked selector whose first option clears that context level."""
    display_options = [all_label, *options]
    current = context.get(level) if follow_context else None
    marker_key = f"{key}__linked_context"
    if follow_context and context.state.get(marker_key) != current:
        context.state[key] = current if current in options else all_label
        context.state[marker_key] = current

    selected = st.selectbox(label, display_options, key=key)
    value = None if selected == all_label else selected
    if follow_context and value != current:
        context.select(level, value)
        context.state[marker_key] = value
    return value