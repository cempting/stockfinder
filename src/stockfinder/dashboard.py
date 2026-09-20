"""Configuration model and loader for composable dashboards."""

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from stockfinder.runtime import application_data_dir

DEFAULT_DASHBOARDS_PATH = Path(__file__).with_name("default_dashboards.json")


@dataclass(frozen=True)
class WidgetSpec:
    """One configured widget instance on a dashboard."""

    widget_id: str
    widget_type: str
    title: str
    width: int = 12
    follow_context: bool = True
    settings: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class DashboardSpec:
    """A named collection of configured widget instances."""

    dashboard_id: str
    title: str
    description: str
    widgets: tuple[WidgetSpec, ...]


def load_dashboards(path: str | Path | None = None) -> tuple[DashboardSpec, ...]:
    """Load and validate dashboard definitions from JSON."""
    source = Path(path) if path is not None else DEFAULT_DASHBOARDS_PATH
    payload = json.loads(source.read_text(encoding="utf-8"))
    if payload.get("version") != 1:
        raise ValueError("Dashboard configuration version must be 1")
    raw_dashboards = payload.get("dashboards")
    if not isinstance(raw_dashboards, list) or not raw_dashboards:
        raise ValueError("Dashboard configuration needs at least one dashboard")

    dashboards = tuple(_parse_dashboard(item) for item in raw_dashboards)
    dashboard_ids = [dashboard.dashboard_id for dashboard in dashboards]
    if len(dashboard_ids) != len(set(dashboard_ids)):
        raise ValueError("Dashboard IDs must be unique")
    return dashboards


def load_application_dashboards() -> tuple[DashboardSpec, ...]:
    """Load a user-owned dashboard file when present, otherwise packaged defaults."""
    configured_path = application_data_dir() / "dashboards.json"
    return load_dashboards(
        configured_path if configured_path.exists() else DEFAULT_DASHBOARDS_PATH
    )


def _parse_dashboard(raw: object) -> DashboardSpec:
    if not isinstance(raw, dict):
        raise ValueError("Each dashboard must be an object")
    dashboard_id = _required_text(raw, "id", "Dashboard")
    title = _required_text(raw, "title", f"Dashboard {dashboard_id}")
    raw_widgets = raw.get("widgets")
    if not isinstance(raw_widgets, list) or not raw_widgets:
        raise ValueError(f"Dashboard {dashboard_id} needs at least one widget")
    widgets = tuple(_parse_widget(item, dashboard_id) for item in raw_widgets)
    widget_ids = [widget.widget_id for widget in widgets]
    if len(widget_ids) != len(set(widget_ids)):
        raise ValueError(f"Dashboard {dashboard_id} widget IDs must be unique")
    return DashboardSpec(
        dashboard_id=dashboard_id,
        title=title,
        description=str(raw.get("description", "")).strip(),
        widgets=widgets,
    )


def _parse_widget(raw: object, dashboard_id: str) -> WidgetSpec:
    if not isinstance(raw, dict):
        raise ValueError(f"Dashboard {dashboard_id} widgets must be objects")
    widget_id = _required_text(raw, "id", f"Dashboard {dashboard_id} widget")
    widget_type = _required_text(raw, "type", f"Widget {widget_id}")
    width = raw.get("width", 12)
    if not isinstance(width, int) or not 1 <= width <= 12:
        raise ValueError(f"Widget {widget_id} width must be between 1 and 12")
    settings = raw.get("settings", {})
    if not isinstance(settings, dict):
        raise ValueError(f"Widget {widget_id} settings must be an object")
    return WidgetSpec(
        widget_id=widget_id,
        widget_type=widget_type,
        title=str(raw.get("title") or widget_type.replace("_", " ").title()),
        width=width,
        follow_context=bool(raw.get("follow_context", True)),
        settings=settings,
    )


def _required_text(raw: dict[str, Any], key: str, owner: str) -> str:
    value = str(raw.get(key, "")).strip()
    if not value:
        raise ValueError(f"{owner} {key} must not be empty")
    return value