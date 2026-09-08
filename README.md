# Stockfinder

A Streamlit decision workspace for market regime analysis, sector rotation,
fundamental and risk evaluation, and technical confirmation.

The product vision and requirements gathered during discovery are documented
in [docs/product-vision.md](docs/product-vision.md).

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
- CSV watchlist export and transparent source/completeness indicators

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
