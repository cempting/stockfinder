"""Market data access with explicit source and fallback metadata."""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache
from typing import Any
from urllib.request import Request, urlopen

import numpy as np
import pandas as pd
import yfinance as yf

STOCK_SCREENER_URL = (
    "https://api.nasdaq.com/api/screener/stocks"
    "?tableonly=true&limit=10000&offset=0&exchange={exchange}&download=true"
)

UNIVERSE_NAMES = (
    "S&P 500",
    "NASDAQ-listed",
    "Russell 1000 approximation",
    "Russell 2000 approximation",
    "Russell 3000 approximation",
    "Dow Jones Industrial Average",
    "S&P 1500 approximation",
)

UNIVERSE_SIZES = {
    "S&P 500": 500,
    "Russell 1000 approximation": 1000,
    "Russell 2000 approximation": 2000,
    "Russell 3000 approximation": 3000,
    "Dow Jones Industrial Average": 30,
    "S&P 1500 approximation": 1500,
}

NASDAQ_SECTOR_MAP = {
    "Basic Materials": "Materials",
    "Consumer Discretionary": "Consumer Discretionary",
    "Consumer Staples": "Consumer Staples",
    "Energy": "Energy",
    "Finance": "Financials",
    "Health Care": "Health Care",
    "Industrials": "Industrials",
    "Real Estate": "Real Estate",
    "Technology": "Information Technology",
    "Telecommunications": "Communication Services",
    "Utilities": "Utilities",
}

SECTOR_ETFS = {
    "Communication Services": "XLC",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Industrials": "XLI",
    "Information Technology": "XLK",
    "Materials": "XLB",
    "Real Estate": "XLRE",
    "Utilities": "XLU",
}

METAL_PROXIES = {
    "GLD": ("Gold", "Precious metal"),
    "SLV": ("Silver", "Precious metal"),
    "PPLT": ("Platinum", "Precious metal"),
    "PALL": ("Palladium", "Precious metal"),
    "CPER": ("Copper", "Industrial metal"),
    "DBB": ("Industrial metals basket", "Industrial metals"),
}
METALS_BENCHMARK = "DBC"

INDUSTRY_ETFS = {
    "Internet Content": "FDN",
    "Broadline Retail": "XRT",
    "Automobiles": "CARZ",
    "Consumer Staples Retail": "RTH",
    "Household Products": "RHS",
    "Integrated Oil & Gas": "XOP",
    "Diversified Banks": "KBE",
    "Transaction Processing": "IPAY",
    "Pharmaceuticals": "PPH",
    "Managed Health Care": "IHF",
    "Aerospace & Defense": "ITA",
    "Machinery": "AIRR",
    "Semiconductors": "SMH",
    "Systems Software": "IGV",
    "Technology Hardware": "IYW",
    "Industrial Gases": "IYM",
    "Copper": "COPX",
    "Industrial REITs": "INDS",
    "Telecom Tower REITs": "SRVR",
    "Electric Utilities": "VPU",
}

SECURITY_UNIVERSE = pd.DataFrame(
    [
        ("META", "Meta Platforms", "Communication Services", "Internet Content"),
        ("GOOGL", "Alphabet", "Communication Services", "Internet Content"),
        ("AMZN", "Amazon", "Consumer Discretionary", "Broadline Retail"),
        ("TSLA", "Tesla", "Consumer Discretionary", "Automobiles"),
        ("COST", "Costco", "Consumer Staples", "Consumer Staples Retail"),
        ("PG", "Procter & Gamble", "Consumer Staples", "Household Products"),
        ("XOM", "Exxon Mobil", "Energy", "Integrated Oil & Gas"),
        ("CVX", "Chevron", "Energy", "Integrated Oil & Gas"),
        ("JPM", "JPMorgan Chase", "Financials", "Diversified Banks"),
        ("V", "Visa", "Financials", "Transaction Processing"),
        ("LLY", "Eli Lilly", "Health Care", "Pharmaceuticals"),
        ("UNH", "UnitedHealth", "Health Care", "Managed Health Care"),
        ("GE", "GE Aerospace", "Industrials", "Aerospace & Defense"),
        ("CAT", "Caterpillar", "Industrials", "Machinery"),
        ("NVDA", "NVIDIA", "Information Technology", "Semiconductors"),
        ("MSFT", "Microsoft", "Information Technology", "Systems Software"),
        ("AAPL", "Apple", "Information Technology", "Technology Hardware"),
        ("LIN", "Linde", "Materials", "Industrial Gases"),
        ("FCX", "Freeport-McMoRan", "Materials", "Copper"),
        ("PLD", "Prologis", "Real Estate", "Industrial REITs"),
        ("AMT", "American Tower", "Real Estate", "Telecom Tower REITs"),
        ("NEE", "NextEra Energy", "Utilities", "Electric Utilities"),
        ("DUK", "Duke Energy", "Utilities", "Electric Utilities"),
    ],
    columns=["Symbol", "Name", "Sector", "Industry"],
)

INTERNATIONAL_UNIVERSE = pd.DataFrame(
    [
        (
            "ASML.AS",
            "ASML",
            "Europe",
            "Netherlands",
            "Euronext Amsterdam",
            "EUR",
            "Information Technology",
            "Semiconductors",
        ),
        (
            "SAP.DE",
            "SAP",
            "Europe",
            "Germany",
            "Xetra",
            "EUR",
            "Information Technology",
            "Software",
        ),
        (
            "SIE.DE",
            "Siemens",
            "Europe",
            "Germany",
            "Xetra",
            "EUR",
            "Industrials",
            "Industrial Machinery",
        ),
        (
            "ALV.DE",
            "Allianz",
            "Europe",
            "Germany",
            "Xetra",
            "EUR",
            "Financials",
            "Insurance",
        ),
        (
            "MC.PA",
            "LVMH",
            "Europe",
            "France",
            "Euronext Paris",
            "EUR",
            "Consumer Discretionary",
            "Luxury Goods",
        ),
        (
            "AIR.PA",
            "Airbus",
            "Europe",
            "France",
            "Euronext Paris",
            "EUR",
            "Industrials",
            "Aerospace & Defense",
        ),
        (
            "SU.PA",
            "Schneider Electric",
            "Europe",
            "France",
            "Euronext Paris",
            "EUR",
            "Industrials",
            "Electrical Equipment",
        ),
        (
            "NESN.SW",
            "Nestle",
            "Europe",
            "Switzerland",
            "SIX Swiss Exchange",
            "CHF",
            "Consumer Staples",
            "Packaged Foods",
        ),
        (
            "NOVN.SW",
            "Novartis",
            "Europe",
            "Switzerland",
            "SIX Swiss Exchange",
            "CHF",
            "Health Care",
            "Pharmaceuticals",
        ),
        (
            "ROG.SW",
            "Roche",
            "Europe",
            "Switzerland",
            "SIX Swiss Exchange",
            "CHF",
            "Health Care",
            "Pharmaceuticals",
        ),
        (
            "SHEL.L",
            "Shell",
            "Europe",
            "United Kingdom",
            "London Stock Exchange",
            "GBp",
            "Energy",
            "Integrated Oil & Gas",
        ),
        (
            "AZN.L",
            "AstraZeneca",
            "Europe",
            "United Kingdom",
            "London Stock Exchange",
            "GBp",
            "Health Care",
            "Pharmaceuticals",
        ),
        (
            "HSBA.L",
            "HSBC",
            "Europe",
            "United Kingdom",
            "London Stock Exchange",
            "GBp",
            "Financials",
            "Banks",
        ),
        (
            "ULVR.L",
            "Unilever",
            "Europe",
            "United Kingdom",
            "London Stock Exchange",
            "GBp",
            "Consumer Staples",
            "Household Products",
        ),
        (
            "NOVO-B.CO",
            "Novo Nordisk",
            "Europe",
            "Denmark",
            "Nasdaq Copenhagen",
            "DKK",
            "Health Care",
            "Pharmaceuticals",
        ),
        (
            "EQNR.OL",
            "Equinor",
            "Europe",
            "Norway",
            "Oslo Bors",
            "NOK",
            "Energy",
            "Integrated Oil & Gas",
        ),
        (
            "ERIC-B.ST",
            "Ericsson",
            "Europe",
            "Sweden",
            "Nasdaq Stockholm",
            "SEK",
            "Information Technology",
            "Communications Equipment",
        ),
        (
            "SAN.MC",
            "Banco Santander",
            "Europe",
            "Spain",
            "Bolsa de Madrid",
            "EUR",
            "Financials",
            "Banks",
        ),
        (
            "ENEL.MI",
            "Enel",
            "Europe",
            "Italy",
            "Borsa Italiana",
            "EUR",
            "Utilities",
            "Electric Utilities",
        ),
        (
            "7203.T",
            "Toyota Motor",
            "Asia",
            "Japan",
            "Tokyo Stock Exchange",
            "JPY",
            "Consumer Discretionary",
            "Automobiles",
        ),
        (
            "6758.T",
            "Sony Group",
            "Asia",
            "Japan",
            "Tokyo Stock Exchange",
            "JPY",
            "Consumer Discretionary",
            "Consumer Electronics",
        ),
        (
            "9984.T",
            "SoftBank Group",
            "Asia",
            "Japan",
            "Tokyo Stock Exchange",
            "JPY",
            "Financials",
            "Investment Holding",
        ),
        (
            "8035.T",
            "Tokyo Electron",
            "Asia",
            "Japan",
            "Tokyo Stock Exchange",
            "JPY",
            "Information Technology",
            "Semiconductor Equipment",
        ),
        (
            "0700.HK",
            "Tencent",
            "Asia",
            "China",
            "Hong Kong Stock Exchange",
            "HKD",
            "Communication Services",
            "Interactive Media",
        ),
        (
            "9988.HK",
            "Alibaba",
            "Asia",
            "China",
            "Hong Kong Stock Exchange",
            "HKD",
            "Consumer Discretionary",
            "Broadline Retail",
        ),
        (
            "1299.HK",
            "AIA Group",
            "Asia",
            "Hong Kong",
            "Hong Kong Stock Exchange",
            "HKD",
            "Financials",
            "Insurance",
        ),
        (
            "005930.KS",
            "Samsung Electronics",
            "Asia",
            "South Korea",
            "Korea Exchange",
            "KRW",
            "Information Technology",
            "Technology Hardware",
        ),
        (
            "000660.KS",
            "SK Hynix",
            "Asia",
            "South Korea",
            "Korea Exchange",
            "KRW",
            "Information Technology",
            "Semiconductors",
        ),
        (
            "2330.TW",
            "TSMC",
            "Asia",
            "Taiwan",
            "Taiwan Stock Exchange",
            "TWD",
            "Information Technology",
            "Semiconductors",
        ),
        (
            "RELIANCE.NS",
            "Reliance Industries",
            "Asia",
            "India",
            "National Stock Exchange of India",
            "INR",
            "Energy",
            "Diversified Energy",
        ),
        (
            "INFY.NS",
            "Infosys",
            "Asia",
            "India",
            "National Stock Exchange of India",
            "INR",
            "Information Technology",
            "IT Services",
        ),
        (
            "BHP.AX",
            "BHP Group",
            "Asia-Pacific",
            "Australia",
            "Australian Securities Exchange",
            "AUD",
            "Materials",
            "Diversified Mining",
        ),
        (
            "CBA.AX",
            "Commonwealth Bank",
            "Asia-Pacific",
            "Australia",
            "Australian Securities Exchange",
            "AUD",
            "Financials",
            "Banks",
        ),
        (
            "CSL.AX",
            "CSL",
            "Asia-Pacific",
            "Australia",
            "Australian Securities Exchange",
            "AUD",
            "Health Care",
            "Biotechnology",
        ),
        (
            "SHOP.TO",
            "Shopify",
            "Canada",
            "Canada",
            "Toronto Stock Exchange",
            "CAD",
            "Information Technology",
            "Software",
        ),
        (
            "RY.TO",
            "Royal Bank of Canada",
            "Canada",
            "Canada",
            "Toronto Stock Exchange",
            "CAD",
            "Financials",
            "Banks",
        ),
        (
            "CNQ.TO",
            "Canadian Natural Resources",
            "Canada",
            "Canada",
            "Toronto Stock Exchange",
            "CAD",
            "Energy",
            "Oil & Gas Production",
        ),
        (
            "VALE3.SA",
            "Vale",
            "Latin America",
            "Brazil",
            "B3",
            "BRL",
            "Materials",
            "Diversified Mining",
        ),
        (
            "PETR4.SA",
            "Petrobras",
            "Latin America",
            "Brazil",
            "B3",
            "BRL",
            "Energy",
            "Integrated Oil & Gas",
        ),
        (
            "NPN.JO",
            "Naspers",
            "Africa",
            "South Africa",
            "Johannesburg Stock Exchange",
            "ZAc",
            "Consumer Discretionary",
            "Internet Retail",
        ),
    ],
    columns=[
        "Symbol",
        "Name",
        "Region",
        "Country",
        "Exchange",
        "Currency",
        "Sector",
        "Industry",
    ],
)


@dataclass(frozen=True)
class DataResult:
    """A data payload with provenance and freshness information."""

    data: Any
    source: str
    retrieved_at: datetime
    is_fallback: bool = False
    warning: str | None = None


@lru_cache(maxsize=2)
def get_nasdaq_universe(as_of: date | None = None) -> DataResult:
    """Return the daily public NASDAQ stock screener universe."""
    return get_exchange_universe("NASDAQ", as_of)


@lru_cache(maxsize=8)
def get_exchange_universe(exchange: str, as_of: date | None = None) -> DataResult:
    """Return a public exchange stock universe from Nasdaq's screener."""
    requested_date = as_of or datetime.now(UTC).date()
    retrieved_at = datetime.now(UTC)
    request = Request(
        STOCK_SCREENER_URL.format(exchange=exchange.upper()),
        headers={
            "Accept": "application/json, text/plain, */*",
            "User-Agent": "Mozilla/5.0 Stockfinder/0.1",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:  # noqa: S310
            payload = json.load(response)
        data = payload.get("data") or {}
        rows = data.get("rows") or []
        universe = parse_nasdaq_universe(rows)
        if universe.empty:
            raise ValueError("Nasdaq returned no stock rows")
        source_date = data.get("asOf") or requested_date.isoformat()
        return DataResult(
            universe,
            f"Nasdaq public stock screener ({exchange.upper()}) · {source_date}",
            retrieved_at,
        )
    except Exception as error:
        fallback = SECURITY_UNIVERSE.rename(
            columns={"Sector": "Sector", "Industry": "Industry"}
        ).copy()
        fallback["Provider sector"] = fallback["Sector"]
        fallback["Provider industry"] = fallback["Industry"]
        fallback["Last price"] = pd.NA
        fallback["Day %"] = pd.NA
        fallback["Market cap"] = pd.NA
        fallback["Volume"] = pd.NA
        fallback["Country"] = "United States"
        fallback["IPO year"] = ""
        return DataResult(
            fallback,
            "Representative fallback universe",
            retrieved_at,
            is_fallback=True,
            warning=f"{exchange.upper()} universe unavailable: {error}",
        )


@lru_cache(maxsize=16)
def get_market_universe(name: str, as_of: date | None = None) -> DataResult:
    """Build a named public US universe or transparent market-cap approximation."""
    if name not in UNIVERSE_NAMES:
        raise ValueError(f"Unknown market universe: {name}")
    if name == "NASDAQ-listed":
        return get_nasdaq_universe(as_of)

    retrieved_at = datetime.now(UTC)
    nasdaq = get_exchange_universe("NASDAQ", as_of)
    nyse = get_exchange_universe("NYSE", as_of)
    combined = pd.concat([nasdaq.data, nyse.data], ignore_index=True)
    combined = combined.drop_duplicates("Symbol")
    combined = combined[combined["Market cap"].notna()].sort_values(
        "Market cap", ascending=False
    )
    source = "Nasdaq public screener NASDAQ+NYSE market-cap approximation"

    if name == "Russell 1000 approximation":
        universe = combined.head(1000)
    elif name == "Russell 2000 approximation":
        universe = combined.iloc[1000:3000]
    elif name == "Russell 3000 approximation":
        universe = combined.head(3000)
    elif name == "Dow Jones Industrial Average":
        universe = combined[combined["Symbol"].isin(DJIA_SYMBOLS)]
        source = "Public DJIA symbol set enriched by Nasdaq screener"
    elif name == "S&P 500":
        universe = combined.head(500)
        source = "Top-500 US market-cap approximation (not official S&P membership)"
    else:
        universe = combined.head(1500)
        source = "Top-1500 US market-cap approximation (not official S&P membership)"

    warnings = [result.warning for result in (nasdaq, nyse) if result.warning]
    return DataResult(
        universe.reset_index(drop=True),
        source,
        retrieved_at,
        is_fallback=nasdaq.is_fallback or nyse.is_fallback,
        warning="; ".join(warnings) or None,
    )


@lru_cache(maxsize=2)
def get_broad_us_universe(as_of: date | None = None) -> DataResult:
    """Return all classified NASDAQ and NYSE stocks available publicly."""
    retrieved_at = datetime.now(UTC)
    nasdaq = get_exchange_universe("NASDAQ", as_of)
    nyse = get_exchange_universe("NYSE", as_of)
    combined = pd.concat([nasdaq.data, nyse.data], ignore_index=True)
    combined = combined.drop_duplicates("Symbol")
    combined = combined[
        (combined["Sector"] != "Unclassified")
        & (combined["Industry"] != "Unclassified")
    ].reset_index(drop=True)
    warnings = [result.warning for result in (nasdaq, nyse) if result.warning]
    return DataResult(
        combined,
        "Nasdaq public screener · NASDAQ and NYSE classified stocks",
        retrieved_at,
        is_fallback=nasdaq.is_fallback or nyse.is_fallback,
        warning="; ".join(warnings) or None,
    )


@lru_cache(maxsize=2)
def get_global_universe(as_of: date | None = None) -> DataResult:
    """Combine broad US listings with curated international local listings."""
    us_result = get_broad_us_universe(as_of)
    us = us_result.data.copy()
    us["Region"] = "United States"
    us["Exchange"] = "NASDAQ / NYSE"
    us["Currency"] = "USD"
    international = INTERNATIONAL_UNIVERSE.copy()
    for column in us.columns:
        if column not in international:
            international[column] = pd.NA
    combined = pd.concat([us, international[us.columns]], ignore_index=True)
    combined = combined.drop_duplicates("Symbol").reset_index(drop=True)
    return DataResult(
        combined,
        f"{us_result.source} · curated international local listings",
        datetime.now(UTC),
        is_fallback=us_result.is_fallback,
        warning=us_result.warning,
    )


DJIA_SYMBOLS = {
    "AAPL",
    "AMGN",
    "AMZN",
    "AXP",
    "BA",
    "CAT",
    "CRM",
    "CSCO",
    "CVX",
    "DIS",
    "GS",
    "HD",
    "HON",
    "IBM",
    "JNJ",
    "JPM",
    "KO",
    "MCD",
    "MMM",
    "MRK",
    "MSFT",
    "NKE",
    "NVDA",
    "PG",
    "SHW",
    "TRV",
    "UNH",
    "V",
    "VZ",
    "WMT",
}


def parse_nasdaq_universe(rows: list[dict[str, Any]]) -> pd.DataFrame:
    """Normalize all public screener rows without applying liquidity filters."""
    records = []
    for row in rows:
        symbol = str(row.get("symbol") or "").strip().upper()
        if not symbol:
            continue
        provider_sector = str(row.get("sector") or "Unclassified").strip()
        provider_industry = str(row.get("industry") or "Unclassified").strip()
        records.append(
            {
                "Symbol": symbol,
                "Name": str(row.get("name") or symbol).strip(),
                "Sector": NASDAQ_SECTOR_MAP.get(provider_sector, provider_sector),
                "Industry": provider_industry,
                "Provider sector": provider_sector,
                "Provider industry": provider_industry,
                "Last price": _numeric(row.get("lastsale")),
                "Day %": _numeric(row.get("pctchange")),
                "Market cap": _numeric(row.get("marketCap")),
                "Volume": _numeric(row.get("volume")),
                "Country": str(row.get("country") or "Unknown").strip(),
                "IPO year": str(row.get("ipoyear") or "").strip(),
            }
        )
    if not records:
        return pd.DataFrame(
            columns=[
                "Symbol",
                "Name",
                "Sector",
                "Industry",
                "Provider sector",
                "Provider industry",
                "Last price",
                "Day %",
                "Market cap",
                "Volume",
                "Country",
                "IPO year",
            ]
        )
    return pd.DataFrame(records).sort_values("Symbol").reset_index(drop=True)


def _numeric(value: Any) -> float | None:
    text = str(value or "").replace("$", "").replace(",", "").strip()
    try:
        return float(text)
    except ValueError:
        return None


@lru_cache(maxsize=32)
def get_batch_histories(symbols: tuple[str, ...], period: str = "2y") -> DataResult:
    """Download adjusted histories concurrently without synthetic substitutions."""
    retrieved_at = datetime.now(UTC)
    normalized = tuple(dict.fromkeys(symbol.upper() for symbol in symbols if symbol))
    if not normalized:
        return DataResult({}, "Yahoo Finance batch", retrieved_at)
    histories: dict[str, pd.DataFrame] = {}
    missing = []
    failures = []
    for offset in range(0, len(normalized), 200):
        chunk = normalized[offset : offset + 200]
        try:
            downloaded = yf.download(
                list(chunk),
                period=period,
                auto_adjust=True,
                group_by="ticker",
                threads=True,
                progress=False,
            )
            if not isinstance(downloaded, pd.DataFrame):
                raise ValueError("Yahoo Finance returned no tabular history")
        except Exception as error:
            failures.append(f"chunk {offset // 200 + 1}: {error}")
            missing.extend(chunk)
            continue
        for symbol in chunk:
            try:
                frame = (
                    downloaded[symbol]
                    if isinstance(downloaded.columns, pd.MultiIndex)
                    else downloaded
                )
                if not isinstance(frame, pd.DataFrame):
                    raise ValueError("Yahoo Finance returned an invalid ticker frame")
                available = [
                    column
                    for column in ("Open", "High", "Low", "Close", "Volume")
                    if column in frame
                ]
                frame = frame[available].dropna(subset=["Close"])
                if len(frame) < 50:
                    raise ValueError("insufficient history")
                histories[symbol] = frame
            except (KeyError, ValueError):
                missing.append(symbol)
    warning_parts = []
    if missing:
        warning_parts.append(f"No usable history for {len(missing):,} symbols")
    if failures:
        warning_parts.append(f"{len(failures)} batch requests failed")
    warning = "; ".join(warning_parts) or None
    return DataResult(histories, "Yahoo Finance batch", retrieved_at, warning=warning)


def clear_market_data_caches() -> None:
    """Invalidate provider caches before a user-requested market refresh."""
    get_nasdaq_universe.cache_clear()
    get_exchange_universe.cache_clear()
    get_market_universe.cache_clear()
    get_broad_us_universe.cache_clear()
    get_global_universe.cache_clear()
    get_batch_histories.cache_clear()
    get_history.cache_clear()
    get_profile.cache_clear()
    get_news.cache_clear()


def _demo_history(symbol: str, periods: int = 260) -> pd.DataFrame:
    seed = sum(ord(character) for character in symbol)
    generator = np.random.default_rng(seed)
    dates = pd.bdate_range(end=pd.Timestamp.now().normalize(), periods=periods)
    drift = 0.00025 + (seed % 11) / 50_000
    returns = generator.normal(drift, 0.014 + (seed % 5) / 1_000, periods)
    close = (40 + seed % 160) * np.exp(np.cumsum(returns))
    volume = generator.integers(700_000, 8_000_000, periods)
    return pd.DataFrame(
        {
            "Open": close * generator.normal(0.998, 0.004, periods),
            "High": close * generator.normal(1.008, 0.003, periods),
            "Low": close * generator.normal(0.992, 0.003, periods),
            "Close": close,
            "Volume": volume,
        },
        index=dates,
    )


@lru_cache(maxsize=256)
def get_history(symbol: str, period: str = "1y") -> DataResult:
    """Return adjusted daily history, falling back visibly when Yahoo fails."""
    retrieved_at = datetime.now(UTC)
    try:
        history = yf.Ticker(symbol).history(period=period, auto_adjust=True)
        history = history[["Open", "High", "Low", "Close", "Volume"]].dropna(
            subset=["Close"]
        )
        if len(history) < 50:
            raise ValueError(f"Only {len(history)} valid observations returned")
        return DataResult(history, "Yahoo Finance", retrieved_at)
    except Exception as error:
        return DataResult(
            _demo_history(symbol),
            "Synthetic demonstration data",
            retrieved_at,
            is_fallback=True,
            warning=f"Yahoo Finance unavailable for {symbol}: {error}",
        )


@lru_cache(maxsize=128)
def get_profile(symbol: str) -> DataResult:
    """Return available company metrics without masking provider failures."""
    retrieved_at = datetime.now(UTC)
    try:
        profile = yf.Ticker(symbol).get_info()
        if not profile:
            raise ValueError("No company profile returned")
        return DataResult(profile, "Yahoo Finance", retrieved_at)
    except Exception as error:
        seed = sum(ord(character) for character in symbol)
        profile = {
            "longName": symbol,
            "revenueGrowth": 0.04 + (seed % 22) / 100,
            "earningsGrowth": 0.03 + (seed % 27) / 100,
            "returnOnEquity": 0.08 + (seed % 25) / 100,
            "profitMargins": 0.05 + (seed % 20) / 100,
            "debtToEquity": 25 + seed % 130,
            "currentRatio": 0.8 + (seed % 18) / 10,
            "trailingPE": 12 + seed % 35,
            "freeCashflow": 500_000_000 + (seed % 20) * 100_000_000,
            "marketCap": 10_000_000_000 + (seed % 150) * 1_000_000_000,
        }
        return DataResult(
            profile,
            "Synthetic demonstration data",
            retrieved_at,
            is_fallback=True,
            warning=f"Yahoo Finance profile unavailable for {symbol}: {error}",
        )


@lru_cache(maxsize=128)
def get_news(symbol: str) -> DataResult:
    """Return normalized recent company news with source provenance."""
    retrieved_at = datetime.now(UTC)
    try:
        records = yf.Ticker(symbol).news
        return DataResult(parse_news(records), "Yahoo Finance", retrieved_at)
    except Exception as error:
        return DataResult(
            pd.DataFrame(columns=["Published", "Title", "Publisher", "Summary", "URL"]),
            "Yahoo Finance",
            retrieved_at,
            warning=f"News unavailable for {symbol}: {error}",
        )


def parse_news(records: list[dict[str, Any]]) -> pd.DataFrame:
    """Normalize current nested and legacy Yahoo news payloads."""
    rows = []
    for record in records:
        content = record.get("content") or record
        provider = content.get("provider") or {}
        canonical = content.get("canonicalUrl") or content.get("clickThroughUrl") or {}
        published = content.get("pubDate") or content.get("providerPublishTime")
        if isinstance(published, (int, float)):
            published = datetime.fromtimestamp(published, UTC).isoformat()
        title = str(content.get("title") or "").strip()
        if not title:
            continue
        rows.append(
            {
                "Published": published,
                "Title": title,
                "Publisher": provider.get("displayName")
                or content.get("publisher")
                or "Unknown",
                "Summary": str(content.get("summary") or "").strip(),
                "URL": canonical.get("url") or content.get("link"),
            }
        )
    return pd.DataFrame(
        rows, columns=["Published", "Title", "Publisher", "Summary", "URL"]
    )


def _scale(
    value: float | None, low: float, high: float, invert: bool = False
) -> float | None:
    if value is None or pd.isna(value):
        return None
    normalized = max(0.0, min(100.0, 100 * (float(value) - low) / (high - low)))
    return 100.0 - normalized if invert else normalized


def fundamental_pillar_metrics(
    profile: dict[str, Any],
) -> dict[str, dict[str, float | None]]:
    """Group normalized reported metrics into transparent fundamental pillars."""
    free_cash_flow = profile.get("freeCashflow")
    operating_cash_flow = profile.get("operatingCashflow")
    total_revenue = profile.get("totalRevenue")
    free_cash_flow_margin = (
        float(free_cash_flow) / float(total_revenue)
        if isinstance(free_cash_flow, (int, float))
        and isinstance(total_revenue, (int, float))
        and total_revenue
        else None
    )
    return {
        "Quality": {
            "Gross margin": _scale(profile.get("grossMargins"), 0.0, 0.70),
            "Operating margin": _scale(profile.get("operatingMargins"), 0.0, 0.30),
            "Return on equity": _scale(profile.get("returnOnEquity"), 0.0, 0.30),
            "Return on assets": _scale(profile.get("returnOnAssets"), 0.0, 0.15),
        },
        "Growth": {
            "Revenue growth": _scale(profile.get("revenueGrowth"), -0.10, 0.35),
            "Earnings growth": _scale(profile.get("earningsGrowth"), -0.10, 0.35),
        },
        "Cash flow": {
            "Free cash flow margin": _scale(free_cash_flow_margin, -0.10, 0.25),
            "Positive free cash flow": (
                100.0
                if isinstance(free_cash_flow, (int, float)) and free_cash_flow > 0
                else 10.0 if isinstance(free_cash_flow, (int, float)) else None
            ),
            "Positive operating cash flow": (
                100.0
                if isinstance(operating_cash_flow, (int, float))
                and operating_cash_flow > 0
                else 10.0
                if isinstance(operating_cash_flow, (int, float))
                else None
            ),
        },
        "Stability": {
            "Debt to equity": _scale(
                profile.get("debtToEquity"), 20, 200, invert=True
            ),
            "Current ratio": _scale(profile.get("currentRatio"), 0.6, 2.5),
        },
        "Valuation": {
            "Trailing P/E": _scale(profile.get("trailingPE"), 8, 55, invert=True),
            "Forward P/E": _scale(profile.get("forwardPE"), 8, 45, invert=True),
            "Price to book": _scale(
                profile.get("priceToBook"), 1, 10, invert=True
            ),
        },
        "Dividends": {
            "Dividend yield": _scale(profile.get("dividendYield"), 0.0, 0.06),
            "Payout sustainability": _scale(
                profile.get("payoutRatio"), 0.25, 0.90, invert=True
            ),
        },
    }


def fundamental_metrics(profile: dict[str, Any]) -> dict[str, float | None]:
    """Normalize reported company metrics into transparent quality components."""
    metrics = {}
    for pillar, components in fundamental_pillar_metrics(profile).items():
        available = [value for value in components.values() if value is not None]
        metrics[pillar] = sum(available) / len(available) if available else None
    return metrics


def risk_metrics(
    history: pd.DataFrame, profile: dict[str, Any]
) -> dict[str, float | None]:
    """Normalize market and balance-sheet risks, where higher means riskier."""
    returns = history["Close"].pct_change().dropna()
    volatility = float(returns.std() * np.sqrt(252)) if not returns.empty else None
    running_high = history["Close"].cummax()
    drawdown = history["Close"] / running_high - 1
    maximum_drawdown = abs(float(drawdown.min())) if not drawdown.empty else None
    return {
        "Volatility": _scale(volatility, 0.1, 0.7),
        "Maximum drawdown": _scale(maximum_drawdown, 0.05, 0.6),
        "Balance-sheet leverage": _scale(profile.get("debtToEquity"), 20, 220),
        "Liquidity": _scale(profile.get("currentRatio"), 0.5, 2.5, invert=True),
    }
