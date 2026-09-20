"""Registry for independently implemented dashboard widgets."""

from collections.abc import Callable
from typing import Any

from stockfinder.presentation.dashboard import DashboardSpec, WidgetSpec
from stockfinder.presentation.navigation import AnalysisContext

WidgetRenderer = Callable[[WidgetSpec, AnalysisContext, Any], None]


class WidgetRegistry:
    """Map configured widget type names to rendering functions."""

    def __init__(self) -> None:
        self._renderers: dict[str, WidgetRenderer] = {}

    def register(self, widget_type: str, renderer: WidgetRenderer) -> None:
        name = widget_type.strip()
        if not name:
            raise ValueError("Widget type must not be empty")
        if name in self._renderers:
            raise ValueError(f"Widget type already registered: {name}")
        self._renderers[name] = renderer

    def resolve(self, widget_type: str) -> WidgetRenderer:
        try:
            return self._renderers[widget_type]
        except KeyError as error:
            raise ValueError(f"Unknown widget type: {widget_type}") from error

    @property
    def widget_types(self) -> tuple[str, ...]:
        return tuple(self._renderers)

    def validate(self, dashboards: tuple[DashboardSpec, ...]) -> None:
        for dashboard in dashboards:
            for widget in dashboard.widgets:
                self.resolve(widget.widget_type)