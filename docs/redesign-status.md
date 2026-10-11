# Redesign Status

Last updated: 2026-10-11  
Working branch: `dsl`  
Baseline validation: 183 tests passing, Ruff clean, desktop/mobile visual check

This is the living implementation status for the spec-driven redesign. Update it
in the same change that advances a requirement, changes its scope, or discovers
a blocker.

## Status Legend

- **Specified**: behavior is defined and accepted, but runtime work has not begun.
- **Existing**: the current application already satisfies the requirement.
- **Partial**: reusable behavior exists, but the redesign requirement is not
  satisfied end to end.
- **In progress**: implementation has started and is not yet acceptance-complete.
- **Implemented**: runtime behavior and focused tests satisfy the specification.
- **Validated**: implementation also passes the full suite and acceptance check.
- **Deferred**: intentionally outside the current redesign milestone.
- **Blocked**: cannot proceed until a named dependency or decision is resolved.

## Specification Set

| ID | Artifact | Status | Notes |
| --- | --- | --- | --- |
| SPEC-01 | [Domain glossary](domain-glossary.md) | Partial | Canonical economic, market, security, news, social, and evidence vocabulary exists. Runtime metric registry remains pending. |
| SPEC-02 | [Analysis DSL](analysis-dsl.md) | Partial | JSON Schema, safe YAML loading, semantic reference checks, weight/policy validation, and three-valued condition evaluation are implemented and tested. Derived time-series execution and evidence traces remain pending. |
| SPEC-03 | [Discovery brief](redesign-discovery.md) | Specified | Owner workflow, market scope, qualification behavior, risk needs, and acceptance criteria are recorded. |
| SPEC-04 | Redesign status | Validated | This document tracks specification coverage and current runtime state. |

## Runtime Capability Map

| ID | Requirement | Status | Current evidence | Gap to specification |
| --- | --- | --- | --- | --- |
| CAP-01 | Curated regional market context | Partial | Regional proxies and a Regional Markets widget exist. | Curated US, broad Europe, Japan, China/Hong Kong, South Korea, Taiwan, and broad Asia coverage must be reviewed and completed with explicit local benchmarks. |
| CAP-02 | Industry-first opportunity scan | Implemented | Capital Allocation is now one split Flow Finder: direction, region, optional sector, shared pattern filters, industry, profile, and stock selection stay on the left; ranked evidence and charts stay on the right. Sector remains an optional refinement. | Full industry qualification evidence is tracked under CAP-09. |
| CAP-03 | Adjustable capital-movement period | Validated | Daily (`1s`) is the backward-compatible default; Weekly (`5s`), Monthly (`21s`), and custom sessions flow through validated config, industry and stock calculations, cache identity, controls, rankings, and evidence tables. | Historical multi-horizon rotation remains separate by design. |
| CAP-04 | Direct versus inferred capital evidence | Partial | Price-volume inference is labeled separately. Typed contracts and schema-correct unavailable results exist for fund flows, filings, insider, options, block, news, and social evidence. | Real adapters remain optional external dependencies; unavailable evidence is never fabricated. |
| CAP-05 | Change-first scan experience | Implemented | The prior successful compatible scan is retained. Industry movement and stock qualification transitions label new, strengthening, deteriorating, stable, and unavailable states before current leaders. | Materiality thresholds can be refined after historical validation. |
| CAP-06 | Linked constituent stock scan | Existing | `ranked_stocks` follows selected region, sector, and industry context. | Preserve this behavior while making industry selection primary. |
| CAP-07 | Activatable any-rule qualification | Implemented | Every setup family is independently enabled; Any/All profile semantics establish eligibility separately from continuous ranking. Matches, misses, and evidence completeness are visible. | `at_least` remains specified in the generic DSL but is not exposed in the profile editor. |
| CAP-08 | Continuous setup ranking | Implemented | The default opportunity rank separates eligibility from continuous strength: setup evidence contributes 70%, constructive-base maturity 15%, and positive 1.5x-volume recency 15%. Both time effects cap at 20 sessions; each contribution and rank completeness are visible. | Historical validation remains tracked under CAP-17. |
| CAP-09 | Pass/fail evidence and completeness | Implemented | Industry results show qualifying matches, failed values versus thresholds, unavailable criteria, evidence completeness, regional-sector peer rank, and prior-scan movement change. Stocks show setup matches, misses, unavailable evidence, rule failures, rank completeness, peer rank, and qualification/movement changes. | Additional provider-backed criteria inherit the same unavailable semantics when adapters are added. |
| CAP-10 | Peer and benchmark differences | Partial | Screening shows stock and industry peer rank. Peer Comparison reports every instrument's explicit return delta versus the selected stock and configured proxy, plus the selected stock's current 6M return percentile and range against its own available 2Y history. | Separate industry-proxy and regional-index deltas require distinct configured instruments where one fallback currently serves both roles. |
| CAP-11 | Quality, growth, and forecast scoreboard | Partial | Security Scoreboard exposes reported quality, growth, cash flow, valuation, analyst opinion/event fields, availability, evidence type, and source provenance. A typed estimates contract exists. | Revisions, guidance, and cash-flow forecasts remain unavailable until a real adapter supplies them. |
| CAP-12 | Comprehensive risk scoreboard | Partial | Security Scoreboard unifies price risk, balance sheet, event, liquidity, valuation, and jurisdiction fields without one opaque score; portfolio exposure remains separately visible. | Refinancing, jurisdiction scoring, and security-to-portfolio correlation require additional provider/portfolio evidence. |
| CAP-13 | Entry and exit plan | Implemented | Trade Plan calculates and saves volatility, structure, recent-low, moving-average, trailing, target, size, and reward/risk evidence. | Order placement is intentionally out of scope. |
| CAP-14 | Reproducible decision snapshot | Implemented | Append-only SQLite snapshots retain DSL/config/profile versions, settings, timestamps, setup evidence, risk posture, stop candidates, plan, notes, status, and rejection reason. | Long-term export/migration policy is not yet specified. |
| CAP-15 | Configurable macro ranking influence | Partial | Market regime and cross-asset context exist separately, and typed macro event/series contracts preserve timestamps and vintages. | Named strategy boosts/penalties require validated mappings and remain disabled. |
| CAP-16 | Configurable news and social ranking | Partial | Typed news and social contracts exist with explicit unavailable fallback; social requires platform, breadth, attention, and entity-resolution evidence. | No signal can affect ranking until a provider and validation decision are configured. |
| CAP-17 | Validated editable Swing/Position presets | Partial | Editable Swing and Position rule profiles exist. | Add historical, as-known-then validation reports and visibly mark overrides from validated defaults. |
| CAP-18 | Weakening and avoidance scan | Implemented | The Flow Finder applies the same period, geography, and pattern workflow symmetrically to explicit Inflow and Outflow industry and stock states. | Predictive short-selling or trade recommendations remain out of scope. |

## First Implementation Slice

Goal: make the current command center honor the adjustable capital-movement
period while retaining cached-scan correctness.

| Order | Work item | Status | Acceptance check |
| --- | --- | --- | --- |
| 1 | Add capital-movement config with Daily default and custom-session validation | Validated | Existing configs migrate to Daily; invalid periods and session counts are rejected. |
| 2 | Parameterize rotation calculations without removing the existing 1W/1M/3M/6M evidence | Validated | Daily/Weekly/Monthly/custom selection changes active movement evidence deterministically. |
| 3 | Include movement settings in scan identity and snapshot metadata | Validated | Period and effective sessions participate in cache identity; incompatible snapshots are not reused. |
| 4 | Add one shared period control to the industry-first workflow | Validated | Daily is selected by default; industry and stock views share the persisted scan setting. |
| 5 | Reorder the command center around changed industries and linked constituents | Validated | Prior-scan transitions, changed industries, optional sector refinement, and linked stock qualification changes precede instrument detail. |
| 6 | Add focused config, analysis, scan, and widget tests | Validated | The suite now contains 183 passing tests, including split-view flow filtering, transitions, setup activation, capped opportunity ranking, industry explainability, peer differences, immutable snapshots, DSL validation, provider fallback, scoreboard coverage, and legacy snapshot compatibility. |
| 7 | Run full automated and visual acceptance validation | Validated | Pytest and Ruff pass; the real 6,104-symbol refresh rendered on desktop and mobile without horizontal overflow. |

## Known Decisions Needed Later

These do not block the first implementation slice:

- Exact distinct industry-proxy and regional-benchmark symbols for each curated local market.
- Provider-quality threshold before news or social evidence may affect ranking.
- Optional paid-source budget after free-source gaps are measured.
- Exact scope and timing of the deferred weakening/avoidance workflow.

## Update Rule

For every implementation change:

1. Reference one or more `CAP-*` items in the change description.
2. Move status only when its stated gap is actually closed.
3. Add or update the focused acceptance check.
4. Record blockers explicitly instead of marking unavailable evidence complete.
5. Update the date and test baseline after validation.