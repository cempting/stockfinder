# Stockfinder Domain Glossary

This glossary is the canonical vocabulary for product design, data contracts,
analysis, and interface copy. New screens and calculations should use these
terms consistently. The glossary describes decision-support concepts, not
investment advice.

## Knowledge Model

Every value shown by Stockfinder belongs to one of four layers:

1. **Observation**: a reported or directly measured value, such as CPI or a
   closing price.
2. **Derived metric**: a reproducible calculation from observations, such as a
   63-session return or yield-curve spread.
3. **Inference**: an interpretation supported by evidence, such as tightening
   financial conditions or probable accumulation.
4. **Decision control**: a user-configured response, such as reduced maximum
   exposure. A control is not a forecast or trade instruction.

Every observation and derived metric must carry its source, observation time,
retrieval time, frequency, unit, geography, and revision status when relevant.
Every inference must expose its inputs, rule, horizon, and completeness.

## Shared Dimensions

- **As-of time**: when the value was true in the source system.
- **Available-at time**: when the value could first have been known. This is the
  timestamp used to prevent look-ahead bias.
- **Frequency**: intraday, daily, weekly, monthly, quarterly, or event-driven.
- **Horizon**: the period over which evidence is evaluated. Stockfinder uses
  sessions for traded prices and calendar periods for economic series.
- **Geography**: global, region, country, or currency area. Listing region and
  company domicile are separate dimensions.
- **Universe**: the eligible instruments before filters are applied.
- **Benchmark**: the explicit comparison instrument or series.
- **Unit**: percent, percentage points, basis points, index points, currency, or
  ratio. Units are never inferred from a label.
- **Vintage**: the version of a revisable economic observation available at a
  particular time.
- **Completeness**: available required evidence divided by total required
  evidence. Missing evidence is not neutral evidence.
- **Confidence**: strength of support after considering source quality,
  freshness, agreement, and sample size. Confidence is distinct from score.

## Economic Cycle

### Growth And Activity

- **Gross domestic product (GDP)**: inflation-adjusted value of final output.
  Use real GDP growth for cycle comparisons; distinguish quarter-over-quarter
  annualized growth from year-over-year growth.
- **Nowcast**: model estimate of current-period growth before the official
  release. It is an inference and must name the model and update time.
- **Purchasing Managers' Index (PMI)**: diffusion index of business conditions.
  Values above 50 indicate more respondents reporting expansion than
  contraction; they do not measure the magnitude of output growth.
- **Industrial production**: real output of manufacturing, mining, and
  utilities.
- **Retail sales**: consumer-goods spending. Nominal headline values can rise
  because of inflation, so real or volume measures should be preferred where
  available.
- **Economic surprise**: standardized difference between a release and the
  contemporaneous consensus forecast. It measures expectations error, not the
  absolute health of the economy.

### Inflation

- **CPI / HICP**: consumer-price indices. HICP is the harmonized measure used in
  the European Union.
- **PCE price index**: US consumption-price measure covering a broader and
  changing expenditure basket than CPI.
- **Headline inflation**: total index change. **Core inflation** excludes
  selected volatile categories and must state which exclusions apply.
- **Producer prices**: prices received by domestic producers; not a direct
  measure of consumer inflation.
- **Breakeven inflation**: nominal government yield minus inflation-linked yield
  at a matching maturity. It includes inflation expectations, risk premia, and
  liquidity effects.
- **Inflation momentum**: recent annualized change over a short window. The
  window and seasonal adjustment must be explicit.

### Labor And Households

- **Unemployment rate**: unemployed people as a share of the labor force.
- **Labor-force participation**: labor force as a share of the eligible
  population.
- **Payroll growth**: change in employed payroll positions; revisions are common.
- **Initial jobless claims**: weekly new claims for unemployment benefits and a
  high-frequency indicator of labor-market deterioration.
- **Wage growth**: change in compensation. Composition effects and the selected
  series must be disclosed.
- **Consumer sentiment**: survey measure of household perceptions and
  expectations. Keep the University of Michigan and Conference Board series
  separate because their samples and methods differ.
- **Consumer confidence versus sentiment**: related survey concepts, not
  interchangeable series. Analyze level, trend, expectations, and the gap
  between present and expected conditions separately.

### Rates, Liquidity, And Policy

- **Policy rate**: central bank's administered target or reference rate.
- **Government yield**: market yield for a specified sovereign and maturity.
- **Real yield**: nominal yield less an inflation measure or the yield on an
  inflation-linked bond. The chosen definition must be explicit.
- **Yield curve**: yields across maturities for one issuer and instrument type.
- **Term spread**: long-maturity yield minus short-maturity yield, expressed in
  basis points. Inversion is a negative spread, not by itself a timing signal.
- **Financial conditions**: composite evidence from rates, credit, equities,
  currency, and lending conditions. Provider methodologies are not fungible.
- **Central-bank balance sheet**: assets held by a central bank. Changes are
  policy evidence, not a direct one-for-one measure of market liquidity.
- **Money supply**: a defined stock of liquid money, such as M2. Definitions
  differ by jurisdiction.

### Credit

- **Credit spread**: corporate yield minus a maturity-matched government or swap
  yield, expressed in basis points.
- **Investment grade / high yield**: rating-based credit segments. Provider
  rating rules must be identified.
- **Default rate**: share of issuers or debt entering default over a stated
  period.
- **Lending standards**: survey evidence of bank willingness to lend. It is
  delayed and often directional rather than a transaction measure.

## Markets And Cross-Asset Evidence

- **Market regime**: horizon-specific classification of risk appetite and stress
  from transparent evidence. It is an inference, never a single observed fact.
- **Risk-on / mixed / risk-off**: labels for supportive, conflicting, or
  defensive market evidence. Labels must include the rule version and as-of time.
- **Trend**: direction and persistence of a price series under a named method and
  horizon.
- **Momentum**: rate of price change over a defined lookback.
- **Relative strength**: return of an instrument minus or divided by its stated
  benchmark return. This is not the RSI oscillator.
- **Breadth**: share of eligible constituents satisfying a condition. Publish
  the numerator, denominator, condition, and universe coverage.
- **Market liquidity**: ability to transact without material price impact.
  Trading volume and dollar volume are proxies, not complete measurements.
- **Fund flow**: subscriptions and redemptions into an investment vehicle. Do
  not label signed price-volume estimates as fund flows.
- **Accumulation / distribution**: inference from persistent price, volume, and
  breadth behavior. It does not identify the buyers or sellers.
- **Correlation**: standardized co-movement over a stated sample and frequency;
  it is unstable and does not imply causation.
- **Drawdown**: percentage decline from a prior running peak.

### Volatility

- **Realized volatility**: annualized standard deviation of historical returns
  over a stated window and sampling frequency.
- **Implied volatility**: option-price-implied estimate under a named model,
  maturity, and strike convention.
- **VIX**: Cboe measure of the market's risk-neutral expectation of approximately
  30-day S&P 500 variance, derived from SPX options. It is not directly the
  expected percentage move and is not generic global volatility.
- **Volatility term structure**: implied volatility across maturities.
  Front-month elevation relative to later maturities can indicate near-term
  stress; contract and roll conventions matter.
- **Volatility risk premium**: implied volatility minus subsequent or expected
  realized volatility under an explicit comparison method.
- **ATR**: average true range, a price-unit measure of recent trading range. ATR
  is not annualized volatility.

### Currencies And Commodities

- **Trade-weighted currency index**: currency value against a weighted basket;
  disclose basket and weighting method.
- **Dollar strength**: change in an explicit USD index or currency pair, not a
  generic statement.
- **Spot / futures price**: current delivery price versus a standardized forward
  contract. They are not interchangeable.
- **Contango / backwardation**: futures curve with later contracts above / below
  nearer contracts. It can reflect financing, storage, scarcity, and convenience
  yield.
- **Gold, oil, industrial metals**: cross-asset evidence whose interpretation is
  conditional on real yields, currency, supply, and growth. Direction alone does
  not determine a regime.

## Geography, Sector, And Instruments

- **Listing region**: region of the exchange listing used for market data.
- **Company domicile**: legal or operational home assigned by the classification
  source.
- **Economic exposure**: geographic distribution of revenue, assets, or costs.
  It must not be inferred from listing region alone.
- **Regional benchmark**: configured index or ETF proxy used to compare a
  region. A proxy is not the complete local market.
- **Sector / industry**: classification levels from an identified taxonomy and
  version, such as GICS. Similar labels from different taxonomies may differ.
- **Security**: generic financial instrument with a stable internal identifier.
- **Ticker**: venue-specific symbol that can be reused or changed; ticker alone
  is not a durable identity.
- **Stock / ETF / fund / index / future / commodity / FX pair**: distinct
  instrument types with different fields, calendars, and tradability.
- **Tradability**: verified availability through the user's broker, separate
  from analytical inclusion.

## Company And Security Evidence

- **Fundamental quality**: transparent assessment of growth, profitability, cash
  generation, balance-sheet strength, valuation, and capital allocation.
- **Valuation**: price relative to an explicitly defined fundamental measure,
  history, or peer group. Cheapness is not quality.
- **Earnings quality**: degree to which reported earnings are supported by cash
  flow and repeatable operations.
- **Technical confirmation**: price, trend, volume, and relative-strength
  evidence used for timing after suitability checks.
- **Setup**: named, horizon-specific collection of conditions. A passing setup
  is not an order.
- **Observed risk**: measured volatility, drawdown, liquidity, concentration,
  and financial risk. It is distinct from uncertainty and from risk tolerance.
- **Candidate stop**: analytical invalidation level under a named method. It is
  not guaranteed execution protection.
- **Position risk**: planned loss at the candidate stop divided by portfolio
  value.

## News, Social, And Positioning

- **News event**: sourced report with publication time, affected entities,
  headline, URL, and event type. Duplicate syndications should form one cluster.
- **News sentiment**: model estimate of tone toward an entity or topic. Store
  model name/version and confidence; tone is not expected price direction.
- **Event impact**: measured abnormal market response after an event. It must be
  separated from sentiment and must use an explicit benchmark/window.
- **Social mention**: public post that references an entity through a resolved
  ticker, cashtag, name, or URL.
- **Social sentiment**: model classification of resolved social mentions. Report
  volume, unique authors, confidence, language coverage, and bot/spam filtering.
- **Attention / buzz**: unusual mention volume relative to that entity's own
  baseline. Raw mention counts are not comparable across securities.
- **X ticker / cashtag**: a token such as `$AAPL`. It is ambiguous until resolved
  against exchange, company, language, and context; unresolved tokens are not
  evidence.
- **Source credibility**: declared assessment of source history and identity.
  Follower count is not credibility.
- **Positioning**: evidence about existing exposures, such as futures commitment,
  options open interest, short interest, or disclosed holdings. Each source has
  different delay and coverage.
- **Institutional holdings**: reported positions as of a filing date. SEC Form
  13F is delayed holdings disclosure, not real-time institutional flow.
- **Insider transaction**: reported trade by a covered insider. Filing time,
  transaction time, transaction code, and whether the trade was pre-arranged
  must remain visible.

## Evidence Quality Rules

- A missing value is `unknown`, never zero, false, neutral, or unchanged.
- Conflicting credible sources remain visible; they are not silently averaged.
- Revised macro data retains both original vintage and latest value.
- Survey, model, market, filing, and accounting evidence remain separately
  labeled.
- Price-volume behavior may support a flow inference but cannot prove actor
  identity.
- News and social scores cannot alter a regime or security score until a named,
  tested rule explicitly includes them.
- A score always publishes components, weights, completeness, rule version, and
  as-of time.

## Naming Conventions

Canonical DSL identifiers use lowercase `snake_case`. Display labels may be
localized, but canonical IDs remain stable. Metric IDs follow
`namespace.subject.measure.variant`, for example:

- `macro.us.inflation.cpi_core_yoy`
- `rates.us.treasury.spread_10y_2y`
- `market.us_equity.volatility.vix_level`
- `breadth.us_equity.above_sma150_pct`
- `news.security.sentiment_7d`
- `social.security.attention_zscore_24h`

Units, transformations, and horizons are fields, not hidden inside IDs, except
where the variant is part of the established economic series definition.