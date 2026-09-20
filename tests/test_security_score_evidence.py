from stockfinder.models import Score
from stockfinder.widgets.security_score_evidence import score_evidence_frame


def test_score_evidence_frame_preserves_positive_components() -> None:
    score = Score(70.0, "Positive", {"Growth": 80.0, "Value": 60.0}, 50.0)

    evidence = score_evidence_frame(score).set_index("Evidence")

    assert evidence.loc["Growth", "Score"] == 80.0
    assert evidence.loc["Value", "Score"] == 60.0


def test_score_evidence_frame_inverts_risk_into_safety() -> None:
    score = Score(30.0, "Low", {"Volatility": 20.0, "Drawdown": 70.0}, 100.0)

    evidence = score_evidence_frame(score, invert=True).set_index("Evidence")

    assert evidence.loc["Volatility", "Score"] == 80.0
    assert evidence.loc["Drawdown", "Score"] == 30.0


def test_score_evidence_frame_handles_missing_components() -> None:
    evidence = score_evidence_frame(Score(0.0, "Unavailable", {}, 0.0))

    assert evidence.empty
    assert evidence.columns.tolist() == ["Evidence", "Score"]