import json

import pytest

from stockfinder.infrastructure.config import (
    AnalysisConfigStore,
    apply_profile_composition_preset,
    configured_alert_rules,
    configured_proxy,
    configured_rule_profile,
    default_analysis_config,
    geography_column,
    update_alert_rules,
    update_rule_profile,
)


def test_default_config_supports_both_geography_dimensions() -> None:
    config = default_analysis_config()

    assert geography_column(config) == "Region"
    config["geography_dimension"] = "company_domicile"
    assert geography_column(config) == "Country"


def test_config_store_round_trip_and_invalid_fallback(tmp_path) -> None:
    store = AnalysisConfigStore(tmp_path / "analysis.json")
    config = store.load()
    config["rule_profiles"]["Swing"]["minimum_setup_score"] = 77

    store.save(config)
    assert store.load()["rule_profiles"]["Swing"]["minimum_setup_score"] == 77

    store.path.write_text("{invalid", encoding="utf-8")
    assert store.load() == default_analysis_config()


def test_config_store_rejects_out_of_range_threshold(tmp_path) -> None:
    store = AnalysisConfigStore(tmp_path / "analysis.json")
    config = store.load()
    config["rule_profiles"]["Swing"]["minimum_setup_score"] = 101

    with pytest.raises(ValueError, match="between 0 and 100"):
        store.save(config)


def test_rule_profile_update_is_validated_without_mutating_source() -> None:
    config = default_analysis_config()

    updated = update_rule_profile(
        config,
        "Swing",
        {"minimum_setup_score": 82, "require_above_sma150": True},
    )

    assert updated["rule_profiles"]["Swing"]["minimum_setup_score"] == 82
    assert updated["rule_profiles"]["Swing"]["require_above_sma150"] is True
    assert config["rule_profiles"]["Swing"]["minimum_setup_score"] != 82
    with pytest.raises(ValueError, match="between 0 and 100"):
        update_rule_profile(config, "Swing", {"minimum_setup_score": 101})


def test_weighted_profile_defaults_preserve_legacy_configuration() -> None:
    profile = {"minimum_setup_score": 70}

    configured = configured_rule_profile(profile)

    assert configured["weighted_score_enabled"] is False
    assert configured["setup_weight"] == 40.0
    assert "weighted_score_enabled" not in profile


def test_profile_composition_preset_is_validated_without_mutation() -> None:
    config = default_analysis_config()

    updated = apply_profile_composition_preset(config, "Swing", "Quality-first")

    profile = updated["rule_profiles"]["Swing"]
    assert profile["weighted_score_enabled"] is True
    assert profile["fundamental_weight"] == 40.0
    assert config["rule_profiles"]["Swing"]["fundamental_weight"] == 15
    with pytest.raises(ValueError, match="Unknown composition preset"):
        apply_profile_composition_preset(config, "Swing", "Unknown")


def test_alert_rules_are_backward_compatible_and_validated() -> None:
    config = default_analysis_config()
    config.pop("alert_rules")

    assert configured_alert_rules(config)["position_loss_pct"] == 10.0

    updated = update_alert_rules(config, {"position_loss_pct": 8.0})
    assert updated["alert_rules"]["position_loss_pct"] == 8.0
    assert "alert_rules" not in config

    with pytest.raises(ValueError, match="position_loss_pct"):
        update_alert_rules(config, {"position_loss_pct": 101.0})


def test_configured_proxy_prefers_industry_then_sector_then_region() -> None:
    config = default_analysis_config()

    assert configured_proxy(
        config, "United States", "Information Technology", "Semiconductors"
    ) == ("SMH", "regional industry proxy")
    assert configured_proxy(
        config, "United States", "Information Technology", "Unknown"
    ) == ("XLK", "regional sector proxy")
    assert configured_proxy(config, "Europe", "Industrials", "Machinery") == (
        "VGK",
        "regional benchmark fallback",
    )


def test_packaged_default_is_valid_json() -> None:
    serialized = json.dumps(default_analysis_config())
    assert json.loads(serialized)["version"] == 1