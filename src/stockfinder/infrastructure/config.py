"""Validated, user-editable analysis configuration."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from stockfinder.infrastructure.runtime import application_data_dir

DEFAULT_CONFIG_PATH = Path(__file__).with_name("default_analysis_config.json")
GEOGRAPHY_DIMENSIONS = ("listing_region", "company_domicile")
REQUIRED_MARKET_REGIMES = ("defensive", "neutral", "supportive")
CAPITAL_MOVEMENT_PRESETS = {
    "Daily": 1,
    "Weekly": 5,
    "Monthly": 21,
}
DEFAULT_CAPITAL_MOVEMENT = {
    "period": "Daily",
    "custom_sessions": 1,
}
DEFAULT_ALERT_RULES = {
    "max_position_allocation_pct": 25.0,
    "minimum_position_safety": 40.0,
    "position_loss_pct": 10.0,
    "watchlist_entry_tolerance_pct": 2.0,
}
DEFAULT_PROFILE_COMPOSITION = {
    "weighted_score_enabled": False,
    "minimum_weighted_score": 60.0,
    "setup_weight": 40.0,
    "safety_weight": 25.0,
    "fundamental_weight": 20.0,
    "trend_weight": 15.0,
    "setup_match_mode": "any",
    "enabled_setup_filters": [
        "heartbeat_consolidation",
        "sma50_cross",
        "rising_sma50",
        "increasing_volume",
        "above_sma150",
    ],
}
SETUP_FILTERS = {
    "heartbeat_consolidation": "Heartbeat consolidation",
    "sma50_cross": "Recent SMA50 cross",
    "rising_sma50": "Rising SMA50",
    "increasing_volume": "Increasing volume",
    "above_sma150": "Above SMA150",
}
PROFILE_COMPOSITION_PRESETS = {
    "Momentum-led": {
        "minimum_weighted_score": 65.0,
        "setup_weight": 50.0,
        "safety_weight": 15.0,
        "fundamental_weight": 10.0,
        "trend_weight": 25.0,
    },
    "Balanced": {
        "minimum_weighted_score": 65.0,
        "setup_weight": 35.0,
        "safety_weight": 25.0,
        "fundamental_weight": 25.0,
        "trend_weight": 15.0,
    },
    "Quality-first": {
        "minimum_weighted_score": 70.0,
        "setup_weight": 20.0,
        "safety_weight": 25.0,
        "fundamental_weight": 40.0,
        "trend_weight": 15.0,
    },
}


def default_analysis_config() -> dict[str, Any]:
    """Load a fresh copy of the packaged default configuration."""
    return json.loads(DEFAULT_CONFIG_PATH.read_text(encoding="utf-8"))


def validate_analysis_config(config: dict[str, Any]) -> None:
    """Raise ValueError when required configuration semantics are invalid."""
    if config.get("version") != 1:
        raise ValueError("Analysis configuration version must be 1")
    if config.get("geography_dimension") not in GEOGRAPHY_DIMENSIONS:
        raise ValueError(
            "geography_dimension must be listing_region or company_domicile"
        )

    movement = configured_capital_movement(config)
    valid_periods = (*CAPITAL_MOVEMENT_PRESETS, "Custom")
    if movement["period"] not in valid_periods:
        raise ValueError(
            "capital_movement.period must be Daily, Weekly, Monthly, or Custom"
        )
    custom_sessions = movement["custom_sessions"]
    if (
        not isinstance(custom_sessions, int)
        or isinstance(custom_sessions, bool)
        or not 1 <= custom_sessions <= 252
    ):
        raise ValueError(
            "capital_movement.custom_sessions must be an integer between 1 and 252"
        )

    controls = config.get("market_controls")
    if not isinstance(controls, dict):
        raise ValueError("market_controls must be an object")
    for regime in REQUIRED_MARKET_REGIMES:
        control = controls.get(regime)
        if not isinstance(control, dict):
            raise ValueError(f"market_controls.{regime} must be an object")
        for field in ("max_gross_exposure_pct", "risk_per_position_pct"):
            value = control.get(field)
            if not isinstance(value, (int, float)) or not 0 <= value <= 100:
                raise ValueError(
                    f"market_controls.{regime}.{field} must be between 0 and 100"
                )
        if not str(control.get("new_entry_policy", "")).strip():
            raise ValueError(
                f"market_controls.{regime}.new_entry_policy must not be empty"
            )

    profiles = config.get("rule_profiles")
    if not isinstance(profiles, dict) or not profiles:
        raise ValueError("rule_profiles must contain at least one profile")
    for name, profile in profiles.items():
        if not isinstance(profile, dict):
            raise ValueError(f"rule_profiles.{name} must be an object")
        for field in (
            "minimum_setup_score",
            "maximum_volatility_pct",
            "minimum_safety_score",
            "minimum_fundamental_score",
        ):
            value = profile.get(field)
            if not isinstance(value, (int, float)) or not 0 <= value <= 100:
                raise ValueError(
                    f"rule_profiles.{name}.{field} must be between 0 and 100"
                )
        composition = configured_rule_profile(profile)
        if not isinstance(composition["weighted_score_enabled"], bool):
            raise ValueError(
                f"rule_profiles.{name}.weighted_score_enabled must be boolean"
            )
        if composition["setup_match_mode"] not in {"any", "all"}:
            raise ValueError(
                f"rule_profiles.{name}.setup_match_mode must be any or all"
            )
        enabled_filters = composition["enabled_setup_filters"]
        if (
            not isinstance(enabled_filters, list)
            or not enabled_filters
            or any(filter_id not in SETUP_FILTERS for filter_id in enabled_filters)
            or len(enabled_filters) != len(set(enabled_filters))
        ):
            raise ValueError(
                f"rule_profiles.{name}.enabled_setup_filters must contain "
                "unique known setup filters"
            )
        for field in (
            "minimum_weighted_score",
            "setup_weight",
            "safety_weight",
            "fundamental_weight",
            "trend_weight",
        ):
            value = composition[field]
            if not isinstance(value, (int, float)) or not 0 <= value <= 100:
                raise ValueError(
                    f"rule_profiles.{name}.{field} must be between 0 and 100"
                )
        if not any(
            composition[field] > 0
            for field in (
                "setup_weight",
                "safety_weight",
                "fundamental_weight",
                "trend_weight",
            )
        ):
            raise ValueError(f"rule_profiles.{name} needs at least one positive weight")

    alert_rules = config.get("alert_rules", DEFAULT_ALERT_RULES)
    if not isinstance(alert_rules, dict):
        raise ValueError("alert_rules must be an object")
    for field in DEFAULT_ALERT_RULES:
        value = alert_rules.get(field)
        if not isinstance(value, (int, float)) or not 0 <= value <= 100:
            raise ValueError(f"alert_rules.{field} must be between 0 and 100")

    proxies = config.get("regional_proxies")
    if not isinstance(proxies, dict) or not proxies:
        raise ValueError("regional_proxies must contain at least one region")
    for region, mapping in proxies.items():
        if not isinstance(mapping, dict) or not str(mapping.get("benchmark", "")):
            raise ValueError(
                f"regional_proxies.{region}.benchmark must be a ticker symbol"
            )
        if not isinstance(mapping.get("sectors", {}), dict):
            raise ValueError(f"regional_proxies.{region}.sectors must be an object")
        if not isinstance(mapping.get("industries", {}), dict):
            raise ValueError(
                f"regional_proxies.{region}.industries must be an object"
            )


class AnalysisConfigStore:
    """Persist user configuration while retaining packaged defaults."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = (
            Path(path)
            if path is not None
            else application_data_dir() / "analysis_config.json"
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return default_analysis_config()
        try:
            config = json.loads(self.path.read_text(encoding="utf-8"))
            config.setdefault("capital_movement", deepcopy(DEFAULT_CAPITAL_MOVEMENT))
            validate_analysis_config(config)
            return config
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            return default_analysis_config()

    def save(self, config: dict[str, Any]) -> dict[str, Any]:
        candidate = deepcopy(config)
        candidate.setdefault(
            "capital_movement", deepcopy(DEFAULT_CAPITAL_MOVEMENT)
        )
        validate_analysis_config(candidate)
        temporary = self.path.with_name(f".{self.path.name}.{uuid4().hex}.tmp")
        try:
            temporary.write_text(
                json.dumps(candidate, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
            temporary.replace(self.path)
        finally:
            if temporary.exists():
                temporary.unlink()
        return candidate

    def reset(self) -> dict[str, Any]:
        config = default_analysis_config()
        self.save(config)
        return config


def geography_column(config: dict[str, Any]) -> str:
    """Return the universe column controlled by the selected geography mode."""
    return (
        "Country"
        if config.get("geography_dimension") == "company_domicile"
        else "Region"
    )


def configured_capital_movement(config: dict[str, Any]) -> dict[str, Any]:
    """Return capital-movement settings with defaults for legacy configs."""
    configured = config.get("capital_movement", {})
    if not isinstance(configured, dict):
        raise ValueError("capital_movement must be an object")
    return {**DEFAULT_CAPITAL_MOVEMENT, **configured}


def capital_movement_sessions(config: dict[str, Any]) -> int:
    """Resolve the configured movement period to completed trading sessions."""
    movement = configured_capital_movement(config)
    if movement["period"] == "Custom":
        return int(movement["custom_sessions"])
    return CAPITAL_MOVEMENT_PRESETS[str(movement["period"])]


def update_capital_movement(
    config: dict[str, Any], period: str, custom_sessions: int
) -> dict[str, Any]:
    """Return validated capital-movement settings without mutating the source."""
    candidate = deepcopy(config)
    candidate["capital_movement"] = {
        "period": period,
        "custom_sessions": custom_sessions,
    }
    validate_analysis_config(candidate)
    return candidate


def update_rule_profile(
    config: dict[str, Any],
    profile_name: str,
    values: dict[str, Any],
) -> dict[str, Any]:
    """Return a validated configuration with one rule profile updated."""
    candidate = deepcopy(config)
    if profile_name not in candidate.get("rule_profiles", {}):
        raise ValueError(f"Unknown rule profile: {profile_name}")
    candidate["rule_profiles"][profile_name].update(values)
    validate_analysis_config(candidate)
    return candidate


def configured_rule_profile(profile: dict[str, Any]) -> dict[str, Any]:
    """Return a profile with defaults for optional weighted composition fields."""
    return {**DEFAULT_PROFILE_COMPOSITION, **profile}


def apply_profile_composition_preset(
    config: dict[str, Any],
    profile_name: str,
    preset_name: str,
) -> dict[str, Any]:
    """Enable and apply one validated weighted-composition preset."""
    if preset_name not in PROFILE_COMPOSITION_PRESETS:
        raise ValueError(f"Unknown composition preset: {preset_name}")
    return update_rule_profile(
        config,
        profile_name,
        {
            "weighted_score_enabled": True,
            **PROFILE_COMPOSITION_PRESETS[preset_name],
        },
    )


def configured_alert_rules(config: dict[str, Any]) -> dict[str, float]:
    """Return alert rules with defaults for configurations saved before alerts."""
    configured = config.get("alert_rules", {})
    return {
        field: float(configured.get(field, default))
        for field, default in DEFAULT_ALERT_RULES.items()
    }


def update_alert_rules(
    config: dict[str, Any], values: dict[str, float]
) -> dict[str, Any]:
    """Return a validated configuration with alert thresholds updated."""
    candidate = deepcopy(config)
    candidate["alert_rules"] = configured_alert_rules(candidate)
    candidate["alert_rules"].update(values)
    validate_analysis_config(candidate)
    return candidate


def configured_proxy(
    config: dict[str, Any], region: str, sector: str, industry: str
) -> tuple[str, str]:
    """Resolve the most specific configured regional analysis proxy."""
    regions = config["regional_proxies"]
    mapping = regions.get(region) or regions.get("Global") or {}
    industry_symbol = mapping.get("industries", {}).get(industry)
    if industry_symbol:
        return str(industry_symbol), "regional industry proxy"
    sector_symbol = mapping.get("sectors", {}).get(sector)
    if sector_symbol:
        return str(sector_symbol), "regional sector proxy"
    return str(mapping.get("benchmark", "ACWI")), "regional benchmark fallback"