"""Technical descriptions shown from dashboard widget info controls."""

from stockfinder.presentation.dashboard import WidgetSpec

SECTIONS = ("**Data origin**", "**Calculation**", "**Criteria**", "**Limitations**")

WIDGET_HELP = {
    "market_regime": """
**Data origin**

One year of daily adjusted OHLCV history for SPY, IWM, HYG, IEF, UUP, and
`^VIX`, loaded from the persistent Yahoo Finance cache and refreshed from Yahoo
Finance when stale.

**Calculation**

The regime score counts four binary checks: SPY above a rising SMA150, IWM
outperforming SPY over 63 sessions, HYG outperforming IEF over 63 sessions, and
VIX below its SMA50. The selected regime loads its exposure, per-position risk,
and entry policy from analysis configuration.

**Criteria**

Three or four checks means Risk-on, two means Mixed, and zero or one means
Risk-off. Separate stress triggers are SPY drawdown at or below -10%, annualized
20-day SPY volatility at or above 25%, VIX at or above 25, HYG lagging IEF by at
least 2% over 21 sessions, and UUP gaining at least 3% over 21 sessions. Zero,
one, two-to-three, or four-plus triggers map to Normal, Monitor, Cautious, or
Defensive guidance.

**Limitations**

ETF and index prices are market proxies. The score does not include macro
releases, central-bank decisions, news, positioning, or sentiment unless an
external provider is installed and a separate widget uses it.
""",
    "cross_asset_conditions": """
**Data origin**

One year of daily adjusted history for SPY, IWM, HYG, IEF, TLT, UUP, GLD, DBC,
and `^VIX`, or the symbols overridden in the widget settings.

**Calculation**

Returns use 21, 63, and 126 trading sessions as 1M, 3M, and 6M approximations.
Annualized volatility is daily return standard deviation times the square root of
252. The underlying trend score awards 20 points for each positive horizon, price
above SMA150, and a rising SMA150.

**Criteria**

HYG minus IEF over 3M is Supportive above zero and Defensive otherwise. IWM minus
SPY over 3M is Broadening above zero and Narrow otherwise. A negative 1M VIX
return is Falling; zero or positive is Rising.

**Limitations**

These are liquid price proxies, not direct economic releases, yield curves, fund
subscriptions, futures positioning, or institutional transactions.
""",
    "regional_markets": """
**Data origin**

Configured regional ETF/index symbols from `regional_proxies`, one year of daily
history for each benchmark, and industry internals from the latest completed broad
scan. The configured Global benchmark, normally ACWI, is the relative baseline.

**Calculation**

The chart shows 63-session return and its difference from the global benchmark.
Trend score combines positive 21/63/126-session returns, price above SMA150, and
a rising SMA150 at 20 points each. Internal breadth, liquidity, and rotation are
means across the region's scanned industries.

**Criteria**

Confirmed leader requires trend at least 80, positive 3M relative return, and
breadth at least 60%. Narrow leader meets the first two but not breadth. Internal
recovery requires breadth and internal rotation at least 60. Broad weakness
requires trend below 40, negative relative return, and breadth below 40%.

**Limitations**

Benchmark evidence can exist without matching constituents. In that case the
label is Benchmark only. Coverage depends on configured proxies and scan members.
""",
    "rotation_explorer": """
**Data origin**

Daily Close and Volume histories for classified stocks with at least 170 sessions,
grouped by configured region, sector, and industry in the latest scan.

**Calculation**

Industry returns use 5, 21, 63, and 126 sessions. Liquidity combines normalized
dollar-volume change (-30% to +50%) and directional dollar-volume balance (-20%
to +20%). Rotation score is the mean of normalized multi-horizon momentum,
liquidity composite, and member breadth above a rising SMA150. Sector values are
member-weighted industry aggregates. Early rotation equally weights SMA20 breadth
acceleration, relative-strength inflection, positive dollar volume, and close
location pressure.

**Criteria**

Gaining requires positive momentum change, liquidity change, and recent flow;
Losing requires all three negative. Winning also requires aggregate price above a
rising SMA150, positive 3M and 6M returns, at least three liquidity horizons at 50
or higher, and breadth at least 50%. Broad industry leadership requires rotation
at least 65, liquidity and breadth at least 60, positive flow, and three members.
Early Emerging requires score at least 65 with three components at least 60;
Building requires 55 with two confirmations.

**Limitations**

Directional flow is inferred from price and volume. Small groups are explicitly
labeled Thin leadership and are not equivalent to broad industry participation.
""",
    "liquidity_breadth": """
**Data origin**

Industry aggregates from the latest scan, filtered by linked region and sector.
Inputs are member Close and Volume histories over 5, 21, 63, and 126 sessions.

**Calculation**

Dollar volume is Close times Volume. For each horizon, recent and baseline
segments measure dollar-volume growth; up-day minus down-day dollar volume divided
by their total produces directional flow balance. Liquidity score is the mean of
volume-growth normalized from -30% to +50% and flow normalized from -20% to +20%.
Breadth is the share of members above a rising SMA150.

**Criteria**

The heatmap midpoint is 50 for liquidity and zero for directional flow. The view
shows the 18 industries with the highest liquidity composite after context filters.

**Limitations**

Flow is an inference from end-of-day price and volume, not reported ETF flows,
order flow, dark-pool activity, or institutional transactions.
""",
    "ranked_stocks": """
**Data origin**

Stock candidates from the latest completed scan, optional cached Yahoo company
fundamentals, cached price-risk profiles, the selected rule profile, and an
optional user-imported broker symbol list.

**Calculation**

Hard gates evaluate setup score, annualized volatility, safety (`100 - observed
risk`), optional SMA150 trend, available fundamental quality, and broker status.
The weighted profile score combines setup, safety, fundamentals, and binary
SMA150 trend using editable weights; missing components are reweighted and the
available-weight percentage is shown as Evidence coverage.

**Criteria**

Thresholds come from Swing, Position, or Investing configuration. Missing setup
or volatility fails its hard gate; missing SMA150 fails when required. Missing
fundamental or safety evidence is not invented. The weighted minimum is enforced
only when explicitly enabled. Broker-only mode requires an exact normalized symbol
match. Ranking can use setup, weighted score, safety, SMA50 distance, base length,
SMA50 slope, or volume-interest ratio.

**Limitations**

An empty pass set is not relaxed silently: excluded candidates remain visible with
their exact failure reasons. Broker membership confirms symbol availability, not
order eligibility, market access, liquidity, or suitability.
""",
    "instrument_analysis": """
**Data origin**

Two years of adjusted daily OHLCV history and cached/refreshed Yahoo Finance
company profile data for the linked or entered stock, ETF, or index symbol.

**Calculation**

Price and daily change come from the latest two closes. Quality is the mean of
available normalized fundamental pillars. Observed risk averages annualized
volatility, maximum drawdown, debt-to-equity, and inverse current-ratio evidence;
Safety displays `100 - risk`. Technical score averages price above SMA50/SMA150,
moving-average direction, heartbeat structure, and relative 20-day volume.

**Criteria**

Positive score labels begin at 65 and Strong at 80; Neutral begins at 45. Risk is
Low below 35, Moderate from 35, Elevated from 60, and High from 80. Technical
history needs at least 50 sessions; SMA150 components require at least 150.

**Limitations**

Missing inputs lower completeness. Provider fallback status and source are shown;
quality, safety, and technical evidence remain independent rather than one rating.
""",
    "security_score_evidence": """
**Data origin**

Uses the same two-year security analysis as Instrument Analysis. Fundamental
evidence comes from reported Yahoo profile fields; risk and technical evidence
come from daily adjusted price and volume history.

**Calculation**

Fundamental pillars average only available normalized metrics: margins and
returns, growth, cash flow, leverage/liquidity, valuation, and dividends. Risk
uses annualized volatility, maximum drawdown, debt-to-equity, and inverse current
ratio. Technical evidence uses SMA50/SMA150 position and slope, heartbeat price
structure, and volume participation. Risk components are inverted in this widget
so a higher displayed value always means greater safety.

**Criteria**

Components and totals are clamped to 0–100 and displayed on a 1–10 scale. Positive
labels are Weak below 45, Neutral from 45, Positive from 65, and Strong from 80.
Observed-risk labels are Low below 35, Moderate from 35, Elevated from 60, and
High from 80.

**Limitations**

The displayed completeness is the percentage of expected components supported by
available data. Missing values are excluded from averages, not estimated.
""",
    "peer_comparison": """
**Data origin**

The selected instrument's classification comes from the latest scan. Up to five
other stocks from the same listing region and industry are chosen, ordered by
available market capitalization. The benchmark follows configured industry,
sector, then regional fallback. Price history covers six months.

**Calculation**

Each nonempty Close series is normalized to 100 at its first available date.
Six-month return is the final normalized value minus 100; relative return is the
selected instrument return minus the configured benchmark return.

**Criteria**

Peers must match both listing region and industry and exclude the selected symbol.
No broader peer group is substituted when fewer than five members are available.

**Limitations**

An ETF or index outside the classified stock universe can be analyzed elsewhere
but cannot receive inferred peers. Missing histories are omitted and source labels
remain visible.
""",
    "trade_plan": """
**Data origin**

Two years of daily adjusted OHLCV, ATR14, the recent 20-day low, SMA50, detected
5/7/10/15/20-session consolidation base, and optional analyst mean target from the
company profile.

**Calculation**

Candidate stops are entry minus an ATR multiple, structural base stop, SMA50,
20-day swing low, and a trailing percentage. Position size is the smaller of
`floor(risk budget / risk per share)` and `floor(account value / entry)`. Targets
include 2R, measured move, and analyst mean when reported. Reward/risk is target
distance divided by stop distance.

**Criteria**

Conservative/Balanced/Aggressive defaults are respectively 1.5/2.0/2.5 ATR,
6/9/12% trailing stop, and 0.25/0.5/1.0% account risk. The swing setup requires at
least 170 sessions and tests SMA trends, a prior advance of at least 10%, base
width no more than 15%, controlled base volume no more than 1.10 times prior
volume, proximity within 5% below pivot, and breakout confirmation above pivot on
at least 1.5 times volume with a close in the upper quartile. Plans below 2R warn.

**Limitations**

Levels are analytical planning aids, not orders. Slippage, taxes, gaps, lot sizes,
broker rules, and portfolio correlation are not modeled.
""",
    "rule_profile_editor": """
**Data origin**

Reads and atomically writes the versioned analysis configuration used by stock
screening. Profiles are Swing, Position, and Investing unless the configuration
defines others.

**Calculation**

Hard gates cover minimum setup, maximum annualized volatility, minimum safety,
minimum fundamental quality, and optional price above SMA150. Weighted composition
normalizes editable setup, safety, fundamental, and trend weights across available
evidence and records evidence coverage separately.

**Criteria**

All scores, thresholds, and weights must be between 0 and 100, with at least one
positive weight. Momentum-led uses 50/15/10/25 weights; Balanced uses 35/25/25/15;
Quality-first uses 20/25/40/15. Applying a preset enables the weighted minimum;
manual edits remain possible afterward.

**Limitations**

Changes affect future screen evaluations immediately but do not alter historical
snapshots or constitute an investment mandate.
""",
    "portfolio_exposure": """
**Data origin**

User-owned SQLite positions and watchlist records, latest cached scan prices and
risk profiles, scan classifications, and verified Yahoo direct or inverse FX
pairs. Position currency is explicit; the portfolio base currency is selectable.

**Calculation**

Local cost and market value are quantity times entry and latest price, then
multiplied by the verified FX rate. Allocation uses converted market value.
Unrealized P&L is converted market value minus converted cost. Weighted safety is
market-value-weighted `100 - observed risk`; gross exposure is converted market
value divided by entered account value.

**Criteria**

Gross exposure is compared with the current Risk-on/Mixed/Risk-off configured
maximum. The largest position is the maximum converted allocation. Legacy rows
migrate to USD; exchange suffixes provide editable currency suggestions for new
positions.

**Limitations**

Synthetic FX fallback data is rejected. Quoted positions without verified FX are
excluded and counted. Prices are end-of-day cached evidence, not live broker marks.
""",
    "alert_center": """
**Data origin**

Persistent positions and watchlist plans, latest cached prices and market-risk
profiles, and alert thresholds in the validated analysis configuration.

**Calculation**

Position return compares latest price with entry. Concentration uses portfolio
allocation. Safety is `100 - observed risk`. Watchlist comparisons use planned
entry, target, and invalidation stop.

**Criteria**

Defaults are maximum position allocation 25%, minimum safety 40, position loss
10%, and entry proximity within 2%. Stop breaches and position losses are
Critical; concentration and safety breaches are Warning; target hits and entry
proximity are Review. Thresholds are editable and atomically persisted.

**Limitations**

Only symbols with cached evidence can trigger relevant conditions. The widget is
evaluated on render and is not real-time. Optional scheduled email delivery is a
separate command and uses no credentials unless explicitly configured.
""",
}


def widget_methodology(spec: WidgetSpec) -> str:
    """Return technical help for one configured widget instance."""
    text = WIDGET_HELP.get(spec.widget_type)
    if text is None:
        return (
            "**Data origin**\n\nNot documented for this custom widget.\n\n"
            "**Calculation**\n\nDefined by the installed widget renderer.\n\n"
            "**Criteria**\n\nInspect its deployment configuration.\n\n"
            "**Limitations**\n\nNo built-in methodology is registered."
        )
    if spec.widget_type == "security_score_evidence":
        dimension = str(spec.settings.get("dimension", "technical")).title()
        return f"**Configured dimension:** {dimension}\n\n{text.strip()}"
    return text.strip()