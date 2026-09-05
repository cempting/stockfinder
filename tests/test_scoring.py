import pandas as pd

from stockfinder.scoring import score_fundamentals, score_risk, score_technicals


def test_fundamental_score_excludes_missing_values() -> None:
    score = score_fundamentals({"Growth": 80.0, "Profitability": 60.0, "Debt": None})

    assert score.value == 70.0
    assert score.label == "Positive"
    assert score.completeness == 66.7


def test_risk_score_treats_missing_dataset_as_high_risk() -> None:
    score = score_risk({"Volatility": None, "Drawdown": None})

    assert score.value == 100.0
    assert score.label == "High"
    assert score.completeness == 0.0


def test_technical_score_recognizes_constructive_history() -> None:
    prices = [100 + index * 0.5 for index in range(180)]
    history = pd.DataFrame(
        {"Close": prices, "Volume": [1_000_000] * 179 + [1_500_000]}
    )

    score = score_technicals(history)

    assert score.value >= 80
    assert score.label == "Strong"
    assert score.completeness == 100.0