import pandas as pd

from stockfinder.data import DataResult
from stockfinder.widgets.peer_comparison import (
    _peer_comparison_figure,
    comparison_summary,
    historical_return_context,
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


def test_comparison_summary_reports_explicit_selected_and_benchmark_deltas() -> None:
    performance = pd.DataFrame(
        {"TARGET": [100.0, 120.0], "PEER": [100.0, 110.0], "INDEX": [100.0, 105.0]}
    )

    summary = comparison_summary(
        performance, "TARGET", "INDEX", "regional benchmark"
    ).set_index("Symbol")

    assert summary.loc["PEER", "Vs selected %"] == -10.0
    assert summary.loc["PEER", "Vs benchmark %"] == 5.0
    assert summary.loc["INDEX", "Role"] == "Regional Benchmark"


def test_historical_return_context_reports_own_distribution() -> None:
    history = pd.DataFrame({"Close": range(100, 400)})

    context = historical_return_context(history, sessions=20)

    assert context is not None
    assert context["minimum"] <= context["median"] <= context["maximum"]
    assert 0 <= context["percentile"] <= 100