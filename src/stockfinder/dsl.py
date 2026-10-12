"""Validated loading and restricted evaluation for Stockfinder analysis DSL."""

import json
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path
from typing import Any

import yaml
from jsonschema import Draft202012Validator

SCHEMA_PATH = Path(__file__).with_name("stockfinder-v1.schema.json")
COLLECTIONS = ("definitions", "signals", "regimes", "policies")


class DslValidationError(ValueError):
    """Raised when an analysis pack violates schema or semantic constraints."""


class TruthValue(StrEnum):
    TRUE = "true"
    FALSE = "false"
    UNKNOWN = "unknown"


def load_analysis_pack(text: str) -> dict[str, Any]:
    """Parse and validate one YAML Stockfinder analysis pack."""
    try:
        document = yaml.safe_load(text)
    except yaml.YAMLError as error:
        raise DslValidationError(f"Invalid YAML: {error}") from error
    if not isinstance(document, dict):
        raise DslValidationError("Analysis pack must be a YAML object")
    validate_analysis_pack(document)
    return document


def validate_analysis_pack(document: Mapping[str, Any]) -> None:
    """Validate schema shape and cross-node semantic invariants."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    errors = sorted(
        Draft202012Validator(schema).iter_errors(document),
        key=lambda error: tuple(str(item) for item in error.path),
    )
    if errors:
        error = errors[0]
        path = ".".join(str(item) for item in error.path) or "document"
        raise DslValidationError(f"{path}: {error.message}")

    nodes = [
        node
        for collection in COLLECTIONS
        for node in document.get(collection, [])
    ]
    ids = [str(node["id"]) for node in nodes]
    duplicates = sorted({node_id for node_id in ids if ids.count(node_id) > 1})
    if duplicates:
        raise DslValidationError(f"Duplicate IDs: {', '.join(duplicates)}")

    known_ids = set(ids)
    for node in nodes:
        _validate_references(node, known_ids, str(node["id"]))
        score = node.get("score")
        if isinstance(score, dict) and isinstance(score.get("components"), list):
            weights = [component.get("weight") for component in score["components"]]
            if any(
                not isinstance(weight, (int, float)) or weight < 0
                for weight in weights
            ):
                raise DslValidationError(
                    f"{node['id']}: score weights must be nonnegative"
                )
            if abs(sum(weights) - 100) > 1e-9:
                raise DslValidationError(f"{node['id']}: score weights must sum to 100")
        if node in document.get("policies", []) and "unavailable" not in node:
            raise DslValidationError(
                f"{node['id']}: policy requires conservative unavailable controls"
            )


def _validate_references(value: Any, known_ids: set[str], owner: str) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"metric", "signal", "score", "regime"}:
                if not isinstance(child, str) or child not in known_ids:
                    raise DslValidationError(
                        f"{owner}: unresolved {key} reference {child!r}"
                    )
            else:
                _validate_references(child, known_ids, owner)
    elif isinstance(value, list):
        for child in value:
            _validate_references(child, known_ids, owner)


def evaluate_condition(
    expression: Any,
    *,
    metrics: Mapping[str, Any] | None = None,
    signals: Mapping[str, TruthValue | bool | None] | None = None,
) -> TruthValue:
    """Evaluate a restricted condition using conservative three-valued logic."""
    metric_values = metrics or {}
    signal_values = signals or {}
    if isinstance(expression, bool):
        return TruthValue.TRUE if expression else TruthValue.FALSE
    if not isinstance(expression, dict) or len(expression) != 1:
        raise DslValidationError("Condition must contain exactly one operator")
    operator, arguments = next(iter(expression.items()))
    if operator in {"gt", "gte", "lt", "lte", "eq"}:
        if not isinstance(arguments, list) or len(arguments) != 2:
            raise DslValidationError(f"{operator} requires two arguments")
        left = _resolve_value(arguments[0], metric_values)
        right = _resolve_value(arguments[1], metric_values)
        if left is None or right is None:
            return TruthValue.UNKNOWN
        comparisons = {
            "gt": left > right,
            "gte": left >= right,
            "lt": left < right,
            "lte": left <= right,
            "eq": left == right,
        }
        return TruthValue.TRUE if comparisons[operator] else TruthValue.FALSE
    if operator == "signal":
        signal_id = arguments if isinstance(arguments, str) else arguments.get("id")
        return _truth(signal_values.get(signal_id))
    if operator == "not":
        value = evaluate_condition(
            arguments, metrics=metric_values, signals=signal_values
        )
        return {
            TruthValue.TRUE: TruthValue.FALSE,
            TruthValue.FALSE: TruthValue.TRUE,
            TruthValue.UNKNOWN: TruthValue.UNKNOWN,
        }[value]
    if operator in {"all", "any"}:
        if not isinstance(arguments, list) or not arguments:
            raise DslValidationError(f"{operator} requires a nonempty list")
        values = [
            evaluate_condition(item, metrics=metric_values, signals=signal_values)
            for item in arguments
        ]
        return _all(values) if operator == "all" else _any(values)
    if operator == "at_least":
        if not isinstance(arguments, dict):
            raise DslValidationError("at_least requires count and conditions")
        count = arguments.get("count")
        conditions = arguments.get("conditions")
        if not isinstance(count, int) or not isinstance(conditions, list):
            raise DslValidationError("at_least requires integer count and conditions")
        values = [
            evaluate_condition(item, metrics=metric_values, signals=signal_values)
            for item in conditions
        ]
        true_count = values.count(TruthValue.TRUE)
        unknown_count = values.count(TruthValue.UNKNOWN)
        if true_count >= count:
            return TruthValue.TRUE
        if true_count + unknown_count < count:
            return TruthValue.FALSE
        return TruthValue.UNKNOWN
    raise DslValidationError(f"Unsupported condition operator: {operator}")


def _resolve_value(value: Any, metrics: Mapping[str, Any]) -> Any:
    if isinstance(value, dict) and set(value) == {"metric"}:
        return metrics.get(value["metric"])
    if isinstance(value, (int, float, str)) and not isinstance(value, bool):
        return value
    raise DslValidationError(f"Unsupported comparison value: {value!r}")


def _truth(value: TruthValue | bool | None) -> TruthValue:
    if isinstance(value, TruthValue):
        return value
    if value is True:
        return TruthValue.TRUE
    if value is False:
        return TruthValue.FALSE
    return TruthValue.UNKNOWN


def _all(values: list[TruthValue]) -> TruthValue:
    if TruthValue.FALSE in values:
        return TruthValue.FALSE
    if TruthValue.UNKNOWN in values:
        return TruthValue.UNKNOWN
    return TruthValue.TRUE


def _any(values: list[TruthValue]) -> TruthValue:
    if TruthValue.TRUE in values:
        return TruthValue.TRUE
    if TruthValue.UNKNOWN in values:
        return TruthValue.UNKNOWN
    return TruthValue.FALSE