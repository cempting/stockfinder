import numpy as np
import pandas as pd
import pytest

from stockfinder import analysis
from stockfinder.analysis import liquidity_rotation_6m
from stockfinder.data import DataResult


def _history(prices: np.ndarray, volumes: np.ndarray) -> pd.DataFrame:
    return pd.DataFrame({"Close": prices, "Volume": volumes})


def test_price_risk_helpers_preserve_atr_and_recent_swing_low() -> None:
    close = np.arange(100.0, 130.0)
    history = pd.DataFrame(
        {"High": close + 2, "Low": close - 1, "Close": close}
    )

    assert analysis._average_true_range(history) == 3.0
    assert analysis._recent_swing_low(history) == 109.0


def test_six_month_liquidity_favors_accumulation_over_distribution() -> None:
    sessions = 126
    accumulating = _history(
        np.linspace(100, 140, sessions),
        np.linspace(1_000_000, 2_000_000, sessions),
    )
    distributing = _history(
        np.linspace(140, 100, sessions),
        np.linspace(1_000_000, 2_000_000, sessions),
    )

    accumulation = liquidity_rotation_6m(accumulating)
    distribution = liquidity_rotation_6m(distributing)

    assert accumulation["score"] > distribution["score"]
    assert accumulation["flow_balance"] > 0
    assert distribution["flow_balance"] < 0


def test_six_month_liquidity_requires_two_months_of_data() -> None:
    history = _history(np.arange(20, dtype=float), np.full(20, 1_000_000))

    assert liquidity_rotation_6m(history) == {
        "score": 0.0,
        "trend": 0.0,
        "flow_balance": 0.0,
    }


def test_metals_analysis_ranks_stronger_price_and_flow_first() -> None:
    sessions = 180
    histories = {
        "UP": _history(
            np.linspace(100, 160, sessions),
            np.linspace(1_000_000, 2_000_000, sessions),
        ),
        "DOWN": _history(
            np.linspace(150, 90, sessions),
            np.linspace(2_000_000, 1_000_000, sessions),
        ),
        "BENCH": _history(
            np.linspace(100, 110, sessions), np.full(sessions, 1_000_000)
        ),
    }

    ranked = analysis.analyze_metals(
        histories,
        proxies={"UP": ("Rising", "Test"), "DOWN": ("Falling", "Test")},
        benchmark_symbol="BENCH",
    )

    assert ranked["Metal"].tolist() == ["Rising", "Falling"]
    assert ranked.iloc[0]["Metal score"] > ranked.iloc[1]["Metal score"]
    assert ranked.iloc[0]["Relative strength"] > ranked.iloc[1]["Relative strength"]
    assert ranked.iloc[0]["Signal"] in {"Positive", "Strong"}


def test_metals_analysis_excludes_missing_or_short_histories() -> None:
    histories = {
        "SHORT": _history(np.arange(20, dtype=float), np.full(20, 1_000_000))
    }

    ranked = analysis.analyze_metals(
        histories,
        proxies={"SHORT": ("Short", "Test"), "MISSING": ("Missing", "Test")},
    )

    assert ranked.empty


def test_sector_rotation_exposes_six_month_liquidity(monkeypatch) -> None:
    history = _history(
        np.linspace(100, 140, 180),
        np.linspace(1_000_000, 2_000_000, 180),
    )

    monkeypatch.setattr(analysis, "SECTOR_ETFS", {"Test sector": "TEST"})
    monkeypatch.setattr(
        analysis,
        "get_history",
        lambda symbol: DataResult(history, "Test data", pd.Timestamp.now()),
    )

    rotation = analysis.sector_rotation()

    assert rotation.columns[0] == "Price · SMA50"
    assert {
        "Price · SMA50",
        "6M liquidity score",
        "6M liquidity trend %",
        "6M flow balance %",
    }.issubset(rotation.columns)
    assert rotation.iloc[0]["Price · SMA50"].startswith("data:image/png;base64,")


def test_industry_rotation_ranks_stronger_industry_first(monkeypatch) -> None:
    sessions = 180
    universe = pd.DataFrame(
        [
            ("UP1", "Up One", "Test sector", "Strong industry"),
            ("UP2", "Up Two", "Test sector", "Strong industry"),
            ("DOWN", "Down", "Test sector", "Weak industry"),
        ],
        columns=["Symbol", "Name", "Sector", "Industry"],
    )
    histories = {
        "SECTOR": _history(
            np.linspace(100, 105, sessions), np.full(sessions, 1_000_000)
        ),
        "UP1": _history(
            np.linspace(100, 150, sessions), np.linspace(1_000_000, 2_000_000, sessions)
        ),
        "UP2": _history(
            np.linspace(100, 140, sessions), np.linspace(1_000_000, 1_800_000, sessions)
        ),
        "DOWN": _history(
            np.linspace(140, 90, sessions), np.linspace(1_000_000, 1_800_000, sessions)
        ),
    }

    monkeypatch.setattr(analysis, "SECURITY_UNIVERSE", universe)
    monkeypatch.setattr(analysis, "SECTOR_ETFS", {"Test sector": "SECTOR"})
    monkeypatch.setattr(
        analysis,
        "get_history",
        lambda symbol: DataResult(histories[symbol], "Test data", pd.Timestamp.now()),
    )

    industries = analysis.industry_rotation("Test sector")

    assert industries.columns[0] == "Price · SMA50"
    assert industries.iloc[0]["Industry"] == "Strong industry"
    assert industries.iloc[0]["Members"] == 2
    assert industries.iloc[0]["Industry score"] > industries.iloc[1]["Industry score"]
    assert {
        "ETF",
        "Price · SMA50",
        "Relative 3M %",
        "Breadth above SMA50 %",
        "6M liquidity score",
    }.issubset(industries.columns)
    assert industries.iloc[0]["Price · SMA50"].startswith("data:image/png;base64,")


def test_mansfield_ranks_industry_outperformer_first() -> None:
    dates = pd.bdate_range("2024-01-01", periods=520)
    histories = {
        "LEADER": pd.DataFrame(
            {
                "Close": np.linspace(100, 240, len(dates)),
                "Volume": np.full(len(dates), 1_000_000),
            },
            index=dates,
        ),
        "LAGGARD": pd.DataFrame(
            {
                "Close": np.linspace(100, 80, len(dates)),
                "Volume": np.full(len(dates), 1_000_000),
            },
            index=dates,
        ),
    }

    ranked = analysis.rank_stocks_by_mansfield(histories)

    assert ranked.iloc[0]["Symbol"] == "LEADER"
    assert ranked.iloc[0]["Mansfield RS"] > 0
    assert ranked.iloc[1]["Mansfield RS"] < 0


def test_normalized_performance_aligns_mixed_timezone_histories(monkeypatch) -> None:
    naive_dates = pd.bdate_range("2026-01-01", periods=60)
    aware_dates = naive_dates.tz_localize("America/New_York")
    histories = {
        "NAIVE": pd.DataFrame({"Close": np.linspace(100, 120, 60)}, index=naive_dates),
        "AWARE": pd.DataFrame({"Close": np.linspace(80, 100, 60)}, index=aware_dates),
    }
    monkeypatch.setattr(
        analysis,
        "get_history",
        lambda symbol, period: DataResult(
            histories[symbol], "Test data", pd.Timestamp.now()
        ),
    )

    performance = analysis.normalized_performance(["NAIVE", "AWARE"])

    assert list(performance.columns) == ["NAIVE", "AWARE"]
    assert len(performance) == 60
    assert performance.index.tz is None


def test_broad_rotation_excludes_downward_industry() -> None:
    dates = pd.bdate_range("2025-01-01", periods=220)
    universe = pd.DataFrame(
        [
            ("UP", "Up", "Technology", "Winner"),
            ("DOWN", "Down", "Energy", "Loser"),
        ],
        columns=["Symbol", "Name", "Sector", "Industry"],
    )
    histories = {
        "UP": pd.DataFrame(
            {
                "Close": np.linspace(100, 160, len(dates)),
                "Volume": np.linspace(1_000_000, 2_000_000, len(dates)),
            },
            index=dates,
        ),
        "DOWN": pd.DataFrame(
            {
                "Close": np.linspace(160, 80, len(dates)),
                "Volume": np.linspace(1_000_000, 2_000_000, len(dates)),
            },
            index=dates,
        ),
    }

    _, industries = analysis.broad_rotation_scan(universe, histories)

    assert bool(industries.set_index("Industry").loc["Winner", "Winning"])
    assert not bool(industries.set_index("Industry").loc["Loser", "Winning"])
    assert {
        "Region",
        "Liquidity 1W",
        "Liquidity 1M",
        "Liquidity 3M",
        "Liquidity 6M",
        "Flow 1W %",
        "Flow 1M %",
        "Flow 3M %",
        "Flow 6M %",
        "Liquidity composite",
        "Liquidity confirmations",
        "Momentum change",
        "Liquidity change",
        "Recent flow %",
        "Rotation state",
        "Early rotation score",
        "Early rotation signal",
        "Breadth acceleration",
        "RS inflection",
        "Positive dollar volume",
        "Close pressure",
    }.issubset(industries.columns)


def test_early_rotation_detects_broad_accumulation_before_established_trend() -> None:
    dates = pd.bdate_range("2025-01-01", periods=180)
    baseline = np.full(170, 100.0)
    emerging = np.concatenate([baseline, np.linspace(100, 112, 10)])
    histories = {
        symbol: pd.DataFrame(
            {
                "Close": emerging,
                "High": emerging + 1.0,
                "Low": emerging - 3.0,
                "Volume": np.concatenate(
                    [np.full(175, 1_000_000), np.full(5, 3_000_000)]
                ),
            },
            index=dates,
        )
        for symbol in ("EARLY1", "EARLY2")
    }
    benchmark = pd.Series(np.full(len(dates), 100.0), index=dates)

    evidence = analysis.early_rotation_evidence(histories, benchmark)

    assert evidence["Early rotation signal"] == "Emerging"
    assert evidence["Early rotation score"] >= 65
    assert evidence["Breadth acceleration"] >= 60
    assert evidence["Positive dollar volume"] >= 60
    assert evidence["Close pressure"] >= 60


def test_early_rotation_does_not_reward_volume_during_price_decline() -> None:
    dates = pd.bdate_range("2025-01-01", periods=180)
    falling = np.concatenate([np.full(170, 100.0), np.linspace(100, 85, 10)])
    history = pd.DataFrame(
        {
            "Close": falling,
            "High": falling + 3.0,
            "Low": falling - 1.0,
            "Volume": np.concatenate(
                [np.full(175, 1_000_000), np.full(5, 3_000_000)]
            ),
        },
        index=dates,
    )

    evidence = analysis.early_rotation_evidence(
        {"FALLING": history}, pd.Series(100.0, index=dates)
    )

    assert evidence["Positive dollar volume"] < 50
    assert evidence["Early rotation signal"] != "Emerging"


def test_broad_rotation_keeps_same_industry_separate_by_region() -> None:
    dates = pd.bdate_range("2025-01-01", periods=220)
    universe = pd.DataFrame(
        [
            ("US", "United States", "Financials", "Banks"),
            ("EU", "Europe", "Financials", "Banks"),
        ],
        columns=["Symbol", "Region", "Sector", "Industry"],
    )
    histories = {
        symbol: pd.DataFrame(
            {
                "Close": np.linspace(100, end, len(dates)),
                "Volume": np.linspace(1_000_000, 2_000_000, len(dates)),
            },
            index=dates,
        )
        for symbol, end in (("US", 150), ("EU", 130))
    }

    sectors, industries = analysis.broad_rotation_scan(universe, histories)

    assert set(industries["Region"]) == {"United States", "Europe"}
    assert len(industries) == 2
    assert len(sectors) == 2


@pytest.mark.parametrize(
    ("momentum_change", "liquidity_change", "recent_flow", "expected"),
    [
        (8.0, 12.0, 5.0, "Gaining"),
        (-8.0, -12.0, -5.0, "Losing"),
        (8.0, -2.0, 5.0, "Mixed"),
    ],
)
def test_rotation_state_requires_confirming_price_liquidity_and_flow(
    momentum_change: float,
    liquidity_change: float,
    recent_flow: float,
    expected: str,
) -> None:
    assert (
        analysis.classify_rotation_state(
            momentum_change, liquidity_change, recent_flow
        )
        == expected
    )


def test_breakout_candidates_retain_independent_filter_evidence() -> None:
    dates = pd.bdate_range("2025-01-01", periods=220)
    leader = np.concatenate(
        [np.linspace(50, 130, 200), np.linspace(128, 132, 20)]
    )
    below_sma = np.linspace(160, 70, 220)
    universe = pd.DataFrame(
        [
            ("BASE", "Base", "Technology", "Winner"),
            ("DOWN", "Down", "Technology", "Winner"),
        ],
        columns=["Symbol", "Name", "Sector", "Industry"],
    )
    histories = {
        "BASE": pd.DataFrame(
            {
                "High": leader + 1,
                "Low": leader - 1,
                "Close": leader,
                "Volume": np.full(220, 1_000_000),
            },
            index=dates,
        ),
        "DOWN": pd.DataFrame(
            {
                "High": below_sma + 1,
                "Low": below_sma - 1,
                "Close": below_sma,
                "Volume": np.full(220, 1_000_000),
            },
            index=dates,
        ),
    }

    candidates = analysis.breakout_candidates(universe, histories, {"Winner"})

    evidence = candidates.set_index("Symbol")
    assert set(evidence.index) == {"BASE", "DOWN"}
    assert bool(evidence.loc["BASE", "Price above SMA50"])
    assert bool(evidence.loc["BASE", "Price above SMA150"])
    assert bool(evidence.loc["BASE", "Consolidation base"])
    assert "Base sessions" in evidence
    assert "Heartbeat base" in evidence
    assert "Heartbeat turns" in evidence
    assert "Distance to SMA50 %" in evidence
    assert "Crossed SMA50 recently" in evidence
    assert "SMA50 rising" in evidence
    assert "SMA50 slope 20D %" in evidence
    assert "Volume increasing" in evidence
    assert "Volume trend ratio" in evidence
    assert not bool(evidence.loc["DOWN", "Price above SMA50"])
    assert not bool(evidence.loc["DOWN", "Price above SMA150"])
    assert not bool(evidence.loc["BASE", "Volume Evidence"])


def test_long_swing_rule_confirms_high_volume_breakout() -> None:
    dates = pd.bdate_range("2025-01-01", periods=221)
    close = np.concatenate(
        [np.linspace(40, 120, 200), np.linspace(118, 122, 20), [126]]
    )
    volume = np.concatenate([np.full(220, 1_000_000), [2_000_000]])
    history = pd.DataFrame(
        {
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": volume,
        },
        index=dates,
    )
    history.loc[dates[-1], ["High", "Low"]] = [126.5, 124.0]

    setup = analysis.analyze_long_swing_setup(history)

    assert setup.state == "Breakout confirmed"
    assert setup.checks["Price above SMA150"]
    assert setup.checks["Breakout volume at least 1.5x"]
    assert setup.suggested_entry > setup.pivot


def test_long_swing_rule_rejects_downtrend() -> None:
    dates = pd.bdate_range("2025-01-01", periods=221)
    close = np.linspace(180, 80, len(dates))
    history = pd.DataFrame(
        {
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": np.full(len(dates), 1_000_000),
        },
        index=dates,
    )

    assert analysis.analyze_long_swing_setup(history).state == "Reject: trend"


def test_long_swing_rule_detects_short_base_without_volume_confirmation() -> None:
    dates = pd.bdate_range("2025-01-01", periods=221)
    close = np.concatenate(
        [
            np.linspace(50, 80, 200),
            np.linspace(70, 95, 10),
            np.linspace(98, 102, 10),
            [110],
        ]
    )
    history = pd.DataFrame(
        {
            "High": close + 1,
            "Low": close - 1,
            "Close": close,
            "Volume": np.full(len(dates), 1_000_000),
        },
        index=dates,
    )
    history.loc[dates[-1], ["High", "Low"]] = [110.5, 107.0]

    setup = analysis.analyze_long_swing_setup(history)

    assert setup.state == "Price breakout · volume unconfirmed"
    assert setup.metrics["Base length sessions"] == 10
    assert setup.checks["Breakout above pivot"]
    assert not setup.checks["Breakout volume at least 1.5x"]


def test_position_plan_uses_risk_budget() -> None:
    plan = analysis.calculate_position_plan(100_000, 0.5, 13.24, 11.50)

    assert plan.shares == 287
    assert plan.risk_budget == 500
    assert plan.planned_loss <= plan.risk_budget


def test_position_plan_caps_shares_by_available_capital() -> None:
    plan = analysis.calculate_position_plan(1_000, 10, 100, 99)

    assert plan.risk_limited_shares == 100
    assert plan.capital_limited_shares == 10
    assert plan.shares == 10


def test_reward_risk_for_long_trade() -> None:
    assert analysis.calculate_reward_risk(100, 90, 125) == 2.5


def test_reward_risk_rejects_target_below_entry() -> None:
    with pytest.raises(ValueError, match="Target price must be above entry"):
        analysis.calculate_reward_risk(100, 90, 95)


def test_market_regime_reports_transparent_risk_on_checks() -> None:
    dates = pd.bdate_range("2025-01-01", periods=220)

    def history(start: float, end: float) -> pd.DataFrame:
        return pd.DataFrame(
            {
                "Close": np.linspace(start, end, len(dates)),
                "Volume": np.full(len(dates), 1_000_000),
            },
            index=dates,
        )

    regime = analysis.classify_market_regime(
        {
            "SPY": history(100, 140),
            "IWM": history(100, 160),
            "HYG": history(100, 130),
            "IEF": history(100, 105),
            "^VIX": history(30, 12),
        }
    )

    assert regime.label == "Risk-on"
    assert regime.score == 4
    assert all(regime.checks.values())


def test_market_risk_profiles_use_cached_history_only() -> None:
    dates = pd.bdate_range("2025-01-01", periods=60)
    close = np.linspace(100, 120, len(dates))
    histories = {
        "TEST": pd.DataFrame(
            {
                "High": close + 2,
                "Low": close - 2,
                "Close": close,
                "Volume": np.full(len(dates), 1_000_000),
            },
            index=dates,
        )
    }

    profiles = analysis.build_market_risk_profiles(histories)
    profile = profiles.iloc[0]

    assert profile["Symbol"] == "TEST"
    assert profile["Last price"] == pytest.approx(120)
    assert profile["ATR %"] > 0
    assert profile["Swing low"] > 0
    assert 0 <= profile["Market risk"] <= 100
    assert profile["Risk data %"] == 50