import pandas as pd

from stockfinder import data
from stockfinder.data import (
    INDUSTRY_ETFS,
    INTERNATIONAL_UNIVERSE,
    SECURITY_UNIVERSE,
    UNIVERSE_NAMES,
    DataResult,
    fundamental_metrics,
    parse_nasdaq_universe,
    parse_news,
    risk_metrics,
)


def test_every_representative_industry_has_an_etf_proxy() -> None:
    assert set(SECURITY_UNIVERSE["Industry"]) <= set(INDUSTRY_ETFS)


def test_nasdaq_universe_keeps_illiquid_rows_and_maps_sectors() -> None:
    universe = parse_nasdaq_universe(
        [
            {
                "symbol": "TECH",
                "name": "Technology Corp",
                "lastsale": "$12.50",
                "marketCap": "1000000",
                "volume": "0",
                "sector": "Technology",
                "industry": "Computer Software",
                "country": "United States",
                "ipoyear": "2020",
            },
            {
                "symbol": "TINY",
                "name": "Tiny Corp",
                "lastsale": "$0.25",
                "marketCap": "",
                "volume": "1",
                "sector": "Finance",
                "industry": "Major Banks",
            },
        ]
    )

    assert universe["Symbol"].tolist() == ["TECH", "TINY"]
    assert universe["Sector"].tolist() == ["Information Technology", "Financials"]
    assert universe.loc[0, "Last price"] == 12.5
    assert universe.loc[0, "Volume"] == 0


def test_requested_us_universes_are_registered() -> None:
    assert set(UNIVERSE_NAMES) == {
        "S&P 500",
        "NASDAQ-listed",
        "Russell 1000 approximation",
        "Russell 2000 approximation",
        "Russell 3000 approximation",
        "Dow Jones Industrial Average",
        "S&P 1500 approximation",
    }


def test_international_universe_uses_local_listing_symbols_and_metadata() -> None:
    symbols = set(INTERNATIONAL_UNIVERSE["Symbol"])

    assert {"ASML.AS", "SAP.DE", "SHEL.L", "7203.T", "0700.HK", "BHP.AX"} <= symbols
    assert {"Region", "Country", "Exchange", "Currency"} <= set(
        INTERNATIONAL_UNIVERSE.columns
    )
    assert INTERNATIONAL_UNIVERSE["Symbol"].is_unique


def test_global_universe_combines_us_and_local_listings(monkeypatch) -> None:
    us = pd.DataFrame(
        {
            "Symbol": ["AAPL"],
            "Name": ["Apple"],
            "Sector": ["Information Technology"],
            "Industry": ["Technology Hardware"],
            "Country": ["United States"],
        }
    )
    monkeypatch.setattr(
        data,
        "get_broad_us_universe",
        lambda as_of=None: DataResult(us, "Test US", pd.Timestamp.now()),
    )
    data.get_global_universe.cache_clear()

    result = data.get_global_universe()

    assert {"AAPL", "ASML.AS", "7203.T"} <= set(result.data["Symbol"])
    assert result.data.set_index("Symbol").loc["AAPL", "Region"] == "United States"
    assert result.data.set_index("Symbol").loc["ASML.AS", "Exchange"] == (
        "Euronext Amsterdam"
    )


def test_parse_nested_yahoo_news() -> None:
    news = parse_news(
        [
            {
                "content": {
                    "title": "Company reports results",
                    "summary": "Revenue increased.",
                    "pubDate": "2026-08-30T10:00:00Z",
                    "provider": {"displayName": "Example News"},
                    "canonicalUrl": {"url": "https://example.com/story"},
                }
            }
        ]
    )

    assert news.iloc[0]["Publisher"] == "Example News"
    assert news.iloc[0]["URL"] == "https://example.com/story"


def test_metric_normalization_is_bounded() -> None:
    fundamentals = fundamental_metrics(
        {
            "revenueGrowth": 0.2,
            "earningsGrowth": 0.3,
            "returnOnEquity": 0.25,
            "profitMargins": 0.2,
            "debtToEquity": 40,
            "currentRatio": 1.8,
            "trailingPE": 20,
            "freeCashflow": 1_000_000,
        }
    )

    assert all(value is None or 0 <= value <= 100 for value in fundamentals.values())


def test_fundamental_metrics_expose_six_transparent_pillars() -> None:
    fundamentals = fundamental_metrics(
        {
            "revenueGrowth": 0.20,
            "earningsGrowth": 0.25,
            "grossMargins": 0.50,
            "operatingMargins": 0.20,
            "returnOnEquity": 0.20,
            "returnOnAssets": 0.10,
            "freeCashflow": 250,
            "operatingCashflow": 300,
            "totalRevenue": 1_000,
            "debtToEquity": 40,
            "currentRatio": 1.8,
            "trailingPE": 20,
            "forwardPE": 18,
            "priceToBook": 3,
            "dividendYield": 0.02,
            "payoutRatio": 0.40,
        }
    )

    assert list(fundamentals) == [
        "Quality",
        "Growth",
        "Cash flow",
        "Stability",
        "Valuation",
        "Dividends",
    ]
    assert all(value is not None for value in fundamentals.values())


def test_missing_fundamental_pillar_is_not_scored_as_weak() -> None:
    fundamentals = fundamental_metrics({"revenueGrowth": 0.20})

    assert fundamentals["Growth"] is not None
    assert fundamentals["Cash flow"] is None
    assert fundamentals["Dividends"] is None


def test_risk_metrics_penalize_larger_drawdown() -> None:
    stable = pd.DataFrame({"Close": [100, 101, 102, 101, 103]})
    falling = pd.DataFrame({"Close": [100, 95, 80, 65, 50]})
    profile = {"debtToEquity": 50, "currentRatio": 1.5}

    assert risk_metrics(falling, profile)["Maximum drawdown"] > risk_metrics(
        stable, profile
    )["Maximum drawdown"]
