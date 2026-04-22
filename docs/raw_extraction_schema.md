# `raw_extraction.yaml` schema reference

This document is the field-by-field contract for the
`RawExtraction` schema. If the YAML validates against this contract,
the pipeline will process it. If it doesn't, the pipeline blocks.

The authoritative source is
[`src/portfolio_thesis_engine/schemas/raw_extraction.py`](../src/portfolio_thesis_engine/schemas/raw_extraction.py)
— this document is a human-readable mirror, updated manually.

## Top-level structure

```yaml
metadata:            # required
income_statement:    # dict keyed by period label → IncomeStatementPeriod
balance_sheet:       # dict keyed by period label → BalanceSheetPeriod
cash_flow:           # dict keyed by period label → CashFlowPeriod (optional per period)
notes:               # NotesContainer (optional)
segments:            # Segments (optional)
historical:          # HistoricalData (optional)
operational_kpis:    # OperationalKPIs (optional)
narrative:           # NarrativeContent (required when extraction_type=narrative)
```

**Rules that apply everywhere:**

- Every monetary field is `Decimal | None`; omit a field when not
  reported. Do not use `"0"` as a stand-in for absent data.
- Decimals are YAML strings: `"580.0"`. Not `580.0` (float risk).
- Negative values use `-`, never parentheses: `"-290.0"`.
- Period keys in `income_statement` / `balance_sheet` / `cash_flow`
  must match the `fiscal_periods[].period` labels in the metadata.

## 1. `metadata` (required)

Identity + provenance.

| Field                  | Type                 | Required | Notes                                                                                                |
| ---------------------- | -------------------- | -------- | ---------------------------------------------------------------------------------------------------- |
| `ticker`               | str                  | yes      | Exchange-qualified (`1846.HK`, `MSFT`, `ASML.AS`).                                                   |
| `company_name`         | str                  | yes      | Full legal / commercial name.                                                                        |
| `document_type`        | `DocumentType`       | yes      | See [document_types.md](document_types.md) for the 42 values.                                        |
| `extraction_type`      | `numeric` / `narrative` | yes   | `numeric` = produces statements; `narrative` = key themes / guidance / Q&A.                          |
| `reporting_currency`   | `Currency`           | yes      | 3-letter ISO (`USD` / `EUR` / `GBP` / `CHF` / `JPY` / `HKD`).                                        |
| `unit_scale`           | `units` / `thousands` / `millions` | yes | One value for the whole document.                                                   |
| `fiscal_year`          | int (1900–2100)      | yes      | Year of the primary period.                                                                          |
| `extraction_date`      | ISODate              | yes      | When the YAML was produced (`YYYY-MM-DD`).                                                           |
| `extractor`            | str                  | no       | Defaults to `"Claude.ai + human validation"`.                                                        |
| `source_file_sha256`   | str / null           | no       | Optional, but useful: lets the pipeline detect re-runs on identical PDFs.                            |
| `extraction_version`   | int ≥ 1              | no       | Increment when you revise an earlier extraction.                                                     |
| `extraction_notes`     | str                  | no       | Free-form: restatements, IFRS adoption year, unusual acquisitions.                                   |
| `fiscal_periods`       | list[FiscalPeriodData] | yes    | At least one entry. Exactly one may be `is_primary: true`.                                           |

### `FiscalPeriodData`

| Field         | Type                | Required | Notes                                                         |
| ------------- | ------------------- | -------- | ------------------------------------------------------------- |
| `period`      | str                 | yes      | Label matching the IS/BS/CF keys (`FY2024`, `H1 2025`, ...).  |
| `end_date`    | ISODate             | yes      | Last calendar day of the period (`2024-12-31`).               |
| `is_primary`  | bool                | no       | Defaults to `false`. At most one period may be primary.       |
| `period_type` | see below           | no       | Defaults to `FY`.                                             |

`period_type` values: `FY`, `H1`, `H2`, `Q1`, `Q2`, `Q3`, `Q4`, `YTD`,
`LTM`.

### Example

```yaml
metadata:
  ticker: "1846.HK"
  company_name: "EuroEyes Medical Group"
  document_type: "annual_report"
  extraction_type: "numeric"
  reporting_currency: "HKD"
  unit_scale: "millions"
  fiscal_year: 2024
  extraction_date: "2026-04-22"
  source_file_sha256: "a1b2c3d4..."
  extraction_version: 1
  extraction_notes: "FY2024 AR + H1 2025 Interim; IFRS 16 adopted FY2019."
  fiscal_periods:
    - period: "FY2024"
      end_date: "2024-12-31"
      is_primary: true
      period_type: "FY"
    - period: "H1 2025"
      end_date: "2025-06-30"
      period_type: "H1"
```

## 2. `income_statement`

Dict keyed by period label → `IncomeStatementPeriod`.

**Top-line fields:**

| Field                                | Type          | Notes                                   |
| ------------------------------------ | ------------- | --------------------------------------- |
| `revenue`                            | Decimal\|None |                                         |
| `cost_of_sales`                      | Decimal\|None | Typically negative.                     |
| `gross_profit`                       | Decimal\|None |                                         |
| `selling_marketing`                  | Decimal\|None | Use when the PDF splits this out.       |
| `general_administrative`             | Decimal\|None | Use when split.                         |
| `selling_general_administrative`     | Decimal\|None | Use when the PDF aggregates SG&A.       |
| `research_development`               | Decimal\|None |                                         |
| `other_operating_expenses`           | Decimal\|None |                                         |
| `operating_expenses_total`           | Decimal\|None | Sum of opex lines.                      |
| `depreciation_amortization`          | Decimal\|None | When reported separately; else in opex. |
| `operating_income`                   | Decimal\|None |                                         |
| `ebitda_reported`                    | Decimal\|None | Only when the company reports it.       |
| `finance_income`                     | Decimal\|None |                                         |
| `finance_expenses`                   | Decimal\|None | Typically negative.                     |
| `net_finance`                        | Decimal\|None | Aggregate `finance_income + finance_expenses`. |
| `share_of_associates`                | Decimal\|None | Equity-method earnings.                 |
| `non_operating_income`               | Decimal\|None | One-offs below operating profit.        |
| `income_before_tax`                  | Decimal\|None |                                         |
| `income_tax`                         | Decimal\|None | Typically negative.                     |
| `net_income_from_continuing`         | Decimal\|None |                                         |
| `net_income_from_discontinued`       | Decimal\|None |                                         |
| `net_income`                         | Decimal\|None |                                         |
| `net_income_minority`                | Decimal\|None | NCI portion.                            |
| `net_income_parent`                  | Decimal\|None | Parent-only portion.                    |
| `eps_basic`                          | Decimal\|None | Per-share; **not** scaled by `unit_scale`. |
| `eps_diluted`                        | Decimal\|None | Per-share; not scaled.                  |
| `shares_basic_weighted_avg`          | Decimal\|None | Share count; not scaled.                |
| `shares_diluted_weighted_avg`        | Decimal\|None | Not scaled.                             |
| `extensions`                         | dict[str, Decimal] | Free-form extras; snake_case keys.  |

### Example

```yaml
income_statement:
  FY2024:
    revenue: "580.0"
    cost_of_sales: "-290.0"
    gross_profit: "290.0"
    selling_marketing: "-95.0"
    general_administrative: "-65.0"
    depreciation_amortization: "-20.0"
    operating_income: "110.0"
    finance_income: "4.0"
    finance_expenses: "-18.0"
    income_before_tax: "96.0"
    income_tax: "-21.0"
    net_income: "75.0"
    eps_basic: "0.375"
    shares_basic_weighted_avg: "200.0"
```

## 3. `balance_sheet`

Dict keyed by period label → `BalanceSheetPeriod`.

**Current assets:** `cash_and_equivalents`, `short_term_investments`,
`accounts_receivable`, `inventory`, `current_assets_other`,
`total_current_assets`.

**Non-current assets:** `ppe_gross`, `accumulated_depreciation`
(typically negative), `ppe_net`, `rou_assets`, `goodwill`,
`intangibles_other`, `investments`, `deferred_tax_assets`,
`non_current_assets_other`, `total_non_current_assets`, `total_assets`.

**Current liabilities:** `accounts_payable`, `short_term_debt`,
`lease_liabilities_current`, `deferred_revenue_current`,
`current_liabilities_other`, `total_current_liabilities`.

**Non-current liabilities:** `long_term_debt`,
`lease_liabilities_noncurrent`, `deferred_tax_liabilities`,
`provisions`, `pension_obligations`, `non_current_liabilities_other`,
`total_non_current_liabilities`, `total_liabilities`.

**Equity:** `share_capital`, `share_premium`, `retained_earnings`,
`other_reserves`, `treasury_shares` (typically negative),
`total_equity_parent`, `non_controlling_interests`, `total_equity`.

**Extensions:** `extensions: dict[str, Decimal]`.

**Identity (enforced by strict validation):**

```
total_assets == total_liabilities + total_equity
```

### Example

```yaml
balance_sheet:
  FY2024:
    cash_and_equivalents: "450.0"
    accounts_receivable: "120.0"
    inventory: "80.0"
    total_current_assets: "650.0"
    ppe_net: "950.0"
    rou_assets: "380.0"
    goodwill: "600.0"
    total_non_current_assets: "2550.0"
    total_assets: "3200.0"
    accounts_payable: "95.0"
    short_term_debt: "150.0"
    lease_liabilities_current: "60.0"
    total_current_liabilities: "305.0"
    long_term_debt: "580.0"
    lease_liabilities_noncurrent: "310.0"
    total_non_current_liabilities: "995.0"
    total_liabilities: "1300.0"
    share_capital: "500.0"
    retained_earnings: "1300.0"
    total_equity_parent: "1900.0"
    total_equity: "1900.0"
```

## 4. `cash_flow`

Dict keyed by period label → `CashFlowPeriod`.

**Operating:** `net_income_cf`, `depreciation_amortization_cf`,
`working_capital_changes`, `operating_cash_flow_other`,
`operating_cash_flow`.

**Investing:** `capex` (typically negative), `acquisitions` (typically
negative), `divestitures` (positive), `investments_other`,
`investing_cash_flow`.

**Financing:** `dividends_paid` (negative), `debt_issuance` (positive),
`debt_repayment` (negative), `share_issuance` (positive),
`share_repurchases` (negative), `financing_other`, `financing_cash_flow`.

**Reconciliation:** `fx_effect`, `net_change_in_cash`.

**Extensions:** `extensions: dict[str, Decimal]`. Module A's A.4
cash-tax check reads `cash_taxes_paid` from here when present.

### Example

```yaml
cash_flow:
  FY2024:
    net_income_cf: "75.0"
    depreciation_amortization_cf: "20.0"
    working_capital_changes: "-10.0"
    operating_cash_flow: "135.0"
    capex: "-75.0"
    investing_cash_flow: "-75.0"
    dividends_paid: "-25.0"
    debt_issuance: "35.0"
    debt_repayment: "-5.0"
    financing_cash_flow: "-45.0"
    fx_effect: "0.0"
    net_change_in_cash: "15.0"
    extensions:
      cash_taxes_paid: "19.0"
```

## 5. `notes`

Container for 18 typed note objects + extensions.

### 5.1 `notes.taxes` — `TaxNote` (feeds Module A)

```yaml
notes:
  taxes:
    effective_tax_rate_percent: "21.9"
    statutory_rate_percent: "16.5"
    reconciling_items:
      - description: "Non-deductible expenses"
        amount: "1.5"
        classification: "operational"
      - description: "Prior-year adjustments"
        amount: "0.8"
        classification: "one_time"
```

`classification` ∈ {`operational`, `non_operational`, `one_time`,
`unknown`}. Module A routes on this directly — use the exact value.

### 5.2 `notes.leases` — `LeaseNote` (feeds Module C)

```yaml
notes:
  leases:
    rou_assets_opening: "360.0"
    rou_assets_closing: "380.0"
    rou_assets_additions: "55.0"
    rou_assets_depreciation: "45.0"
    lease_liabilities_total: "370.0"
    lease_liabilities_opening: "350.0"
    lease_liabilities_closing: "370.0"
    lease_interest_expense: "15.0"
    lease_principal_payments: "35.0"
    short_term_lease_expense: "3.0"
    variable_lease_payments: "2.0"
```

### 5.3 `notes.provisions` — list[`ProvisionItem`] (feeds Module B)

```yaml
notes:
  provisions:
    - description: "Warranty provisions"
      amount: "8.0"
      classification: "operating"
    - description: "Site closure restructuring"
      amount: "-30.0"
      classification: "restructuring"
```

`classification` ∈ {`operating`, `non_operating`, `restructuring`,
`impairment`, `other`}. `restructuring` / `impairment` /
`non_operating` surface as `B.2.*` adjustments.

### 5.4 `notes.goodwill` — `GoodwillNote`

```yaml
notes:
  goodwill:
    opening: "620.0"
    additions: "0.0"
    impairment: "-20.0"
    closing: "600.0"
    by_cgu:
      "Greater China": "420.0"
      "Germany": "180.0"
```

`impairment` when populated creates a `B.2.goodwill_impairment`
adjustment.

### 5.5–5.8 Other movement tables

- **`intangibles`** — `opening`, `additions`, `amortization`,
  `impairment`, `closing`, `by_type: dict[str, Decimal]`.
- **`ppe`** — `opening_gross`, `additions`, `disposals`, `transfers`,
  `closing_gross`, `accumulated_depreciation`.
- **`inventory`** — `raw_materials`, `wip`, `finished_goods`,
  `provisions`, `total`.
- **`pensions`** — DBO + plan-assets movement + service/interest cost
  + actuarial gains/losses.

### 5.9 `notes.employee_benefits`

`headcount`, `avg_compensation`, `total_compensation`,
`pension_expense`, `sbc_expense`.

### 5.10 `notes.share_based_compensation` — `SBCNote`

Option grants, exercises, outstanding; RSUs granted / vested /
outstanding; total `expense`.

### 5.11 `notes.financial_instruments` — narrative

Three free-form strings: `credit_risk`, `liquidity_risk`,
`market_risk`.

### 5.12 `notes.commitments_contingencies`

`capital_commitments`, `operating_lease_future`, `guarantees_provided`,
`contingent_liabilities`.

### 5.13 `notes.acquisitions`

```yaml
notes:
  acquisitions:
    items:
      - name: "SmallCo"
        date: "2024-05-10"
        consideration: "45.0"
        fair_value: "38.0"
        goodwill_recognized: "7.0"
```

### 5.14 `notes.discontinued_ops`

`revenue`, `operating_income`, `net_income` for discontinued
operations. Feeds Module B together with the IS
`net_income_from_discontinued`.

### 5.15 `notes.subsequent_events`

```yaml
notes:
  subsequent_events:
    - description: "Announced HKD 80M debt refinancing at 4.25%"
      date: "2025-03-14"
      impact: "material_positive"
```

`impact` ∈ {`material_negative`, `material_positive`, `neutral`,
`pending`}.

### 5.16 `notes.related_parties`

```yaml
notes:
  related_parties:
    - counterparty: "Founder-controlled HoldCo"
      nature: "Property rent"
      amount: "2.5"
```

### 5.17 `notes.trade_receivables` / `trade_payables`

```yaml
notes:
  trade_receivables:
    "FY2024": "120.0"
    "H1 2025": "135.0"
  trade_payables:
    "FY2024": "95.0"
    "H1 2025": "98.0"
```

### 5.18 `notes.unknown_sections`

Catchall for sections that don't fit any bucket.

```yaml
notes:
  unknown_sections:
    - title: "Exceptional item disclosure"
      page_range: "p.85"
      content_summary: "Legal reserve release following court ruling"
      extracted_values:
        reserve_release: "3.5"
      reviewer_flag: true
```

## 6. `segments`

Three optional dict-of-dict-of-dict structures:

```yaml
segments:
  by_geography:
    FY2024:
      "Greater China":
        revenue: "420.0"
        operating_income: "85.0"
  by_product:
    FY2024:
      "LASIK":
        revenue: "380.0"
  by_business_line:
    FY2024:
      "Clinics":
        revenue: "420.0"
```

Outer key = period; middle key = segment name (verbatim from the PDF);
inner key = metric → Decimal.

## 7. `historical`

Multi-year time series keyed by year (string):

```yaml
historical:
  revenue_by_year:
    "2020": "380.0"
    "2024": "580.0"
  net_income_by_year:
    "2020": "32.0"
    "2024": "75.0"
  total_assets_by_year:
    "2022": "2900.0"
  total_equity_by_year:
    "2022": "1600.0"
  free_cash_flow_by_year: {}
  shares_outstanding_by_year: {}
  dividends_by_year: {}
  extensions:
    custom_kpi_by_year:
      "2024": "42.0"
```

## 8. `operational_kpis`

Free-form metrics dict (period-keyed):

```yaml
operational_kpis:
  metrics:
    patient_visits_thousands:
      "FY2024": "285"
      "H1 2025": "152"
    clinics_total:
      "FY2024": "38"
      "H1 2025": "40"
    avg_revenue_per_visit_hkd:
      "FY2024": "2035"
```

## 9. `narrative` (required when `extraction_type: "narrative"`)

```yaml
narrative:
  key_themes:
    - "AI-enabled drug discovery acceleration"
  guidance_changes:
    - metric: "revenue growth"
      old: "8-10%"
      new: "10-12%"
      direction: "up"
  risks_mentioned:
    - "Supply-chain exposure to APIs sourced from China"
  q_and_a_highlights:
    - question: "Margin trajectory into 2025?"
      answer: "Operating margin floor 18% across the cycle."
      speaker: "CFO"
      topic: "Margins"
  forward_looking_statements:
    - "We expect 15-20 new clinic openings in 2025"
  capital_allocation_comments:
    - "Buyback ceiling remains USD 100M for 2025"
```

## 10. `DocumentType` decision tree

High-level selector. Full list in
[document_types.md](document_types.md).

```
Is it a financial statement?
├─ Yes → Annual?
│   ├─ Listed US → form_10k (foreign filers: form_20f)
│   ├─ Listed UK / EU / AU / HK / SG → annual_report
│   ├─ Canadian → aif + annual_report
│   └─ Chinese domestic → prc_annual
├─ Yes → Interim?
│   ├─ US quarterly → form_10q / form_8k (material events)
│   ├─ UK/EU semi-annual → interim_report
│   ├─ US material update → form_6k
│   └─ HK → hkex_announcement
├─ Is it narrative?
│   ├─ Earnings call transcript → earnings_call
│   ├─ Earnings call slides → earnings_call_slides
│   ├─ Investor day → investor_day / analyst_day
│   ├─ MD&A standalone → mda_standalone
│   └─ Prospectus → prospectus
├─ Is it regulatory correspondence?
│   ├─ SEC letter → sec_comment_letter / sec_response_letter
│   └─ FDA → fda_warning_letter
└─ Industry-specific?
    ├─ Bank → pillar_3 / icaap
    ├─ Insurance → sfcr / orsa
    └─ Mining → ni_43_101
```

## 11. Cross-references to methodology

| Schema element                       | Consumed by                          |
| ------------------------------------ | ------------------------------------ |
| `notes.taxes.reconciling_items`      | Module A (taxes, A.1–A.5)            |
| `notes.provisions` (non-op class.)   | Module B (B.2.*)                     |
| `notes.goodwill.impairment`          | Module B (B.2.goodwill_impairment)   |
| `notes.discontinued_ops` + IS field  | Module B (B.2.discontinued)          |
| IS `non_operating_income`            | Module B (B.2.non_operating_other)   |
| IS `share_of_associates`             | Module B (B.2.associates)            |
| `notes.leases.*`                     | Module C (C.1–C.3)                   |
| IS / BS / CF typed fields            | AnalysisDeriver (IC, NOPAT, ratios)  |
| `historical.*_by_year`               | Phase 2 CAGR / DuPont                |
| `segments.*`                         | Phase 2 segment reporting            |
| `operational_kpis.metrics`           | Ficha view / peer comparison         |

Validator rules — strict, warn, completeness — live in
[`src/portfolio_thesis_engine/ingestion/raw_extraction_validator.py`](../src/portfolio_thesis_engine/ingestion/raw_extraction_validator.py).
Completeness checks are driven by
[`required_notes_by_profile.md`](required_notes_by_profile.md).
