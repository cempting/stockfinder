import json

import pytest

from stockfinder.infrastructure.config import (
    AnalysisConfigStore,
    apply_profile_composition_preset,
    capital_movement_sessions,
    configured_alert_rules,
    configured_capital_movement,
    configured_rule_profile,
    default_analysis_config,
    geography_column,
    update_alert_rules,
    update_capital_movement,
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


def test_legacy_config_migrates_to_daily_capital_movement(tmp_path) -> None:
    store = AnalysisConfigStore(tmp_path / "analysis.json")
    legacy = default_analysis_config()
    legacy.pop("capital_movement")
    legacy["regional_proxies"] = {
        "Global": {"benchmark": "ACWI", "sectors": {}, "industries": {}}
    }
    legacy["rule_profiles"]["Swing"]["minimum_setup_score"] = 77
    store.path.write_text(json.dumps(legacy), encoding="utf-8")

    loaded = store.load()

    assert configured_capital_movement(loaded) == {
        "period": "Daily",
        "custom_sessions": 1,
    }
    assert capital_movement_sessions(loaded) == 1
    assert loaded["rule_profiles"]["Swing"]["minimum_setup_score"] == 77
    assert "regional_proxies" not in loaded


def test_capital_movement_periods_are_resolved_and_validated() -> None:
    config = default_analysis_config()

    assert capital_movement_sessions(config) == 1
    weekly = update_capital_movement(config, "Weekly", 1)
    monthly = update_capital_movement(config, "Monthly", 1)
    custom = update_capital_movement(config, "Custom", 13)

    assert capital_movement_sessions(weekly) == 5
    assert capital_movement_sessions(monthly) == 21
    assert capital_movement_sessions(custom) == 13
    assert config["capital_movement"]["period"] == "Daily"

    with pytest.raises(ValueError, match="must be Daily"):
        update_capital_movement(config, "Quarterly", 1)
    with pytest.raises(ValueError, match="integer between 1 and 252"):
        update_capital_movement(config, "Custom", 0)
    with pytest.raises(ValueError, match="integer between 1 and 252"):
        update_capital_movement(config, "Custom", True)


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
    assert configured["setup_match_mode"] == "any"
    assert "heartbeat_consolidation" in configured["enabled_setup_filters"]
    assert "weighted_score_enabled" not in profile


def test_setup_filter_configuration_is_validated() -> None:
    config = default_analysis_config()

    updated = update_rule_profile(
        config,
        "Swing",
        {
            "setup_match_mode": "all",
            "enabled_setup_filters": ["sma50_cross", "increasing_volume"],
        },
    )

    assert updated["rule_profiles"]["Swing"]["setup_match_mode"] == "all"
    assert updated["rule_profiles"]["Swing"]["enabled_setup_filters"] == [
        "sma50_cross",
        "increasing_volume",
    ]
    with pytest.raises(ValueError, match="setup_match_mode"):
        update_rule_profile(config, "Swing", {"setup_match_mode": "some"})
    with pytest.raises(ValueError, match="enabled_setup_filters"):
        update_rule_profile(config, "Swing", {"enabled_setup_filters": []})
    with pytest.raises(ValueError, match="enabled_setup_filters"):
        update_rule_profile(
            config, "Swing", {"enabled_setup_filters": ["unknown"]}
        )


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


def test_packaged_default_is_valid_json() -> None:
    serialized = json.dumps(default_analysis_config())
    assert json.loads(serialized)["version"] == 1