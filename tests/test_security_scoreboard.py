import pandas as pd

from stockfinder.widgets.security_scoreboard import security_scoreboard_frame


def test_security_scoreboard_separates_available_and_missing_evidence() -> None:
    history = pd.DataFrame(
        {
            "Close": [100.0, 102.0, 101.0],
            "Volume": [1_000_000, 1_200_000, 900_000],
        },
        index=pd.bdate_range("2026-01-01", periods=3),
    )

    frame = security_scoreboard_frame(
        {
            "revenueGrowth": 0.12,
            "freeCashflow": 500_000_000,
            "currency": "USD",
        },
        history,
        latest_price=101.0,
        atr=3.0,
    ).set_index("Measure")

    assert frame.loc["Revenue growth", "Status"] == "Available"
    assert frame.loc["Revenue growth", "Evidence type"] == "Reported"
    assert frame.loc["Forward P/E", "Status"] == "Unavailable"
    assert frame.loc["Realized volatility %", "Evidence type"] == "Calculated"
    assert frame.loc["Currency", "Value"] == "USD"