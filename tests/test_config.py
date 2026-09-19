import json

import pytest

from stockfinder.config import (
    AnalysisConfigStore,
    configured_proxy,
    default_analysis_config,
    geography_column,
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