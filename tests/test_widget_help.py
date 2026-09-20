from stockfinder.presentation.dashboard import WidgetSpec
from stockfinder.presentation.widget_help import (
    SECTIONS,
    WIDGET_HELP,
    widget_methodology,
)
from stockfinder.widgets import built_in_widget_registry


def test_every_built_in_widget_has_complete_methodology() -> None:
    assert set(built_in_widget_registry().widget_types) == set(WIDGET_HELP)
    for widget_type in built_in_widget_registry().widget_types:
        text = widget_methodology(
            WidgetSpec(widget_type, widget_type, widget_type)
        )
        assert all(section in text for section in SECTIONS)


def test_score_evidence_methodology_names_configured_dimension() -> None:
    text = widget_methodology(
        WidgetSpec(
            "risk-evidence",
            "security_score_evidence",
            "Safety Evidence",
            settings={"dimension": "risk"},
        )
    )

    assert "**Configured dimension:** Risk" in text
    assert "Risk components are inverted" in text


def test_custom_widget_receives_explicit_undocumented_help() -> None:
    text = widget_methodology(WidgetSpec("custom", "custom", "Custom"))

    assert "Not documented for this custom widget" in text