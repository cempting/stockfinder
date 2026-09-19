"""Validated, user-editable analysis configuration."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Any
from uuid import uuid4

from stockfinder.runtime import application_data_dir

DEFAULT_CONFIG_PATH = Path(__file__).with_name("default_analysis_config.json")
GEOGRAPHY_DIMENSIONS = ("listing_region", "company_domicile")
REQUIRED_MARKET_REGIMES = ("defensive", "neutral", "supportive")


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
            validate_analysis_config(config)
            return config
        except (OSError, json.JSONDecodeError, ValueError, TypeError):
            return default_analysis_config()

    def save(self, config: dict[str, Any]) -> dict[str, Any]:
        candidate = deepcopy(config)
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