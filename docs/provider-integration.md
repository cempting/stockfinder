# External Provider Integration

Stockfinder discovers optional external-data adapters through Python entry points.
The core application does not contain provider credentials and does not fabricate
records when no adapter is installed.

## Capabilities

Adapters may implement any subset of these `ProviderCapability` values:

- `macro_events`
- `news_sentiment`
- `institutional_flows`
- `constituents`

Each response must be a `DataResult` containing a pandas DataFrame, source label,
retrieval timestamp, and optional warning/fallback metadata. Required columns are
defined in `stockfinder.providers.REQUIRED_COLUMNS` and validated before results
can reach analysis or presentation code.

Institutional-flow adapters should identify the evidence accurately. Regulatory
holdings such as SEC Form 13F are delayed position disclosures, not real-time
institutional transactions. News sentiment must retain the original headline,
timestamp, symbol, and source URL.

## Adapter Contract

```python
from datetime import UTC, datetime

import pandas as pd

from stockfinder.data import DataResult
from stockfinder.providers import ProviderCapability, ProviderRequest


class LicensedProvider:
    provider_id = "licensed-provider"
    capabilities = frozenset({ProviderCapability.NEWS_SENTIMENT})

    def fetch(
        self,
        capability: ProviderCapability,
        request: ProviderRequest,
    ) -> DataResult:
        frame = pd.DataFrame(
            columns=[
                "Timestamp",
                "Symbol",
                "Headline",
                "Sentiment",
                "Source URL",
            ]
        )
        return DataResult(frame, self.provider_id, datetime.now(UTC))


def create_provider() -> LicensedProvider:
    return LicensedProvider()
```

Register the factory from the adapter package:

```toml
[project.entry-points."stockfinder.providers"]
licensed-provider = "licensed_provider:create_provider"
```

After installing that package in the same environment, inspect discovery without
fetching data:

```bash
stockfinder-providers
```

## Credentials And Caching

Read API credentials from provider-specific environment variables or the hosting
platform's secret manager. Do not place keys in dashboard JSON, analysis config,
SQLite records, logs, fixtures, or source control.

Adapters own their HTTP client, authentication, provider rate-limit handling, and
raw-response cache. They should return an empty schema-correct DataFrame with a
warning when no records exist. Authentication failures, malformed payloads, and
schema violations are surfaced by the registry as unavailable evidence rather
than replaced with synthetic values.

## Selection

The registry evaluates providers in entry-point discovery order and returns the
first nonempty, schema-valid result for a capability. A deployment that installs
multiple adapters should package them in the preferred order or construct an
explicit `ProviderRegistry` in its composition root.