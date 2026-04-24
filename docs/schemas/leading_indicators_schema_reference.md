# `leading_indicators.yaml` — schema reference

**Sprint 4A-alpha.5 Part E** — analyst-facing reference for authoring
per-company leading-indicator files. Upload this document alongside
the briefing when using Claude.ai Project to generate or revise
`leading_indicators.yaml`.

## Purpose

A `leading_indicators.yaml` enumerates the exogenous macro / sector /
factor signals that a scenario set is sensitive to, with calibration
data (elasticity, sensitivity type, current environment) the
`AnalyticalBriefingGenerator` surfaces to the analyst.

Location: `data/yamls/companies/<ticker>/leading_indicators.yaml`.

## Schema

### Top level — `LeadingIndicatorsSet`

| Field | Type | Required | Notes |
|---|---|---|---|
| `target_ticker` | str | yes | ticker, e.g. `1846.HK` |
| `last_updated` | datetime | yes | ISO 8601 with timezone |
| `sector_taxonomy` | str | recommended | dotted path, e.g. `healthcare_services.eye_care` |
| `indicators` | list[LeadingIndicator] | yes | one entry per indicator |
| `source_documents_referenced` | list[str] | recommended | narrative citations |
| `sector_default_suggestions` | list[str] | optional | sector-catalogue names pending |

### `LeadingIndicator`

| Field | Type | Required | Notes |
|---|---|---|---|
| `name` | str | yes | stable slug, e.g. `eur_hkd_exchange_rate` |
| `category` | enum | yes | see below |
| `relevance` | list[str] | yes | affected metrics: `MARGIN`, `REVENUE`, `NPAT_TRANSLATION`, `COGS`, `PERSONNEL`, `DEMAND`, `INTEREST_INCOME`, `NIM`, `CREDIT_LOSSES`, `VALUATION`, `REVENUE_PRC_TRANSLATION`, `REVENUE_PRC`, etc. |
| `data_source` | `IndicatorDataSource` | yes | see below |
| `current_value` | Decimal | optional | latest observation |
| `historical_correlation` | dict[str, Decimal] | optional | `{metric: correlation_coefficient}` |
| `correlation_lag_months` | int | optional | lead time in months |
| `sensitivity` | `IndicatorSensitivity` | yes | see below |
| `current_environment` | `IndicatorEnvironment` | optional | see below |
| `scenario_relevance` | list[str] | optional | scenario names this indicator informs |
| `source_evidence` | list[int] | optional | indices into `source_documents_referenced` |
| `confidence` | enum | yes | `HIGH`, `MEDIUM`, `LOW` |

### `IndicatorDataSource`

| Field | Type | Required | Notes |
|---|---|---|---|
| `type` | enum | yes | `FRED`, `MANUAL`, `FMP`, `EODHD`, `INDUSTRY_REPORT` |
| `series_id` | str | only for `FRED` | e.g. `DEXEUHK` |
| `fallback` | enum | optional | `MANUAL` (default) or `NONE` |

### `IndicatorSensitivity`

| Field | Type | Notes |
|---|---|---|
| `type` | enum | `LINEAR`, `LINEAR_WITHIN_RANGE`, `QUALITATIVE`, `NONLINEAR` |
| `range` | tuple[Decimal, Decimal] | only for `LINEAR_WITHIN_RANGE` |
| `elasticity` | str | e.g. `"1% EUR → -0.05% OI margin"` |
| `absolute_impact_per_percent` | str | e.g. `"HK$0.86M PAT per 1% EUR move"` |
| `interpretation` | str | free-form for `QUALITATIVE` |

### `IndicatorEnvironment`

| Field | Type | Notes |
|---|---|---|
| `trend` | enum | `STABLE`, `EXPANDING`, `DETERIORATING_SLIGHTLY`, `DETERIORATING_SHARPLY`, `IMPROVING` |
| `recent_volatility` | enum | `LOW`, `MODERATE`, `HIGH` |
| `direction` | enum | `NEUTRAL`, `WARNING`, `HEADWIND`, `TAILWIND` |
| `data_date` | date | optional |

## Category enumeration

| Category | Typical indicators |
|---|---|
| `CURRENCY` | `eur_hkd_exchange_rate`, `dxy_index`, `emerging_market_fx_basket` |
| `MACRO` | `gdp_growth`, `pmi_manufacturing`, `consumer_confidence_index` |
| `LABOR_COSTS` | `healthcare_wage_inflation`, `average_hourly_earnings_yoy` |
| `COMMODITY` | `commodity_spot_price`, `medical_consumables_ppi`, `brent_crude` |
| `RATES` | `central_bank_policy_rate`, `yield_curve_slope`, `credit_spreads` |
| `DEMAND` | `retail_sales_yoy`, `elective_surgery_demand_index` |
| `SUPPLY` | `supplier_lead_times`, `capacity_utilisation_index` |
| `REGULATORY` | `healthcare_reimbursement_changes`, `capital_requirements` |
| `OTHER` | `commercial_rent_index`, `air_traffic_yoy` |

## Confidence calibration

- **HIGH** — quantified elasticity backed by filed numbers (management
  disclosure, regulatory filings, audited report with explicit
  sensitivity table).
- **MEDIUM** — qualitative link with historical correlation but no
  explicit elasticity.
- **LOW** — hypothesised link under active monitoring; insufficient
  evidence to anchor scenario math.

## Example (EuroEyes H1 2025)

See `data/yamls/companies/1846-HK/leading_indicators.yaml` for the
fully-commented starter set (5 indicators: EUR/HKD, EUR/CNY, PRC
deposit rate, PRC consumer confidence, German healthcare wage
growth).

## Claude.ai prompt template

When prompting Claude.ai Project to generate a first
`leading_indicators.yaml` from scratch:

> I need to generate `leading_indicators.yaml` for `<TICKER>`. Use the
> briefing (Section 6 and Section 12), the latest `raw_extraction.yaml`
> (especially the management narrative / risks / guidance), and the
> sector-default catalogue suggestions listed in the briefing.
>
> Output a full YAML file conforming to the schema in
> `leading_indicators_schema_reference.md`. Include:
> - 5–10 indicators prioritised by the sensitivity the narrative
>   explicitly quantifies.
> - A `sensitivity.elasticity` string for every indicator whose
>   impact is numeric in the narrative.
> - An `IndicatorEnvironment` entry per indicator with
>   `trend`/`direction` based on the latest macro data I'll describe.
> - `source_evidence` indices pointing at the narrative citations
>   I'll include in `source_documents_referenced`.

## Validation checklist

- [ ] `target_ticker` matches the file path.
- [ ] Every `LINEAR` sensitivity has an `elasticity` string.
- [ ] Every `QUALITATIVE` sensitivity has an `interpretation`.
- [ ] Every `FRED` data source has a `series_id`.
- [ ] `last_updated` within the last 90 days.
- [ ] Confidence rating honest (avoid over-claiming HIGH without
  explicit elasticity in narrative).
