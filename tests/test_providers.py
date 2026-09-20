from datetime import UTC, datetime

import pandas as pd

from stockfinder.data import DataResult
from stockfinder.providers import (
    ProviderCapability,
    ProviderRegistry,
    ProviderRequest,
    discover_provider_registry,
)


class NewsProvider:
    provider_id = "test-news"
    capabilities = frozenset({ProviderCapability.NEWS_SENTIMENT})

    def fetch(self, capability, request) -> DataResult:
        assert capability == ProviderCapability.NEWS_SENTIMENT
        assert request.symbols == ("TEST",)
        return DataResult(
            pd.DataFrame(
                {
                    "Timestamp": ["2026-09-20T12:00:00Z"],
                    "Symbol": ["TEST"],
                    "Headline": ["Verified test headline"],
                    "Sentiment": [0.4],
                    "Source URL": ["https://example.com/story"],
                }
            ),
            "Test provider",
            datetime.now(UTC),
        )


class InvalidProvider:
    provider_id = "invalid"
    capabilities = frozenset({ProviderCapability.NEWS_SENTIMENT})

    def fetch(self, capability, request) -> DataResult:
        return DataResult(
            pd.DataFrame({"Headline": ["Incomplete"]}),
            "Invalid",
            datetime.now(UTC),
        )


class FakeEntryPoint:
    def __init__(self, name, loaded) -> None:
        self.name = name
        self.loaded = loaded

    def load(self):
        return self.loaded


def test_provider_registry_returns_validated_capability_data() -> None:
    registry = ProviderRegistry()
    registry.register(NewsProvider())

    result = registry.fetch(
        ProviderCapability.NEWS_SENTIMENT,
        ProviderRequest(symbols=("TEST",)),
    )

    assert result.source == "Test provider"
    assert result.data.iloc[0]["Sentiment"] == 0.4


def test_provider_registry_returns_transparent_unavailable_result() -> None:
    registry = ProviderRegistry()
    registry.register(InvalidProvider())

    result = registry.fetch(
        ProviderCapability.NEWS_SENTIMENT,
        ProviderRequest(symbols=("TEST",)),
    )

    assert result.is_fallback is True
    assert result.data.empty
    assert "Missing news_sentiment columns" in result.warning
    assert "No provider configured" in ProviderRegistry().fetch(
        ProviderCapability.MACRO_EVENTS,
        ProviderRequest(),
    ).warning


def test_provider_discovery_loads_factories_and_reports_failures() -> None:
    registry, warnings = discover_provider_registry(
        (
            FakeEntryPoint("news", NewsProvider),
            FakeEntryPoint("broken", lambda: InvalidProvider()),
            FakeEntryPoint("duplicate", NewsProvider),
        )
    )

    assert registry.provider_ids == ("test-news", "invalid")
    assert len(warnings) == 1
    assert "Duplicate provider ID" in warnings[0]