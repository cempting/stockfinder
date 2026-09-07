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


def test_adaptive_history_download_splits_failed_large_batches(monkeypatch) -> None:
    dates = pd.bdate_range("2026-01-01", periods=60)
    frame = pd.DataFrame(
        {
            "Open": range(60),
            "High": range(1, 61),
            "Low": range(60),
            "Close": range(1, 61),
            "Volume": [1_000] * 60,
        },
        index=dates,
    )

    def download(symbols, **kwargs):
        del kwargs
        if len(symbols) > 3:
            raise RuntimeError("batch too large")
        return pd.concat({symbol: frame for symbol in symbols}, axis=1)

    monkeypatch.setattr(data.yf, "download", download)
    monkeypatch.setattr(data.time, "sleep", lambda delay: None)

    histories, missing, retries = data._download_history_chunk(
        tuple(f"S{index}" for index in range(6)), "1y", attempts=1
    )

    assert set(histories) == {f"S{index}" for index in range(6)}
    assert not missing
    assert retries >= 1


def test_history_validation_rejects_impossible_candles() -> None:
    history = pd.DataFrame(
        {
            "Open": [100.0, 120.0],
            "High": [110.0, 110.0],
            "Low": [90.0, 90.0],
            "Close": [105.0, 115.0],
            "Volume": [1_000, 1_000],
        },
        index=pd.date_range("2026-01-01", periods=2),
    )

    validated = data._validate_history(history)

    assert len(validated) == 1
    assert validated.iloc[0]["Close"] == 105.0


def test_batch_history_refresh_uses_incremental_window(monkeypatch, tmp_path) -> None:
    dates = pd.bdate_range("2025-01-01", periods=200)
    cached = pd.DataFrame(
        {"Close": range(100, 300), "Volume": [1_000] * 200}, index=dates
    )
    cache = data.MarketHistoryCache(tmp_path / "market")
    cache.save("TEST", cached)
    requested_periods = []

    def download(symbols, period, attempts=2):
        del attempts
        requested_periods.append(period)
        update = pd.DataFrame(
            {"Close": [301.0, 302.0], "Volume": [1_100, 1_200]},
            index=pd.bdate_range(dates[-1] + pd.Timedelta(days=1), periods=2),
        )
        return {symbols[0]: update}, [], 0

    monkeypatch.setattr(data, "_market_history_cache", lambda: cache)
    monkeypatch.setattr(data, "_download_history_chunk", download)
    monkeypatch.setenv("STOCKFINDER_HISTORY_MAX_AGE_HOURS", "0")
    data.get_batch_histories.cache_clear()

    result = data.get_batch_histories(("TEST",), "1y")

    assert requested_periods == ["1mo"]
    assert result.data["TEST"]["Close"].iloc[-1] == 302.0
