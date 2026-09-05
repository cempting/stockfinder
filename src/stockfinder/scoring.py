"""Transparent scoring functions for stock analysis."""

from collections.abc import Mapping
from math import isfinite

import pandas as pd

from stockfinder.models import Score


def _clamp(value: float) -> float:
    return round(max(0.0, min(100.0, value)), 1)


def _label(value: float, positive: bool = True) -> str:
    boundaries = (
        ((80, "Strong"), (65, "Positive"), (45, "Neutral"), (0, "Weak"))
        if positive
        else ((80, "High"), (60, "Elevated"), (35, "Moderate"), (0, "Low"))
    )
    return next(label for minimum, label in boundaries if value >= minimum)


def _available(values: Mapping[str, float | None]) -> dict[str, float]:
    return {
        name: float(value)
        for name, value in values.items()
        if value is not None and isfinite(float(value))
    }


def score_fundamentals(metrics: Mapping[str, float | None]) -> Score:
    """Score normalized fundamental metrics without inventing missing values."""
    components = _available(metrics)
    value = _clamp(sum(components.values()) / len(components)) if components else 0.0
    completeness = round(100 * len(components) / max(1, len(metrics)), 1)
    return Score(value, _label(value), components, completeness)


def score_risk(metrics: Mapping[str, float | None]) -> Score:
    """Score risk where a higher number means greater observed risk."""
    components = _available(metrics)
    value = _clamp(sum(components.values()) / len(components)) if components else 100.0
    completeness = round(100 * len(components) / max(1, len(metrics)), 1)
    return Score(value, _label(value, positive=False), components, completeness)


def score_technicals(history: pd.DataFrame) -> Score:
    """Score trend, relative volume, and price structure from daily history."""
    if history.empty or len(history) < 50:
        return Score(0.0, "Insufficient data", {}, 0.0)

    close = history["Close"].dropna()
    volume = history["Volume"].dropna()
    if len(close) < 50 or volume.empty:
        return Score(0.0, "Insufficient data", {}, 0.0)

    sma50 = close.rolling(50).mean()
    sma150 = close.rolling(150).mean()
    latest = float(close.iloc[-1])
    components: dict[str, float] = {
        "Above 50-day average": 100.0 if latest > sma50.iloc[-1] else 20.0,
        "50-day trend": 100.0 if sma50.iloc[-1] > sma50.iloc[-10] else 25.0,
    }
    if len(close) >= 150 and pd.notna(sma150.iloc[-1]):
        components["Above 150-day average"] = (
            100.0 if latest > sma150.iloc[-1] else 20.0
        )
        components["150-day trend"] = (
            100.0 if sma150.iloc[-1] > sma150.iloc[-10] else 25.0
        )

    recent = close.tail(40)
    first_half = recent.head(20)
    second_half = recent.tail(20)
    components["Heartbeat structure"] = (
        100.0
        if second_half.max() > first_half.max() and second_half.min() > first_half.min()
        else 35.0
    )

    average_volume = volume.tail(20).mean()
    components["Volume participation"] = _clamp(
        50.0 * float(volume.iloc[-1]) / average_volume
    )

    value = _clamp(sum(components.values()) / len(components))
    completeness = round(100 * len(components) / 6, 1)
    return Score(value, _label(value), components, completeness)
