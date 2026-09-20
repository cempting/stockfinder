"""Plugin contracts for optional licensed and public external data providers."""

import argparse
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from importlib.metadata import EntryPoint, entry_points
from typing import Protocol

import pandas as pd

from stockfinder.data import DataResult

ENTRY_POINT_GROUP = "stockfinder.providers"


class ProviderCapability(StrEnum):
    """External evidence categories supported by provider plugins."""

    MACRO_EVENTS = "macro_events"
    NEWS_SENTIMENT = "news_sentiment"
    INSTITUTIONAL_FLOWS = "institutional_flows"
    CONSTITUENTS = "constituents"


REQUIRED_COLUMNS = {
    ProviderCapability.MACRO_EVENTS: (
        "Timestamp",
        "Region",
        "Event",
        "Actual",
        "Forecast",
        "Previous",
        "Source URL",
    ),
    ProviderCapability.NEWS_SENTIMENT: (
        "Timestamp",
        "Symbol",
        "Headline",
        "Sentiment",
        "Source URL",
    ),
    ProviderCapability.INSTITUTIONAL_FLOWS: (
        "As of",
        "Symbol",
        "Institution",
        "Position value",
        "Change %",
        "Source URL",
    ),
    ProviderCapability.CONSTITUENTS: (
        "Symbol",
        "Name",
        "Region",
        "Country",
        "Exchange",
        "Currency",
        "Sector",
        "Industry",
    ),
}


@dataclass(frozen=True)
class ProviderRequest:
    """Provider-neutral query parameters for optional external evidence."""

    symbols: tuple[str, ...] = ()
    regions: tuple[str, ...] = ()
    start: date | None = None
    end: date | None = None
    settings: dict[str, str] = field(default_factory=dict)


class ExternalDataProvider(Protocol):
    """Contract implemented by separately installed provider adapters."""

    provider_id: str
    capabilities: frozenset[ProviderCapability]

    def fetch(
        self,
        capability: ProviderCapability,
        request: ProviderRequest,
    ) -> DataResult: ...


class ProviderContractError(ValueError):
    """Raised when an adapter returns data outside the declared schema."""


class ProviderRegistry:
    """Resolve optional provider plugins by evidence capability."""

    def __init__(self) -> None:
        self._providers: dict[str, ExternalDataProvider] = {}

    def register(self, provider: ExternalDataProvider) -> None:
        provider_id = str(provider.provider_id).strip()
        if not provider_id:
            raise ProviderContractError("Provider ID must not be empty")
        if provider_id in self._providers:
            raise ProviderContractError(f"Duplicate provider ID: {provider_id}")
        unknown = set(provider.capabilities) - set(ProviderCapability)
        if unknown:
            raise ProviderContractError(
                f"Provider {provider_id} has unknown capabilities: {unknown}"
            )
        self._providers[provider_id] = provider

    @property
    def provider_ids(self) -> tuple[str, ...]:
        return tuple(self._providers)

    def providers_for(
        self, capability: ProviderCapability
    ) -> tuple[ExternalDataProvider, ...]:
        return tuple(
            provider
            for provider in self._providers.values()
            if capability in provider.capabilities
        )

    def fetch(
        self,
        capability: ProviderCapability,
        request: ProviderRequest,
    ) -> DataResult:
        """Return the first usable provider result with transparent failures."""
        warnings = []
        for provider in self.providers_for(capability):
            try:
                result = provider.fetch(capability, request)
                validate_provider_result(capability, result)
            except Exception as error:
                warnings.append(f"{provider.provider_id}: {error}")
                continue
            if not result.data.empty:
                return result
            warnings.append(
                f"{provider.provider_id}: {result.warning or 'no records returned'}"
            )
        columns = REQUIRED_COLUMNS[capability]
        warning = "; ".join(warnings) or (
            f"No provider configured for {capability.value}"
        )
        return DataResult(
            pd.DataFrame(columns=columns),
            "No configured external provider",
            datetime.now(UTC),
            is_fallback=True,
            warning=warning,
        )


def validate_provider_result(
    capability: ProviderCapability,
    result: DataResult,
) -> None:
    """Validate one adapter response before it reaches analysis or presentation."""
    if not isinstance(result, DataResult):
        raise ProviderContractError("Provider must return DataResult")
    if not isinstance(result.data, pd.DataFrame):
        raise ProviderContractError("Provider result data must be a DataFrame")
    missing = set(REQUIRED_COLUMNS[capability]) - set(result.data.columns)
    if missing:
        raise ProviderContractError(
            f"Missing {capability.value} columns: {', '.join(sorted(missing))}"
        )
    if not str(result.source).strip():
        raise ProviderContractError("Provider source must not be empty")


def discover_provider_registry(
    discovered: Iterable[EntryPoint] | None = None,
) -> tuple[ProviderRegistry, tuple[str, ...]]:
    """Load adapters registered under the stockfinder.providers entry-point group."""
    registry = ProviderRegistry()
    warnings = []
    candidates = (
        tuple(discovered)
        if discovered is not None
        else tuple(entry_points().select(group=ENTRY_POINT_GROUP))
    )
    for entry_point in candidates:
        try:
            loaded = entry_point.load()
            provider = loaded() if callable(loaded) else loaded
            registry.register(provider)
        except Exception as error:
            warnings.append(f"{entry_point.name}: {error}")
    return registry, tuple(warnings)


def main(argv: list[str] | None = None) -> int:
    """List discovered adapters and capability coverage without fetching data."""
    parser = argparse.ArgumentParser(
        description="Inspect installed Stockfinder external-data providers."
    )
    parser.parse_args(argv)
    registry, warnings = discover_provider_registry()
    print(f"Discovered providers: {len(registry.provider_ids)}")
    for capability in ProviderCapability:
        providers = registry.providers_for(capability)
        names = ", ".join(provider.provider_id for provider in providers) or "none"
        print(f"{capability.value}: {names}")
    for warning in warnings:
        print(f"Warning: {warning}")
    return 1 if warnings else 0


if __name__ == "__main__":
    raise SystemExit(main())