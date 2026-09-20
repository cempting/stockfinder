# Stockfinder

A Streamlit decision workspace for market regime analysis, sector rotation,
fundamental and risk evaluation, and technical confirmation.

The product vision and requirements gathered during discovery are documented
in [docs/product-vision.md](docs/product-vision.md).
Optional licensed-provider adapters are documented in
[docs/provider-integration.md](docs/provider-integration.md).
The latest local and Streamlit Cloud acceptance findings are recorded in
[docs/acceptance-report-2026-09-20.md](docs/acceptance-report-2026-09-20.md).

## Setup

Create and activate a virtual environment, then install the package with its
development dependencies:

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

## Usage

Launch the application through its command-line entry point:

```bash
stockfinder
```

Or run Streamlit directly:

```bash
streamlit run src/stockfinder/ui.py
```

The application opens at <http://localhost:8501> by default.

## Configurable Dashboards

The default **Command Center** is composed from registered widgets rather than a
fixed page. Packaged dashboard definitions live in
`src/stockfinder/default_dashboards.json`. Create `data/dashboards.json` (or the
same file under `STOCKFINDER_DATA_DIR`) to add, remove, reorder, resize, or create
named dashboards without editing the application shell.

The modular widgets now cover market regime and controls, cross-asset conditions,
regional benchmark comparison, linked sector/industry rotation, multi-horizon
liquidity and breadth, profile-driven stock ranking, and generic stock/ETF/index
analysis. See
[docs/widget-architecture.md](docs/widget-architecture.md) for the widget
contract, configuration fields, and migration roadmap.

## Data Cache

Stockfinder persists last-known-good daily histories, completed scans, watchlists,
and portfolio data under `data/`. Set `STOCKFINDER_DATA_DIR` to use a mounted
cloud volume:

```bash
export STOCKFINDER_DATA_DIR=/data
```

Fresh history files are reused for 18 hours by default. Override this with
`STOCKFINDER_HISTORY_MAX_AGE_HOURS`. Company profiles are reused for seven days;
override this with `STOCKFINDER_PROFILE_MAX_AGE_HOURS`. Provider failures are
retried with smaller batches; unresolved symbols use last-known real data when
available. Synthetic data is reserved for symbols with no cached or provider
data.

## Broker Tradability

Broker availability is separate from the exchange used for market data. Import a
broker-confirmed CSV under **Data controls → Broker trading list**. The file must
contain one of these columns:

- `Symbol`
- `Ticker`
- `Yahoo Symbol`
- `yahoo_symbol`

Values must match Stockfinder's Yahoo-compatible symbols, for example `SAP.DE`.
After import, matching candidates are marked **Available**, and unmatched
candidates are marked **Not available**. Before a list is imported, every stock is
marked **Not verified**. Stocks and Industry Rotation provide an independent
broker-availability filter while retaining global market and industry analysis.

ISIN-only broker exports cannot currently be matched because the public universe
does not provide reliable ISIN identifiers. Add a Yahoo-compatible symbol column
before importing such a file.

## External Data Providers

Optional macro-event, news/sentiment, institutional-disclosure, and constituent
providers are discovered through the `stockfinder.providers` Python entry-point
group. Inspect installed capability coverage without fetching provider data:

```bash
stockfinder-providers
```

No external adapter or credential is installed by default. Missing capabilities
return typed empty results with explicit warnings; they never generate synthetic
macro, news, sentiment, flow, or constituent records.

## Container Deployment

Build and run locally:

```bash
docker build -t stockfinder .
docker run --rm -p 8501:8501 -v stockfinder-data:/data stockfinder
```

The container runs as a non-root user, listens on `0.0.0.0`, honors the platform
`PORT` variable, and exposes Streamlit's health endpoint at
`/_stcore/health`. Mount `/data` to retain market histories and user-owned state
between deployments. Without a volume, the app still runs but container state is
ephemeral.

### Streamlit Community Cloud

Create or edit the app with these settings:

- Repository: `cempting/stockfinder`
- Branch: `main`
- Main file path: `streamlit_app.py`

The root entry point adds this repository's `src` directory before importing the
application, preventing a cached or unrelated installed `stockfinder` package from
shadowing the deployed source. After changing the main file path, reboot the app
from **Manage app** to clear the previous Python process.

## Current Features

- Market pulse for major US indices and cross-asset proxies
- Dedicated metals pulse with multi-horizon rankings and evidence breakdowns
- Broad NASDAQ and NYSE scan plus curated local listings from Europe, Asia,
  Asia-Pacific, Canada, Latin America, and Africa
- Unified Stocks workspace for global discovery, deep research, and watchlists
- Composable market, classification, price, setup, trend, and risk filters
- Independent promising-stock filters for heartbeat consolidation, SMA50 crossing
	opportunity, rising SMA50, increasing volume, and optional SMA150 confirmation
- Any/All matching policy to combine promising criteria with OR or AND logic
- Optional cached fundamental enrichment for narrowed stock shortlists
- Always-on 1-week, 1-month, 3-month, and 6-month industry liquidity analysis
- Secondary early-rotation signal for breadth, relative strength, dollar volume,
  and close-location pressure
- Composite liquidity-flow heatmap with all four horizons in each industry
- Winning/losing industry pulse with region-aware rotation filtering
- Heartbeat consolidation screening above a rising SMA150
- Direct drill-down from rotation leaders into Stock research
- Transparent long-swing states and pass/fail rule evidence
- Entry, stop-loss, and risk/capital constrained share calculations
- Six-pillar fundamental scorecard with metric evidence and completeness
- Separate overall quality, observed risk, and technical confirmation scores
- Interactive candlestick, moving-average, and volume charts
- Candidate stops and risk-based position sizing
- Persistent local watchlist and portfolio using SQLite
- Editable geography, regional proxy, rule-profile, and market-control settings
- CSV watchlist export and transparent source/completeness indicators

## Analysis Configuration

Packaged defaults live in `src/stockfinder/default_analysis_config.json`. Changes
made in the **Settings** workspace are saved to `data/analysis_config.json`, or
under `STOCKFINDER_DATA_DIR` when configured. Settings include:

- Listing-region or company-domicile sector and industry grouping
- Region-specific benchmark, sector, and industry ETF/index mappings
- Swing, position, and investing filter profiles
- Defensive, neutral, and supportive exposure and position-risk controls

Changing geography invalidates the processed scan so sectors, industries, and
stocks are rebuilt under the selected hierarchy.

The broad scan uses classified NASDAQ and NYSE rows from Nasdaq's public stock
screener, a curated set of Yahoo-compatible international local-listing symbols,
and batched Yahoo Finance history. Regional industries remain separate so an
industry in Europe is not merged with an identically named US or Asian group.
Exchange and native currency are shown for international candidates. Missing
histories are excluded and reported. The international set is representative,
not exhaustive, and instrument availability depends on the user's broker.

## Market Data Controls

Open **Data controls** in the sidebar to manage broad scans:

- **Refresh now** clears provider and processed-scan caches, reloads exchange
	membership and price history, and rebuilds all rotation results.
- **Extended loading** requests two years of history in 100-symbol batches.
	Standard mode requests one year in 200-symbol batches.
- The scan status shows membership retrieval, exact processed and usable symbol
	counts, industry aggregation, setup filtering, and final coverage.

A completed scan is reused when moving between Market pulse and Rotation
leaders. Data refreshes automatically each day or when **Refresh now** is used.

## Scheduled Alert Delivery

Portfolio Monitor evaluates end-of-day position and watchlist alerts in the app.
The optional `stockfinder-alerts` command evaluates the same rules from persistent
cached data without starting Streamlit. It sends only when the alert set changes,
and sends one recovery message when previously active alerts clear.

Inspect the current report without sending or changing delivery state:

```bash
stockfinder-alerts --dry-run --base-currency EUR
```

SMTP delivery is disabled until these environment variables are supplied:

```bash
export STOCKFINDER_SMTP_HOST=smtp.example.com
export STOCKFINDER_SMTP_PORT=587
export STOCKFINDER_SMTP_STARTTLS=true
export STOCKFINDER_SMTP_USER=alerts@example.com
export STOCKFINDER_SMTP_PASSWORD='use-a-secret-manager'
export STOCKFINDER_ALERT_FROM=alerts@example.com
export STOCKFINDER_ALERT_TO=investor@example.com
export STOCKFINDER_ALERT_BASE_CURRENCY=EUR
stockfinder-alerts
```

Do not store SMTP passwords in repository files. Schedule the command with the
deployment platform, `cron`, or a systemd timer after the daily market scan has
completed. For example, a weekday cron entry can invoke an environment-loading
wrapper at 22:00:

```text
0 22 * * 1-5 /path/to/private/run-stockfinder-alerts
```

The command does not fetch providers. It uses the latest completed scan, local
portfolio/watchlist records, and cached FX histories. Missing scan, quote, or FX
evidence is reported and cannot trigger the corresponding condition. Delivery
state is stored atomically in `data/alert-delivery.json` (or the configured
`STOCKFINDER_DATA_DIR`).

## Backup And Restore

Create a checksum-verified archive of the complete persistent data directory. The
archive must be outside `STOCKFINDER_DATA_DIR` so it cannot include itself.
SQLite state is captured through SQLite's online backup API so an active
application cannot produce a partially copied database:

```bash
stockfinder-backup create ~/Backups/stockfinder-$(date +%F).zip
stockfinder-backup verify ~/Backups/stockfinder-2026-09-20.zip
```

Restore only into a new or empty directory. The command validates every recorded
file size and SHA-256 checksum and rejects unsafe archive paths before writing:

```bash
stockfinder-backup restore \
	~/Backups/stockfinder-2026-09-20.zip \
	~/Restores/stockfinder-2026-09-20
```

Inspect the restored directory before switching `STOCKFINDER_DATA_DIR` to it.
Restore intentionally refuses to overwrite a populated directory. This preserves
the current data set until the restored copy has been verified independently.

Preview and apply local retention without touching unrelated archives:

```bash
stockfinder-backup prune ~/Backups --keep 14 --dry-run
stockfinder-backup prune ~/Backups --keep 14
```

Pruning only considers files matching `stockfinder-*.zip`, keeps at least one,
and removes expired archives oldest-first. Off-machine replication and retention
policies for the remote storage provider remain deployment responsibilities.

## Operational Health

`stockfinder-health` checks persisted analytical state without fetching providers
or modifying application data:

```bash
stockfinder-health
stockfinder-health --json
stockfinder-health --max-scan-age-hours 96 --minimum-coverage-pct 90
```

Checks cover analysis-configuration validity, SQLite integrity, scan age, history
coverage, required snapshot tables, cached risk profiles, model-version presence,
and persisted scan warnings. Exit code `0` means healthy, `1` means one or more
warnings, and `2` means a failed check. The default 96-hour failure threshold
allows for weekends; scans older than half that threshold warn.

Use the existing `/_stcore/health` endpoint for process liveness and this command
for analytical-data health. Monitoring systems can schedule the JSON form and
alert on its exit code independently from the web server.

## Scheduled Market Refresh

`stockfinder-refresh` runs the same broad-market pipeline as the Command Center
without starting Streamlit. It loads membership and daily histories, computes
sector and industry rotation, builds stock candidates and risk profiles, and then
atomically replaces the completed snapshot:

```bash
stockfinder-refresh --mode standard --minimum-coverage-pct 90
stockfinder-refresh --mode extended --minimum-coverage-pct 90
```

Standard mode requests one year in 200-symbol batches; extended mode requests two
years in 100-symbol batches. Exit code `0` means the completed snapshot meets the
coverage threshold, `1` means it was saved but coverage is below the threshold,
`2` means refresh failed before replacement, and `3` means another scheduled
refresh already holds `data/.market-refresh.lock`. The previous snapshot remains
available when computation fails.

Schedule refresh after the relevant markets close. The command's nonblocking
process lock prevents overlapping command runs; the deployment scheduler should
treat exit code `3` as an already-running job. A typical daily sequence is:

1. Run `stockfinder-refresh`.
2. Run `stockfinder-health` and record its JSON output.
3. Run `stockfinder-alerts` if health is acceptable for the deployment policy.
4. Run `stockfinder-backup create` to an off-machine or synchronized location.

Provider rate limits and the breadth of the configured universe determine refresh
duration. Use `--help` to inspect command options without contacting providers.

## Long Swing Rule

Stock research evaluates trend, prior advance, the longest valid 5-, 7-, 10-,
15-, or 20-session consolidation, distance to the base pivot, controlled base
volume, and breakout confirmation. A confirmed breakout must close above the
pivot on at least 1.5 times 50-day average volume and finish in the upper quarter
of its daily range. Price breakouts without enough volume remain visible as an
unconfirmed state rather than being promoted to confirmed signals.

The Risk & trade plan section calculates targets, stop levels, reward/risk, and
position size. For an
entry $E$, stop $S$, account value $A$, and risk percentage $r$:

```text
risk budget = A × r / 100
risk per share = E - S
shares = min(floor(risk budget / risk per share), floor(A / E))
```

The second limit prevents the calculated position from exceeding available
account capital.

## Development

Run the test and lint checks:

```bash
pytest
ruff check .
```

Application code lives under `src/stockfinder`, and tests live under `tests`.
