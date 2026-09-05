"""Domain models shared by analysis and presentation layers."""

from dataclasses import dataclass


@dataclass(frozen=True)
class Score:
    """A transparent normalized score and its evidence."""

    value: float
    label: str
    components: dict[str, float]
    completeness: float


@dataclass(frozen=True)
class SecurityAnalysis:
    """Independent quality, risk, and technical assessments."""

    symbol: str
    quality: Score
    risk: Score
    technical: Score


@dataclass(frozen=True)
class SwingSetup:
    """Evidence and suggested levels for a long swing setup."""

    state: str
    score: float
    checks: dict[str, bool]
    metrics: dict[str, float]
    pivot: float
    suggested_entry: float
    atr_stop: float
    structural_stop: float


@dataclass(frozen=True)
class PositionPlan:
    """A position constrained by both risk budget and available capital."""

    shares: int
    risk_budget: float
    risk_per_share: float
    planned_loss: float
    position_value: float
    risk_limited_shares: int
    capital_limited_shares: int


@dataclass(frozen=True)
class MarketRegime:
    """Transparent cross-asset risk-appetite classification."""

    label: str
    score: int
    checks: dict[str, bool]
