# Stockfinder Analysis DSL

Status: design contract with a partial runtime implementation. JSON Schema,
safe YAML loading, semantic validation, and three-valued condition evaluation
are implemented; time-series execution and complete evidence traces are pending.

The Stockfinder analysis DSL defines *what evidence means* and *how a conclusion
is reached* independently of providers and interface layout. It is declarative,
versioned, horizon-specific, and suitable for historical replay.

## Design Goals

- Keep observations, calculations, inferences, and controls separate.
- Make every conclusion explainable from named evidence.
- Treat missing, stale, and conflicting data explicitly.
- Prevent look-ahead bias through `available_at` timestamps and data vintages.
- Keep provider-specific field names outside analysis rules.
- Allow the same definitions to drive dashboards, screeners, alerts, and tests.
- Never allow news or social evidence to influence a result implicitly.

## Document Shape

DSL documents use YAML for authoring and carry a semantic version. The runtime
validates documents against a versioned schema before evaluation.

```yaml
dsl: stockfinder/v1
kind: analysis_pack
id: global_top_down
name: Global top-down analysis
version: 1.0.0
definitions: []
signals: []
regimes: []
policies: []
```

`id` values are stable lowercase `snake_case`. `name` is display text. `version`
changes whenever evaluation semantics change.

## Core Types

### Entity

An entity is the subject of evidence.

```yaml
entity:
  type: region
  id: united_states
```

Initial entity types are `global`, `region`, `country`, `currency_area`,
`sector`, `industry`, `security`, `instrument`, `issuer`, and `portfolio`.
Securities use stable internal IDs and map to one or more venue-specific tickers.

### Evidence Definition

A definition maps a canonical metric to required metadata and a provider
capability. It does not select a particular commercial provider.

```yaml
- id: market.us_equity.volatility.vix_level
  layer: observation
  subject: {type: region, id: united_states}
  capability: market_history
  instrument: {type: index, symbol: "^VIX"}
  field: close
  unit: index_points
  frequency: daily
  freshness: 2d
  direction: conditional
```

Required evaluation metadata is:

```yaml
evidence:
  metric_id: market.us_equity.volatility.vix_level
  value: 18.4
  unit: index_points
  observed_at: 2026-10-09T20:00:00Z
  available_at: 2026-10-09T20:15:00Z
  retrieved_at: 2026-10-09T20:20:00Z
  source: yahoo
  source_url: null
  vintage: null
  quality: observed
  status: available
```

`status` is one of `available`, `missing`, `stale`, `conflicting`, or `invalid`.
`quality` is one of `reported`, `observed`, `derived`, `estimated`, or `inferred`.

### Derived Metric

Derived metrics use a restricted expression tree rather than arbitrary Python.

```yaml
- id: rates.us.treasury.spread_10y_2y
  layer: derived
  expression:
    subtract:
      - {metric: rates.us.treasury.yield_10y}
      - {metric: rates.us.treasury.yield_2y}
  unit: basis_points
  frequency: daily
  minimum_inputs: 2
```

Initial numeric operators are `add`, `subtract`, `multiply`, `divide`, `min`,
`max`, and `abs`. Time-series operators are:

- `change`: absolute change over a window.
- `pct_change`: percentage return over a window.
- `mean`, `median`, `sum`, `stddev`: rolling statistic over a window.
- `annualized_volatility`: return standard deviation with an explicit annualizer.
- `sma`, `ema`: moving average with an explicit window.
- `slope`: normalized linear slope over a window.
- `zscore`: current value against an explicit trailing baseline.
- `drawdown`: decline from the running peak over a window.
- `spread`: difference between two aligned series.
- `breadth`: satisfied members divided by eligible members.

Windows use trading sessions (`21s`) or calendar durations (`7d`, `3m`, `1y`).
The evaluator rejects ambiguous bare numbers.

### Condition And Signal

A signal converts evidence into a three-valued conclusion: `true`, `false`, or
`unknown`. Unknown evidence never passes or fails silently.

```yaml
- id: us_vix_stress
  name: Elevated US implied volatility
  horizon: swing
  when:
    gte:
      - {metric: market.us_equity.volatility.vix_level}
      - 25
  requires:
    freshness: 2d
    completeness: 1.0
  emit:
    true: stressed
    false: normal
    unknown: unavailable
```

Comparison operators are `gt`, `gte`, `lt`, `lte`, `eq`, `between`, `above`,
and `below`. Logical operators are `all`, `any`, `not`, and `at_least`.
Crossing operators are `crosses_above` and `crosses_below`. Every comparison
must resolve compatible units.

### Score

Scores normalize heterogeneous components but preserve their evidence.

```yaml
- id: us_market_stress_score
  horizon: position
  score:
    range: [0, 100]
    missing: reduce_completeness
    components:
      - {signal: us_vix_stress, weight: 30}
      - {signal: us_equity_drawdown_stress, weight: 30}
      - {signal: us_credit_stress, weight: 25}
      - {signal: us_dollar_stress, weight: 15}
  requires:
    minimum_completeness: 0.75
```

Weights describe contribution, not confidence. An evaluator returns value,
label, components, completeness, confidence, rule version, and as-of time.

### Screen

A screen keeps eligibility separate from ranking. Each filter is independently
enabled, `qualify.mode` defines how enabled filters establish eligibility, and a
separate score ranks only the qualifying entities.

```yaml
- id: industry_constituent_opportunities
  entity_type: security
  horizon: swing
  scope:
    within: {selected: industry}
  filters:
    - {signal: constructive_consolidation, enabled: true}
    - {signal: crosses_sma50_on_volume, enabled: true}
    - {signal: rising_sma50, enabled: true}
    - {signal: above_rising_sma150, enabled: false}
  qualify:
    mode: any
    unknown: not_qualified
    minimum_available_filters: 1
  rank:
    score: swing_opportunity_rank
    order: descending
  compare_with:
    - industry_peers
    - industry_proxy
    - regional_benchmark
    - own_history
  change_window:
    default: 1s
    presets: [1s, 5s, 21s]
    editable: true
```

`qualify.mode` is `any`, `all`, or `at_least`. Unknown filters do not pass, but
remain distinct from false filters in the result. A screen emits pass/fail,
qualifying filters, failed filters, unavailable filters, actual values and
thresholds, completeness, peer rank, benchmark differences, and change since
the previous comparable scan.

`change_window` is a profile-level setting used by industry and constituent
screens. `1s`, `5s`, and `21s` are displayed as Daily, Weekly, and Monthly. The
default is `1s`, one completed trading session. Custom values use trading
sessions so regional holidays do not turn equal labels into unequal samples.
Every movement result records and displays its effective window.

Industry screens run before their constituent security screens. A security
screen must retain the selected industry and regional context in its evidence
trace.

Continuous ranking components can reward evidence such as consolidation length
or volume recency after qualification. Components must define saturation or caps
so stale consolidations and isolated volume events cannot gain unlimited score.

### Regime

A regime maps named evidence to mutually exclusive states with deterministic
precedence.

```yaml
- id: us_risk_regime
  name: US risk regime
  horizon: position
  states:
    - id: defensive
      priority: 30
      when: {gte: [{score: us_market_stress_score}, 65]}
    - id: supportive
      priority: 20
      when:
        all:
          - {lte: [{score: us_market_stress_score}, 35]}
          - {signal: us_equity_trend_supportive, is: true}
    - id: neutral
      priority: 10
      when: {otherwise: true}
  on_unknown: unavailable
```

States are evaluated by descending priority. `otherwise` is valid only for the
lowest-priority state. Regime results list both supporting and contradicting
evidence.

### Policy

A policy translates an inference into user-owned controls. It never places an
order.

```yaml
- id: position_risk_controls
  applies_to: {profile: Position}
  select:
    regime: us_risk_regime
  controls:
    defensive:
      max_gross_exposure_pct: 35
      risk_per_position_pct: 0.50
      new_entry_policy: exceptional_only
    neutral:
      max_gross_exposure_pct: 65
      risk_per_position_pct: 0.75
      new_entry_policy: selective
    supportive:
      max_gross_exposure_pct: 90
      risk_per_position_pct: 1.00
      new_entry_policy: profile_passes
  unavailable:
    max_gross_exposure_pct: 35
    risk_per_position_pct: 0.50
    new_entry_policy: no_new_entries
```

## Horizons

Rules declare exactly one analysis horizon:

- `intraday`: live or delayed intraday evidence. Not supported by the current
  end-of-day data pipeline.
- `swing`: approximately days to weeks.
- `position`: approximately weeks to months.
- `investing`: approximately quarters to years.

Definitions can be shared, but thresholds and rules cannot silently blend
horizons. UI labels must show the active horizon.

## Top-Down Namespace

The initial canonical namespaces are:

| Namespace | Subject | Examples |
| --- | --- | --- |
| `macro` | Growth, inflation, labor, surveys | GDP, CPI, PMI, consumer sentiment |
| `policy` | Central banks and fiscal events | Policy rate, balance sheet, meetings |
| `rates` | Nominal/real yields and curves | 10Y yield, 10Y-2Y spread |
| `credit` | Spreads, defaults, lending | HY spread, HYG-IEF proxy |
| `market` | Price and cross-asset state | Trend, momentum, VIX, drawdown |
| `breadth` | Participation | Above-SMA breadth, advance/decline |
| `flow` | Reported or inferred movement | ETF subscriptions, price-volume proxy |
| `fundamental` | Issuer quality and valuation | ROIC, FCF margin, net debt |
| `technical` | Setup and timing evidence | SMA trend, heartbeat, relative strength |
| `news` | Deduplicated published events | Tone, novelty, event impact |
| `social` | Resolved public attention | Mention z-score, author breadth |
| `positioning` | Existing market exposure | COT, short interest, disclosed holdings |
| `risk` | Security and portfolio risk | ATR, volatility, concentration |

Provider capabilities should evolve toward these namespaces. Current plugin
capabilities map as follows:

- `macro_events` supplies event observations under `macro` or `policy`.
- `macro_series` supplies vintage-aware numeric observations.
- `news_sentiment` supplies sourced records under `news`.
- `social_sentiment` supplies resolved attention and sentiment records under
  `social`.
- `fund_flows` supplies reported vehicle flows under `flow`.
- `institutional_flows` supplies delayed disclosures under `positioning`; a
  provider must not relabel holdings as real-time flow.
- `company_estimates`, `insider_transactions`, `options_activity`, and
  `block_activity` supply separately labeled enhancement evidence.
- `constituents` supplies entity classification and universe membership.
- Existing market-history access supplies `market`, `breadth`, `technical`, and
  price-derived `risk` evidence.
- Every capability returns a schema-correct unavailable result until a provider
  is installed; missing external evidence never becomes a neutral value.

## News And Social Example

Alternative data remains separate from the core score until validated.

```yaml
- id: social_security_attention_spike
  horizon: swing
  when:
    all:
      - {gte: [{metric: social.security.attention_zscore_24h}, 3.0]}
      - {gte: [{metric: social.security.unique_authors_24h}, 25]}
      - {gte: [{metric: social.security.resolution_confidence}, 0.90]}
  requires:
    freshness: 2h
    completeness: 1.0
  tags: [experimental, context_only]
```

`context_only` signals can be displayed and backtested but cannot be referenced
by a regime, score, screener exclusion, or policy. Promotion requires a recorded
validation decision and DSL version change.

## Evaluation Semantics

1. Resolve entities and align calendars/time zones.
2. Select only evidence whose `available_at` is at or before evaluation time.
3. Apply vintage policy (`as_known_then` for backtests, `latest` for current
   descriptive views unless explicitly overridden).
4. Validate units, freshness, minimum history, and source status.
5. Calculate derived metrics without forward filling across prohibited gaps.
6. Evaluate conditions using three-valued logic.
7. Calculate completeness and confidence separately from score.
8. Emit an evidence trace containing every input and intermediate result.

Logical behavior with unknown values is conservative:

| Expression | Result |
| --- | --- |
| `all(true, unknown)` | `unknown` |
| `all(false, unknown)` | `false` |
| `any(true, unknown)` | `true` |
| `any(false, unknown)` | `unknown` |
| `not(unknown)` | `unknown` |

## Validation Rules

The future schema and parser must reject a document when:

- an ID is duplicated or a reference cannot be resolved;
- units or entity types are incompatible;
- a rule has no horizon or version;
- a duration or session window is ambiguous;
- state priorities conflict or more than one fallback exists;
- weights are negative or do not sum to 100;
- a policy has no conservative `unavailable` behavior;
- a derived or inferred value lacks source evidence;
- a non-experimental rule references an experimental/context-only signal;
- backtest evaluation uses evidence not yet available at that historical time.

## Redesign Contract

The redesigned application should be generated around questions, not around raw
data categories:

1. **What is the environment?** Macro, policy, rates, credit, and cross-asset
   regime with conflicts and data freshness.
2. **Where is strength emerging?** Region, sector, industry, breadth, relative
   strength, and liquidity evidence.
3. **What is investable?** Tradability, quality, valuation, observed risk, and
   completeness.
4. **Is timing confirmed?** Horizon-specific setup, trend, volume, and event
   context.
5. **What can invalidate the thesis?** Risks, upcoming events, candidate stops,
   and contradictory evidence.
6. **What action is allowed?** User-owned exposure and position-risk controls.

Each view consumes DSL outputs and their evidence traces. Presentation code
must not recreate thresholds or scoring logic.

Saved decisions retain the analysis-pack version, active preset and overrides,
screen result, evidence timestamps, selected comparisons, entry plan, exit-plan
candidates, notes, and optional rejection reason. This immutable rule snapshot
allows a past decision to be reproduced after presets or live data change.

## Implementation Sequence

1. Review and approve glossary terms, IDs, horizons, and regime labels.
2. Add a machine-readable JSON Schema for `stockfinder/v1` and valid/invalid
   fixtures.
3. Implement provider-neutral evidence records and metric registry.
4. Implement the restricted expression evaluator and evidence trace.
5. Encode the current regime and rule profiles without changing behavior.
6. Replay current tests and historical samples against both implementations.
7. Add macro, news, positioning, and social providers one capability at a time.
8. Redesign views around the six decision questions above.