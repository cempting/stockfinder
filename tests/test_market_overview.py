import pandas as pd

from stockfinder.market_overview import (
    downside_control_response,
    downside_risk_snapshot,
    industry_confirmation_snapshot,
    market_snapshot,
    regional_confirmation_snapshot,
    regional_market_snapshot,
    sector_allocation_snapshot,
)


def _history(start: float, end: float, periods: int = 180) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Close": [
                start + (end - start) * index / (periods - 1)
                for index in range(periods)
            ]
        },
        index=pd.bdate_range("2026-01-01", periods=periods),
    )


def test_market_snapshot_reports_momentum_trend_and_volatility() -> None:
    snapshot = market_snapshot(
        {"UP": _history(100, 150), "DOWN": _history(150, 100)},
        {"UP": "Risk asset", "DOWN": "Defensive asset"},
    ).set_index("Symbol")

    assert snapshot.loc["UP", "3M %"] > 0
    assert bool(snapshot.loc["UP", "Above SMA150"])
    assert snapshot.loc["UP", "Trend score"] == 100
    assert snapshot.loc["DOWN", "Trend score"] == 0


def test_regional_snapshot_ranks_strength_and_compares_with_global() -> None:
    snapshot = regional_market_snapshot(
        {
            "ACWI": _history(100, 120),
            "SPY": _history(100, 140),
            "VGK": _history(100, 110),
        },
        {"Global": "ACWI", "United States": "SPY", "Europe": "VGK"},
    )

    assert snapshot.iloc[0]["Region"] == "United States"
    assert snapshot.set_index("Region").loc["United States", "Relative 3M %"] > 0
    assert snapshot.set_index("Region").loc["Europe", "Relative 3M %"] < 0


def test_regional_confirmation_distinguishes_broad_and_narrow_leaders() -> None:
    benchmarks = pd.DataFrame(
        {
            "Region": ["Europe", "Asia"],
            "Trend score": [100.0, 100.0],
            "Relative 3M %": [4.0, 4.0],
        }
    )
    industries = pd.DataFrame(
        {
            "Region": ["Europe", "Europe", "Asia", "Asia"],
            "Above rising SMA150 %": [80.0, 70.0, 30.0, 20.0],
            "Liquidity composite": [70.0, 60.0, 70.0, 60.0],
            "Rotation score": [75.0, 65.0, 75.0, 65.0],
        }
    )

    snapshot = regional_confirmation_snapshot(benchmarks, industries).set_index(
        "Region"
    )

    assert snapshot.loc["Europe", "Confirmation"] == "Confirmed leader"
    assert snapshot.loc["Asia", "Confirmation"] == "Narrow leader"


def test_sector_allocation_reconstructs_cached_participation_and_stance() -> None:
    sectors = pd.DataFrame(
        {
            "Region": ["Europe", "Europe"],
            "Sector": ["Industrials", "Technology"],
            "Industries": [2, 1],
            "Winners": [2, 0],
            "Liquidity composite": [70.0, 65.0],
            "Flow composite %": [4.0, 2.0],
            "Rotation score": [75.0, 70.0],
        }
    )
    industries = pd.DataFrame(
        {
            "Region": ["Europe", "Europe", "Europe"],
            "Sector": ["Industrials", "Industrials", "Technology"],
            "Members": [3, 1, 2],
            "Above rising SMA150 %": [80.0, 40.0, 30.0],
        }
    )

    snapshot = sector_allocation_snapshot(sectors, industries).set_index("Sector")

    assert snapshot.loc["Industrials", "Members"] == 4
    assert snapshot.loc["Industrials", "Above rising SMA150 %"] == 70.0
    assert snapshot.loc["Industrials", "Stance"] == "Leadership"
    assert snapshot.loc["Technology", "Stance"] == "Narrow strength"


def test_industry_confirmation_separates_broad_and_thin_leadership() -> None:
    industries = pd.DataFrame(
        {
            "Industry": ["Broad", "Thin"],
            "Rotation score": [75.0, 75.0],
            "Liquidity composite": [70.0, 70.0],
            "Flow composite %": [3.0, 3.0],
            "Above rising SMA150 %": [80.0, 80.0],
            "Members": [8, 2],
        }
    )

    snapshot = industry_confirmation_snapshot(industries).set_index("Industry")

    assert snapshot.loc["Broad", "Confirmation"] == "Broad leadership"
    assert snapshot.loc["Thin", "Confirmation"] == "Thin leadership"


def test_downside_risk_snapshot_keeps_triggers_independent() -> None:
    volatile_spy = _history(100, 130)
    volatile_spy.iloc[-1, 0] = 100
    surging_dollar = _history(100, 101)
    surging_dollar.iloc[-1, 0] = 110
    snapshot = downside_risk_snapshot(
        {
            "SPY": volatile_spy,
            "HYG": _history(100, 90),
            "IEF": _history(100, 110),
            "UUP": surging_dollar,
            "^VIX": _history(20, 30),
        }
    ).set_index("Metric")

    assert bool(snapshot.loc["Equity drawdown", "Active"])
    assert bool(snapshot.loc["Realized volatility", "Active"])
    assert bool(snapshot.loc["VIX level", "Active"])
    assert bool(snapshot.loc["Credit underperformance", "Active"])
    assert bool(snapshot.loc["Dollar surge", "Active"])


def test_downside_control_response_escalates_with_visible_trigger_count() -> None:
    assert downside_control_response(0)[0] == "Normal"
    assert downside_control_response(1)[0] == "Monitor"
    assert downside_control_response(2)[0] == "Cautious"
    assert downside_control_response(4)[0] == "Defensive"