import pandas as pd

from stockfinder.data import DataResult
from stockfinder.widgets.peer_comparison import (
    _peer_comparison_figure,
    select_peer_symbols,
)


def test_select_peer_symbols_stays_within_region_and_industry() -> None:
    universe = pd.DataFrame(
        {
            "Symbol": ["TARGET", "LARGE", "SMALL", "OTHER", "FOREIGN"],
            "Region": ["Europe", "Europe", "Europe", "Europe", "Asia"],
            "Sector": ["Technology"] * 5,
            "Industry": ["Software", "Software", "Software", "Hardware", "Software"],
            "Market cap": [50, 100, 20, 200, 300],
        }
    )

    peers, attributes = select_peer_symbols(universe, "TARGET", limit=2)

    assert peers == ["LARGE", "SMALL"]
    assert attributes == {
        "region": "Europe",
        "sector": "Technology",
        "industry": "Software",
    }


def test_peer_comparison_includes_relative_volume_for_each_instrument() -> None:
    from datetime import UTC, datetime

    dates = pd.bdate_range("2026-01-01", periods=30)
    histories = {
        symbol: pd.DataFrame(
            {"Close": range(100, 130), "Volume": range(1_000, 1_030)},
            index=dates,
        )
        for symbol in ("TARGET", "PEER")
    }
    performance = pd.DataFrame(
        {
            symbol: history["Close"] / history["Close"].iloc[0] * 100
            for symbol, history in histories.items()
        }
    )
    results = {
        symbol: DataResult(history, "test", datetime.now(UTC))
        for symbol, history in histories.items()
    }

    figure = _peer_comparison_figure(performance, results, "TARGET", "PEER")

    assert [trace.name for trace in figure.data[-2:]] == [
        "TARGET volume",
        "PEER volume",
    ]
    assert all(trace.yaxis == "y2" for trace in figure.data[-2:])