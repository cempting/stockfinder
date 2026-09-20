from stockfinder.widgets.trade_plan import (
    RISK_PRESETS,
    candidate_stop_levels,
    suggested_account_value,
)


def test_candidate_stop_levels_follow_selected_risk_posture() -> None:
    stops = candidate_stop_levels(
        entry_price=100.0,
        atr=4.0,
        structural_stop=91.0,
        sma50=94.0,
        swing_low=92.0,
        preset=RISK_PRESETS["Balanced"],
    )

    assert stops == {
        "ATR (2.0x)": 92.0,
        "Structural base stop": 91.0,
        "50-day average": 94.0,
        "Recent 20-day swing low": 92.0,
        "Trailing stop": 91.0,
    }


def test_suggested_account_value_supports_high_unit_price_instruments() -> None:
    assert suggested_account_value(700.0, 650.0, 0.5) == 100_000.0
    assert suggested_account_value(1_857_000.0, 1_679_571.43, 0.5) == 35_486_000.0