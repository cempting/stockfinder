import json

import pytest

from stockfinder.presentation.dashboard import (
    load_application_dashboards,
    load_dashboards,
)
from stockfinder.presentation.dashboard_renderer import _widget_rows
from stockfinder.presentation.navigation import AnalysisContext
from stockfinder.presentation.widget_registry import WidgetRegistry
from stockfinder.widgets import built_in_widget_registry
from stockfinder.widgets.instrument_analysis import _instrument_figure
from stockfinder.widgets.rotation_explorer import _ordered_groups


def test_default_dashboards_define_multiple_widget_compositions() -> None:
    dashboards = load_dashboards()

    assert [dashboard.dashboard_id for dashboard in dashboards] == [
        "daily-command-center",
        "instrument-workbench",
        "portfolio-monitor",
    ]
    assert [widget.widget_type for widget in dashboards[0].widgets] == [
        "market_regime",
        "cross_asset_conditions",
        "regional_markets",
        "rotation_explorer",
        "liquidity_breadth",
        "ranked_stocks",
        "instrument_analysis",
        "rule_profile_editor",
    ]
    assert [widget.widget_type for widget in dashboards[1].widgets] == [
        "instrument_analysis",
        "security_score_evidence",
        "security_score_evidence",
        "security_score_evidence",
        "trade_plan",
        "peer_comparison",
    ]
    dimensions = [
        widget.settings.get("dimension") for widget in dashboards[1].widgets[1:4]
    ]
    assert dimensions == [
        "fundamental",
        "risk",
        "technical",
    ]


def test_instrument_chart_includes_aligned_volume() -> None:
    import pandas as pd

    dates = pd.bdate_range("2026-01-01", periods=180)
    history = pd.DataFrame(
        {
            "Close": range(100, 280),
            "Volume": range(1_000, 1_180),
        },
        index=dates,
    )

    figure = _instrument_figure(history)

    assert [trace.name for trace in figure.data] == [
        "Price",
        "SMA50",
        "SMA150",
        "Volume",
    ]
    assert figure.data[-1].type == "bar"
    assert figure.data[-1].yaxis == "y2"


def test_application_dashboards_use_data_directory_override(
    monkeypatch, tmp_path
) -> None:
    custom = {
        "version": 1,
        "dashboards": [
            {
                "id": "custom",
                "title": "Custom",
                "widgets": [{"id": "instrument", "type": "instrument_analysis"}],
            }
        ],
    }
    (tmp_path / "dashboards.json").write_text(json.dumps(custom), encoding="utf-8")
    monkeypatch.setenv("STOCKFINDER_DATA_DIR", str(tmp_path))

    dashboards = load_application_dashboards()

    assert [dashboard.dashboard_id for dashboard in dashboards] == ["custom"]


def test_dashboard_loader_rejects_duplicate_widget_ids(tmp_path) -> None:
    path = tmp_path / "dashboards.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "dashboards": [
                    {
                        "id": "test",
                        "title": "Test",
                        "widgets": [
                            {"id": "same", "type": "one"},
                            {"id": "same", "type": "two"},
                        ],
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="widget IDs must be unique"):
        load_dashboards(path)


def test_registry_rejects_unknown_configured_widget() -> None:
    registry = WidgetRegistry()
    registry.register("market_regime", lambda spec, context, services: None)

    with pytest.raises(ValueError, match="Unknown widget type"):
        registry.validate(load_dashboards())


def test_built_in_registry_supports_default_dashboards() -> None:
    registry = built_in_widget_registry()

    registry.validate(load_dashboards())

    assert registry.widget_types == (
        "alert_center",
        "market_regime",
        "cross_asset_conditions",
        "regional_markets",
        "liquidity_breadth",
        "rotation_explorer",
        "ranked_stocks",
        "instrument_analysis",
        "rule_profile_editor",
        "security_score_evidence",
        "peer_comparison",
        "trade_plan",
        "portfolio_exposure",
    )


def test_linked_context_clears_descendants_when_parent_changes() -> None:
    state = {}
    context = AnalysisContext(state)
    context.select("region", "Europe")
    context.select("sector", "Industrials")
    context.select("industry", "Machinery")
    context.select("instrument", "SIE.DE")

    context.select("sector", "Information Technology")

    assert context.snapshot() == {
        "region": "Europe",
        "sector": "Information Technology",
    }
    assert context.breadcrumb() == ("Europe", "Information Technology")


def test_dashboard_renderer_groups_widgets_into_twelve_column_rows() -> None:
    widgets = load_dashboards()[0].widgets

    rows = _widget_rows(widgets)

    assert [[widget.width for widget in row] for row in rows] == [
        [4, 8],
        [12],
        [6, 6],
        [7, 5],
        [12],
    ]
    workbench_rows = _widget_rows(load_dashboards()[1].widgets)
    assert [[widget.width for widget in row] for row in workbench_rows] == [
        [12],
        [4, 4, 4],
        [12],
        [12],
    ]
    portfolio_rows = _widget_rows(load_dashboards()[2].widgets)
    assert [widget.widget_type for widget in load_dashboards()[2].widgets] == [
        "alert_center",
        "portfolio_exposure",
    ]
    assert [[widget.width for widget in row] for row in portfolio_rows] == [
        [12],
        [12],
    ]


def test_rotation_context_options_are_ordered_by_strongest_group() -> None:
    import pandas as pd

    frame = pd.DataFrame(
        {
            "Region": ["Europe", "Europe", "Asia"],
            "Rotation score": [60.0, 80.0, 70.0],
        }
    )

    assert _ordered_groups(frame, "Region") == ["Europe", "Asia"]