import json

import pandas as pd
import pytest

from stockfinder.infrastructure.market_sources import (
    industry_proxy_symbols,
    load_market_sources,
    regional_benchmark_symbols,
    representative_industry_symbols,
    resolve_industry_source,
    resolve_market_proxy,
    sector_proxy_symbols,
    validate_market_sources,
)


def test_packaged_market_sources_have_unique_industry_symbols() -> None:
    sources = load_market_sources()
    symbols = [
        details["symbol"] for details in sources["global"]["industries"].values()
    ]

    assert len(symbols) == len(set(symbols))
    assert industry_proxy_symbols()["Semiconductors"] == "SMH"
    assert sector_proxy_symbols()["Information Technology"] == "XLK"
    assert regional_benchmark_symbols()["Europe"] == "VGK"


def test_market_sources_can_be_loaded_from_reviewable_override(tmp_path) -> None:
    path = tmp_path / "market_sources.json"
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "sector_proxies": {
                    "Technology": {"symbol": "XLK", "kind": "ETF"}
                },
                "industry_proxies": {
                    "Semiconductors": {"symbol": "SOXX", "kind": "ETF"}
                },
            }
        ),
        encoding="utf-8",
    )

    loaded = load_market_sources(path)

    assert loaded["version"] == 2
    assert loaded["global"]["industries"]["Semiconductors"] == {
        "symbol": "SOXX",
        "kind": "ETF",
    }


def test_market_proxy_resolution_prefers_regional_then_global_sources() -> None:
    assert resolve_market_proxy(
        "United States", "Information Technology", "Semiconductors"
    ) == ("SMH", "dedicated industry ETF/index")
    assert resolve_market_proxy(
        "United States", "Information Technology", "Unknown"
    ) == ("XLK", "regional sector ETF/index")
    assert resolve_market_proxy("Europe", "Industrials", "Unknown") == (
        "VGK",
        "regional benchmark fallback",
    )


def test_unmapped_industry_uses_largest_market_cap_constituent() -> None:
    universe = pd.DataFrame(
        {
            "Region": ["Europe", "Europe"],
            "Sector": ["Financials", "Financials"],
            "Industry": ["Insurance", "Insurance"],
            "Symbol": ["SMALL", "LARGE"],
            "Market cap": [10, 100],
        }
    )

    representatives = representative_industry_symbols(universe)

    assert resolve_industry_source(
        "Europe", "Financials", "Insurance", representatives
    ) == ("LARGE", "representative stock fallback")
    assert resolve_industry_source(
        "Europe", "Information Technology", "Semiconductors", representatives
    ) == ("SMH", "dedicated industry ETF/index")
    assert (
        resolve_market_proxy(
            "Europe", "Industrials", "Unknown", dedicated_only=True
        )
        is None
    )


def test_market_sources_reject_reused_industry_symbols() -> None:
    with pytest.raises(ValueError, match="global.industries symbols must be unique"):
        validate_market_sources(
            {
                "version": 2,
                "global": {
                    "benchmark": {"symbol": "ACWI", "kind": "ETF"},
                    "industry_fallback": {
                        "kind": "Stock",
                        "selection": "largest_market_cap_constituent",
                    },
                    "industries": {
                        "Banks": {"symbol": "KBE", "kind": "ETF"},
                        "Major Banks": {"symbol": "KBE", "kind": "ETF"},
                    },
                },
                "regions": {
                    "United States": {
                        "benchmark": {"symbol": "SPY", "kind": "ETF"},
                        "sectors": {},
                        "industries": {},
                    }
                },
            }
        )