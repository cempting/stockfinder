import pytest

from stockfinder.dsl import (
    DslValidationError,
    TruthValue,
    evaluate_condition,
    load_analysis_pack,
)


def test_analysis_pack_loads_and_validates_references() -> None:
    document = load_analysis_pack(
        """
dsl: stockfinder/v1
kind: analysis_pack
id: test_pack
name: Test pack
version: 1.0.0
definitions:
  - id: market.vix
signals:
  - id: vix_stress
    when: {gte: [{metric: market.vix}, 25]}
policies:
  - id: risk_controls
    unavailable: {new_entry_policy: no_new_entries}
"""
    )

    assert document["id"] == "test_pack"


@pytest.mark.parametrize(
    ("fragment", "message"),
    [
        ("signals:\n  - id: duplicate\n  - id: duplicate", "Duplicate IDs"),
        (
            "signals:\n  - id: broken\n    when: {gt: [{metric: missing}, 1]}",
            "unresolved metric",
        ),
        (
            "policies:\n  - id: unsafe_policy",
            "requires conservative unavailable",
        ),
    ],
)
def test_analysis_pack_rejects_semantic_errors(fragment: str, message: str) -> None:
    text = f"""
dsl: stockfinder/v1
kind: analysis_pack
id: test_pack
name: Test pack
version: 1.0.0
{fragment}
"""

    with pytest.raises(DslValidationError, match=message):
        load_analysis_pack(text)


def test_condition_evaluator_uses_three_valued_logic() -> None:
    stress = {"gte": [{"metric": "market.vix"}, 25]}

    assert evaluate_condition(stress, metrics={"market.vix": 30}) == TruthValue.TRUE
    assert evaluate_condition(stress, metrics={}) == TruthValue.UNKNOWN
    assert evaluate_condition(
        {"all": [stress, {"signal": "credit_supportive"}]},
        metrics={"market.vix": 30},
        signals={"credit_supportive": None},
    ) == TruthValue.UNKNOWN
    assert evaluate_condition(
        {"any": [stress, {"signal": "credit_supportive"}]},
        metrics={"market.vix": 20},
        signals={"credit_supportive": False},
    ) == TruthValue.FALSE
    assert evaluate_condition(
        {
            "at_least": {
                "count": 2,
                "conditions": [stress, True, {"signal": "credit_supportive"}],
            }
        },
        metrics={"market.vix": 30},
    ) == TruthValue.TRUE