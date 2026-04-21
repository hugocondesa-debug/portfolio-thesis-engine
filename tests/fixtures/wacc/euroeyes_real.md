# WACC & Valuation Inputs — EuroEyes Medical Group (1846.HK)

> Synthetic fixture mirroring Hugo's real workflow format — markdown
> tables + H2/H3 sections, no YAML frontmatter. Values are realistic
> but fabricated for Phase 1 testing.

**Ticker:** 1846.HK
**Profile:** P1
**Valuation date:** 2025-03-31
**Reporting currency:** HKD
**DCF currency:** EUR

## Market Data

| Metric                | Value     | Unit |
|-----------------------|----------:|------|
| Share price           | 12.30     | HKD  |
| Shares outstanding    | 200.0     | M    |
| Market cap            | 2,460     | HKD M |
| Cash and equivalents  | 450       | HKD M |
| Total debt            | 730       | HKD M |
| Net debt              | 280       | HKD M |

## WACC Parameters

| Parameter               | Value | Notes                          |
|-------------------------|------:|--------------------------------|
| Risk-Free Rate (Rf)     | 2.50  | German 10Y Bund, year-end 2024 |
| Equity Risk Premium     | 5.50  | Damodaran EU implied           |
| Beta levered (β_l)      | 1.10  | 5-year vs Euro Stoxx 600       |
| Size Premium            | 1.50  | Mid-cap premium (Duff & Phelps)|
| Cost of Debt (Kd)       | 4.00  | Recent bond yield              |
| Tax rate                | 16.50 | HK statutory                   |
| D/E target              | 0.33  | Debt/Equity target              |

## Capital Structure

| Component         | Weight (%) |
|-------------------|-----------:|
| Debt              | 25         |
| Equity            | 75         |
| Preferred         | 0          |

## WACC Time Series (historical — informational)

| Year | Ke    | Kd after-tax | WACC  |
|------|------:|-------------:|------:|
| 2022 | 9.10  | 2.85         | 7.63  |
| 2023 | 9.40  | 3.10         | 7.83  |
| 2024 | 9.55  | 3.34         | 8.00  |

## Business Scenarios

### Bear (25%)

- Revenue CAGR: 3.0%
- Terminal operating margin: 15.0%
- Terminal growth: 2.0%

Narrative: market share loss in Greater China, margin compression on
pricing pressure from new entrants.

### Base (50%)

- Revenue CAGR: 8.0%
- Terminal operating margin: 18.0%
- Terminal growth: 2.5%

Narrative: continued expansion at steady margins, Germany subsidiary
ramps as expected.

### Bull (25%)

- Revenue CAGR: 12.0%
- Terminal operating margin: 22.0%
- Terminal growth: 3.0%

Narrative: EUR subsidiary acquisition accretive from year 2, China
premium segment unlock.

## FX Rates (reference)

| Pair    | Rate  | Date       |
|---------|------:|------------|
| EUR/HKD | 8.65  | 2025-03-31 |
| USD/HKD | 7.78  | 2025-03-31 |

## Notes

Synthetic fixture for Phase 1 markdown-parser testing. Structure
follows Hugo's real workflow for 20+ companies.
