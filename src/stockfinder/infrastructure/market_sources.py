"""Validated, reviewable market proxy source configuration."""

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

from stockfinder.infrastructure.runtime import application_data_dir

DEFAULT_MARKET_SOURCES_PATH = Path(__file__).with_name(
    "default_market_sources.json"
)


def load_market_sources(path: str | Path | None = None) -> dict[str, Any]:
    """Load a configured market-source catalog or the packaged default."""
    configured_path = (
        Path(path)
        if path is not None
        else application_data_dir() / "market_sources.json"
    )
    source_path = (
        configured_path if configured_path.exists() else DEFAULT_MARKET_SOURCES_PATH
    )
    return _load_market_sources_path(source_path)


@lru_cache(maxsize=4)
def _load_market_sources_path(source_path: Path) -> dict[str, Any]:
    payload = json.loads(source_path.read_text(encoding="utf-8"))
    payload = _migrate_market_sources(payload)
    validate_market_sources(payload)
    return payload


def _migrate_market_sources(payload: dict[str, Any]) -> dict[str, Any]:
    """Convert the original flat catalog into the regional v2 structure."""
    if payload.get("version") != 1:
        return payload
    return {
        "version": 2,
        "global": {
            "benchmark": {"symbol": "ACWI", "kind": "ETF"},
            "industries": payload.get("industry_proxies", {}),
        },
        "regions": {
            "United States": {
                "benchmark": {"symbol": "SPY", "kind": "ETF"},
                "sectors": payload.get("sector_proxies", {}),
                "industries": {},
            }
        },
    }


def validate_market_sources(payload: dict[str, Any]) -> None:
    """Reject malformed regional catalogs and reused classification symbols."""
    if payload.get("version") != 2:
        raise ValueError("market source version must be 2")
    global_sources = payload.get("global")
    regions = payload.get("regions")
    if not isinstance(global_sources, dict):
        raise ValueError("global must be an object")
    if not isinstance(regions, dict) or not regions:
        raise ValueError("regions must contain at least one region")
    _validate_instrument(global_sources.get("benchmark"), "global.benchmark")
    _validate_proxy_group(global_sources.get("industries"), "global.industries")
    for region, sources in regions.items():
        if not str(region).strip() or not isinstance(sources, dict):
            raise ValueError("regions entries must be named objects")
        _validate_instrument(sources.get("benchmark"), f"regions.{region}.benchmark")
        _validate_proxy_group(sources.get("sectors"), f"regions.{region}.sectors")
        _validate_proxy_group(
            sources.get("industries"), f"regions.{region}.industries"
        )


def _validate_instrument(details: object, path: str) -> None:
    if not isinstance(details, dict):
        raise ValueError(f"{path} must be an object")
    if not str(details.get("symbol", "")).strip():
        raise ValueError(f"{path}.symbol must be a ticker")
    if details.get("kind") not in {"ETF", "Index"}:
        raise ValueError(f"{path}.kind must be ETF or Index")


def _validate_proxy_group(proxies: object, path: str) -> None:
    if not isinstance(proxies, dict):
        raise ValueError(f"{path} must be an object")
    symbols = []
    for name, details in proxies.items():
        if not str(name).strip():
            raise ValueError(f"{path} entries must have names")
        _validate_instrument(details, f"{path}.{name}")
        symbols.append(str(details["symbol"]).strip().upper())
    if len(symbols) != len(set(symbols)):
        raise ValueError(f"{path} symbols must be unique")


def _symbols(proxies: dict[str, dict[str, str]]) -> dict[str, str]:
    return {
        name: str(details["symbol"]).upper() for name, details in proxies.items()
    }


def sector_proxy_symbols(region: str = "United States") -> dict[str, str]:
    """Return reviewed sector proxy symbols for one region."""
    sources = load_market_sources()
    region_sources = sources["regions"].get(region, {})
    return _symbols(region_sources.get("sectors", {}))


def industry_proxy_symbols(region: str | None = None) -> dict[str, str]:
    """Return global industry proxies overlaid by optional regional mappings."""
    sources = load_market_sources()
    symbols = _symbols(sources["global"]["industries"])
    if region in sources["regions"]:
        symbols.update(_symbols(sources["regions"][region]["industries"]))
    return symbols


def regional_benchmark_symbols() -> dict[str, str]:
    """Return the global and regional benchmark symbols."""
    sources = load_market_sources()
    benchmarks = {
        region: str(details["benchmark"]["symbol"]).upper()
        for region, details in sources["regions"].items()
    }
    benchmarks["Global"] = str(sources["global"]["benchmark"]["symbol"]).upper()
    return benchmarks


def resolve_market_proxy(
    region: str,
    sector: str,
    industry: str,
    *,
    dedicated_only: bool = False,
) -> tuple[str, str] | None:
    """Resolve an industry, sector, then benchmark source from one catalog."""
    sources = load_market_sources()
    region_sources = sources["regions"].get(region, {})
    regional_industries = _symbols(region_sources.get("industries", {}))
    if industry in regional_industries:
        return regional_industries[industry], "regional industry ETF/index"
    global_industries = _symbols(sources["global"]["industries"])
    if industry in global_industries:
        return global_industries[industry], "dedicated industry ETF/index"
    if dedicated_only:
        return None
    regional_sectors = _symbols(region_sources.get("sectors", {}))
    if sector in regional_sectors:
        return regional_sectors[sector], "regional sector ETF/index"
    benchmark = region_sources.get("benchmark", sources["global"]["benchmark"])
    return str(benchmark["symbol"]).upper(), "regional benchmark fallback"