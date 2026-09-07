import runpy
from pathlib import Path
from unittest.mock import patch

import pandas as pd

from stockfinder.app import main
from stockfinder.models import Score, SwingSetup
from stockfinder.ui import (
    _consume_pending_navigation,
    _enrich_with_cached_risk,
    _ensure_rotation_columns,
    _filter_fundamental_candidates,
    _filter_market_stocks,
    _filter_technical_candidates,
    _fundamental_evidence_frame,
    _fundamental_signal,
    _industry_proxy,
    _industry_proxy_thumbnail,
    _metal_summary,
    _raw_risk_limit,
    _raw_score_threshold,
    _safety_score_10,
    _score_10,
    _score_context,
    _selected_rotation_context,
    _setup_evidence_frame,
    _stock_discovery_frame,
    _volatility_context,
    _volume_signal,
)


def test_main_launches_streamlit_with_active_interpreter() -> None:
    with patch("stockfinder.app.subprocess.call", return_value=0) as call:
        assert main() == 0

    command = call.call_args.args[0]
    assert command[1:4] == ["-m", "streamlit", "run"]
    assert command[-1].endswith("stockfinder/ui.py")


def test_pending_navigation_is_centralized_and_validated() -> None:
    state = {
        "pending_workspace_page": "Stocks",
        "pending_stocks_workspace_view": "Research",
    }

    _consume_pending_navigation(state)

    assert state == {
        "workspace_page": "Stocks",
        "stocks_workspace_view": "Research",
    }


def test_invalid_pending_navigation_is_discarded() -> None:
    state = {"workspace_page": "Market pulse", "pending_workspace_page": "Typo"}

    _consume_pending_navigation(state)

    assert state == {"workspace_page": "Market pulse"}


def test_app_script_renders_streamlit_ui() -> None:
    app_path = Path(__file__).parents[1] / "src" / "stockfinder" / "app.py"

    with patch("stockfinder.ui.main") as ui_main:
        runpy.run_path(str(app_path), run_name="__main__")

    ui_main.assert_called_once_with()


def test_score_context_explains_threshold_distance_and_direction() -> None:
    assert _score_context(73) == "Score 7.3/10 · positive evidence."
    assert _score_context(73, risk=True) == "Safety 2.7/10 · elevated risk."
    assert _score_context(64) == "Score 6.4/10 · neutral evidence."


def test_score_display_uses_one_to_ten_and_inverts_risk() -> None:
    assert _score_10(0) == 1.0
    assert _score_10(100) == 10.0
    assert _safety_score_10(0) == 10.0
    assert _safety_score_10(100) == 1.0
    assert _score_10(_raw_score_threshold(7.0)) == 7.0
    assert _safety_score_10(_raw_risk_limit(7.0)) == 7.0


def test_fundamental_evidence_includes_raw_value_and_metric_thresholds() -> None:
    score = Score(
        value=66.7,
        label="Positive",
        components={"Revenue growth": 66.7},
        completeness=100.0,
    )

    evidence = _fundamental_evidence_frame({"revenueGrowth": 0.20}, score).iloc[0]

    assert evidence["Reported value"] == "+20.0%"
    assert evidence["Score"] == 6.7
    assert evidence["Threshold context"] == (
        "Neutral 10% · Positive 19% · Strong 26%+"
    )
    assert "Top-line expansion" in evidence["Why it matters"]


def test_setup_evidence_includes_observed_value_and_rule_threshold() -> None:
    setup = SwingSetup(
        state="Developing",
        score=50.0,
        checks={"Breakout volume at least 1.5x": False},
        metrics={"Breakout volume ratio": 1.2},
        pivot=100.0,
        suggested_entry=101.0,
        atr_stop=95.0,
        structural_stop=94.0,
    )

    evidence = _setup_evidence_frame(setup).iloc[0]

    assert evidence["Result"] == "Fail"
    assert evidence["Observed"] == "1.20x average"
    assert evidence["Threshold"] == "≥ 1.50x"
    assert "participation" in evidence["Why it matters"]


def test_volatility_context_explains_positioning_implication() -> None:
    assert _volatility_context(42) == (
        "Volatility: High at 42.0% annualized; wider stops and fewer shares may "
        "be needed."
    )
    assert _volatility_context(18, concise=True) == "Low (18.0% annualized)"


def test_metal_summary_does_not_treat_missing_benchmark_as_underperformance() -> None:
    summary = _metal_summary(
        pd.Series(
            {
                "Metal": "Gold",
                "Signal": "Positive",
                "Trend": 80,
                "Relative 3M %": float("nan"),
                "Participation": 70,
            }
        )
    )

    assert "benchmark data is missing" in summary
    assert "underperforming" not in summary


def test_fundamental_signal_uses_best_available_core_score() -> None:
    assert _fundamental_signal(pd.Series({"Quality": 82, "Growth": 40})) == "Strong"
    assert _fundamental_signal(pd.Series({"Quality": 60, "Growth": 65})) == "Positive"
    assert _fundamental_signal(pd.Series({"Quality": 64, "Growth": 30})) == "Weak"
    assert _fundamental_signal(pd.Series(dtype=float)) == "Unavailable"


def test_volume_signal_uses_breakout_confirmation_threshold() -> None:
    assert _volume_signal(1.49) == "Building"
    assert _volume_signal(1.5) == "Confirmed spike"
    assert _volume_signal(0.8) == "Unconfirmed"


def test_rotation_columns_are_added_for_hot_loaded_scan_schema() -> None:
    industries = pd.DataFrame(
        {
            "Return 1W %": [5.0, -5.0],
            "Return 1M %": [10.0, -10.0],
            "Return 3M %": [0.0, 20.0],
            "Return 6M %": [0.0, 30.0],
            "Liquidity 1W": [80.0, 20.0],
            "Liquidity 1M": [70.0, 30.0],
            "Liquidity 3M": [40.0, 60.0],
            "Liquidity 6M": [40.0, 60.0],
            "Flow 1W %": [10.0, -10.0],
            "Flow 1M %": [5.0, -5.0],
        }
    )

    enriched = _ensure_rotation_columns(industries)

    assert enriched["Rotation state"].tolist() == ["Gaining", "Losing"]
    assert enriched["Early rotation signal"].tolist() == [
        "Unavailable",
        "Unavailable",
    ]


def test_cached_risk_enrichment_does_not_require_complete_analysis(monkeypatch) -> None:
    profiles = pd.DataFrame(
        {
            "Symbol": ["AAPL"],
            "Last price": [250.0],
            "Market risk": [42.0],
            "Risk label": ["Moderate"],
            "ATR %": [2.1],
        }
    )
    monkeypatch.setattr("stockfinder.ui._cached_risk_profiles", lambda: profiles)

    enriched = _enrich_with_cached_risk(pd.DataFrame({"symbol": ["AAPL", "NEW"]}))

    assert enriched.loc[0, "last_price"] == 250
    assert enriched.loc[0, "market_risk"] == 42
    assert pd.isna(enriched.loc[1, "last_price"])


def test_adjustable_technical_candidate_filters() -> None:
    stocks = pd.DataFrame(
        {
            "Symbol": ["PASS", "VOLUME", "RISK"],
            "Setup state": ["Ready", "Ready", "Ready"],
            "Setup score": [80, 80, 80],
            "Breakout volume": [1.5, 0.9, 1.5],
            "Volatility %": [30, 30, 30],
            "Market risk": [40, 40, 70],
            "Base range %": [10, 10, 10],
            "From pivot %": [2, 2, 2],
            "Price above SMA50": [True, True, True],
            "Price above SMA150": [True, True, True],
            "Volume Evidence": [True, False, True],
            "Consolidation base": [True, True, True],
        }
    )

    filtered = _filter_technical_candidates(
        stocks,
        ("Ready",),
        65,
        1.0,
        50,
        60,
        15,
        5,
        True,
        True,
        True,
        True,
    )

    assert filtered["Symbol"].tolist() == ["PASS"]


def test_core_rule_filters_can_be_disabled_independently() -> None:
    stocks = pd.DataFrame(
        {
            "Symbol": ["PASS", "BELOW50"],
            "Setup state": ["Developing", "Developing"],
            "Setup score": [70, 70],
            "Breakout volume": [1.6, 1.6],
            "Volatility %": [30, 30],
            "Base range %": [10, 10],
            "From pivot %": [2, 2],
            "Price above SMA50": [True, False],
            "Price above SMA150": [True, True],
            "Volume Evidence": [True, True],
            "Consolidation base": [True, True],
        }
    )
    arguments = (("Developing",), 0, 0, 100, 100, 15, 5)

    enabled = _filter_technical_candidates(
        stocks, *arguments, True, True, True, True
    )
    disabled = _filter_technical_candidates(
        stocks, *arguments, False, True, True, True
    )

    assert enabled["Symbol"].tolist() == ["PASS"]
    assert disabled["Symbol"].tolist() == ["PASS", "BELOW50"]


def test_disabled_volume_and_base_rules_ignore_related_thresholds() -> None:
    stocks = pd.DataFrame(
        {
            "Symbol": ["LOOSE"],
            "Setup state": ["Developing"],
            "Setup score": [70],
            "Breakout volume": [0.4],
            "Volatility %": [30],
            "Base range %": [30],
            "From pivot %": [25],
            "Price above SMA50": [True],
            "Price above SMA150": [True],
            "Volume Evidence": [False],
            "Consolidation base": [False],
        }
    )

    filtered = _filter_technical_candidates(
        stocks,
        ("Developing",),
        0,
        1.5,
        100,
        100,
        15,
        5,
        True,
        True,
        False,
        False,
    )

    assert filtered["Symbol"].tolist() == ["LOOSE"]


def test_adjustable_fundamental_filter_supports_any_or_all() -> None:
    stocks = pd.DataFrame(
        {
            "Symbol": ["QUALITY", "BOTH", "WEAK"],
            "Quality": [80, 75, 40],
            "Growth": [40, 70, 50],
        }
    )

    any_match = _filter_fundamental_candidates(
        stocks, ("Quality", "Growth"), 65, require_all=False
    )
    all_match = _filter_fundamental_candidates(
        stocks, ("Quality", "Growth"), 65, require_all=True
    )

    assert any_match["Symbol"].tolist() == ["QUALITY", "BOTH"]
    assert all_match["Symbol"].tolist() == ["BOTH"]


def test_global_stock_filters_compose_market_risk_and_setup_rules() -> None:
    stocks = pd.DataFrame(
        {
            "Symbol": ["USPASS", "EUROPE", "RISKY"],
            "Company": ["US Pass", "Europe Pass", "US Risky"],
            "Region": ["United States", "Europe", "United States"],
            "Sector": ["Technology", "Technology", "Technology"],
            "Industry": ["Software", "Software", "Software"],
            "Exchange": ["NASDAQ", "Xetra", "NASDAQ"],
            "Setup state": ["Ready", "Ready", "Ready"],
            "Price": [100.0, 80.0, 120.0],
            "Market cap": [10e9, 8e9, 12e9],
            "Setup score": [80.0, 80.0, 80.0],
            "Market risk": [40.0, 40.0, 85.0],
            "Volatility %": [30.0, 30.0, 70.0],
            "Price above SMA50": [True, True, True],
            "Price above SMA150": [True, True, True],
        }
    )

    filtered = _filter_market_stocks(
        stocks,
        search="pass",
        regions=("United States",),
        sectors=("Technology",),
        setup_states=("Ready",),
        minimum_price=50,
        maximum_price=150,
        minimum_market_cap=5e9,
        minimum_setup=65,
        maximum_risk=60,
        maximum_volatility=50,
        require_sma50=True,
        require_sma150=True,
    )

    assert filtered["Symbol"].tolist() == ["USPASS"]


def test_stock_discovery_frame_joins_market_and_cached_risk_evidence() -> None:
    candidates = pd.DataFrame(
        {
            "Symbol": ["AAPL"],
            "Company": ["Apple"],
            "Price": [250.0],
        }
    )
    universe = pd.DataFrame(
        {
            "Symbol": ["AAPL"],
            "Market cap": [3e12],
            "Volume": [50e6],
            "Day %": [1.2],
        }
    )
    risk = pd.DataFrame(
        {
            "Symbol": ["AAPL"],
            "Market risk": [35.0],
            "Risk label": ["Moderate"],
            "ATR %": [2.1],
        }
    )

    result = _stock_discovery_frame(universe, candidates, risk).iloc[0]

    assert result["Market cap"] == 3e12
    assert result["Day %"] == 1.2
    assert result["Market risk"] == 35.0


def test_industry_proxy_prefers_industry_etf_then_sector_fallback() -> None:
    exact = pd.Series(
        {"Industry": "Semiconductors", "Sector": "Information Technology"}
    )
    fallback = pd.Series({"Industry": "Unknown energy", "Sector": "Energy"})

    assert _industry_proxy(exact) == ("SMH", "representative industry ETF")
    assert _industry_proxy(fallback) == ("XLE", "sector ETF fallback")


def test_industry_proxy_thumbnail_is_compact_and_selectable() -> None:
    dates = pd.bdate_range("2026-01-01", periods=80)
    history = pd.DataFrame(
        {"Close": range(100, 180), "Volume": [1_000_000] * 80}, index=dates
    )

    figure = _industry_proxy_thumbnail("SMH", "Semiconductors", history)

    assert len(figure.data) == 2
    assert figure.data[0].mode == "lines+markers"
    assert figure.data[0].marker.opacity == 0
    assert figure.layout.height == 230
    assert figure.layout.clickmode == "event+select"
    assert not figure.layout.showlegend


def test_rotation_context_preserves_listing_region() -> None:
    industries = pd.DataFrame(
        [{"Region": "Europe", "Sector": "Financials", "Industry": "Banks"}]
    )
    heatmap_event = {
        "selection": {
            "points": [{"customdata": ["Europe", "Financials", "Banks"]}]
        }
    }

    assert _selected_rotation_context(heatmap_event, {}, industries) == (
        "Europe",
        "Financials",
        "Banks",
    )
    assert _selected_rotation_context(
        {}, {"selection": {"rows": [0]}}, industries
    ) == ("Europe", "Financials", "Banks")
