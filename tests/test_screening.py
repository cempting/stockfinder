import pandas as pd

from stockfinder.screening import evaluate_stock_rules, screen_ranked_stocks


def _candidates() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Symbol": ["PASS", "UNTRADABLE", "OTHER", "RISKY"],
            "Region": ["Europe", "Europe", "Europe", "Europe"],
            "Sector": ["Industrials", "Industrials", "Technology", "Industrials"],
            "Industry": ["Machinery", "Machinery", "Software", "Machinery"],
            "Setup score": [85.0, 75.0, 95.0, 90.0],
            "Volatility %": [30.0, 35.0, 20.0, 30.0],
            "Market risk": [25.0, 30.0, 10.0, 70.0],
            "Price above SMA150": [True, True, True, True],
            "Distance to SMA50 %": [2.0, 1.0, 3.0, 2.0],
            "Base sessions": [10, 12, 15, 8],
            "SMA50 slope 20D %": [2.0, 1.0, 3.0, 2.5],
            "Volume trend ratio": [1.4, 1.2, 1.5, 1.3],
        }
    )


def test_screen_ranked_stocks_applies_context_profile_and_broker_list() -> None:
    profile = {
        "minimum_setup_score": 70,
        "maximum_volatility_pct": 50,
        "minimum_safety_score": 40,
        "require_above_sma150": True,
    }

    result = screen_ranked_stocks(
        _candidates(),
        region="Europe",
        sector="Industrials",
        industry="Machinery",
        profile=profile,
        broker_symbols={"PASS"},
        broker_only=True,
    )

    assert result["Symbol"].tolist() == ["PASS"]
    assert result["Broker availability"].tolist() == ["Available"]


def test_screen_ranked_stocks_marks_unverified_without_broker_list() -> None:
    result = screen_ranked_stocks(
        _candidates(),
        region="Europe",
        sector="Industrials",
        industry="Machinery",
        profile={},
    )

    assert result["Symbol"].tolist() == ["RISKY", "PASS", "UNTRADABLE"]
    assert set(result["Broker availability"]) == {"Not verified"}


def test_screen_ranked_stocks_applies_fundamental_threshold_when_available() -> None:
    candidates = _candidates()
    candidates["Quality"] = [80.0, 60.0, 90.0, 85.0]

    result = screen_ranked_stocks(
        candidates,
        region="Europe",
        sector="Industrials",
        industry="Machinery",
        profile={"minimum_fundamental_score": 70},
    )

    assert result["Symbol"].tolist() == ["RISKY", "PASS"]


def test_evaluate_stock_rules_explains_each_exclusion() -> None:
    candidates = _candidates()
    candidates["Quality"] = [80.0, 60.0, 90.0, 85.0]
    candidates["Price above SMA150"] = candidates["Price above SMA150"].astype(
        "boolean"
    )
    candidates.loc[candidates["Symbol"] == "OTHER", "Price above SMA150"] = pd.NA
    result = evaluate_stock_rules(
        candidates,
        {
            "minimum_setup_score": 80,
            "maximum_volatility_pct": 32,
            "minimum_safety_score": 40,
            "minimum_fundamental_score": 70,
            "require_above_sma150": True,
        },
        broker_symbols={"PASS", "RISKY"},
        broker_only=True,
    ).set_index("Symbol")

    assert result.loc["PASS", "Profile result"] == "Pass"
    assert "Setup < 80" in result.loc["UNTRADABLE", "Rule failures"]
    assert "Volatility > 32%" in result.loc["UNTRADABLE", "Rule failures"]
    assert "Quality < 70" in result.loc["UNTRADABLE", "Rule failures"]
    assert "Broker unavailable" in result.loc["UNTRADABLE", "Rule failures"]
    assert result.loc["RISKY", "Rule failures"] == "Safety < 40"
    assert "Below SMA150" in result.loc["OTHER", "Rule failures"]


def test_weighted_profile_score_is_optional_and_reports_completeness() -> None:
    candidates = _candidates().iloc[[0, 1]].copy()
    candidates["Quality"] = [80.0, pd.NA]
    profile = {
        "weighted_score_enabled": True,
        "minimum_weighted_score": 81,
        "setup_weight": 40,
        "safety_weight": 20,
        "fundamental_weight": 20,
        "trend_weight": 20,
    }

    result = evaluate_stock_rules(candidates, profile).set_index("Symbol")

    assert result.loc["PASS", "Weighted score"] == 85.0
    assert result.loc["PASS", "Weighted data %"] == 100.0
    assert result.loc["UNTRADABLE", "Weighted data %"] == 80.0
    assert result.loc["PASS", "Profile result"] == "Pass"
    assert "Weighted score < 81" in result.loc["UNTRADABLE", "Rule failures"]

    candidates.loc[candidates["Symbol"] == "PASS", "Price above SMA150"] = False
    failed_trend = evaluate_stock_rules(candidates, profile).set_index("Symbol")
    assert failed_trend.loc["PASS", "Weighted data %"] == 100.0
    assert failed_trend.loc["PASS", "Weighted score"] == 65.0