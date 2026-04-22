# `raw_extraction.yaml` schema reference

**Phase 1.5.3 as-reported structured schema.**

The schema captures the company's disclosures verbatim. Line items
keep their reading order, their reported labels, and a boolean flag
marking subtotal lines. Notes are lists of tables with company
labels. Classification (operating vs financial, operating vs
non-operating, etc.) happens **downstream** — in the extraction
modules — not in the schema.

Authoritative source:
[`src/portfolio_thesis_engine/schemas/raw_extraction.py`](../src/portfolio_thesis_engine/schemas/raw_extraction.py).

## Top-level structure

```yaml
metadata:            # required
income_statement:    # dict[period_label → IncomeStatementPeriod]
balance_sheet:       # dict[period_label → BalanceSheetPeriod]
cash_flow:           # dict[period_label → CashFlowPeriod] (optional per period)
notes:               # list[Note]
segments:            # list[SegmentReporting]
historical:          # HistoricalDataSeries (optional)
operational_kpis:    # list[OperationalKPI]
narrative:           # NarrativeContent (required when extraction_type = narrative)
```

## 1. `metadata`

| Field                  | Type                   | Required | Notes                                    |
| ---------------------- | ---------------------- | -------- | ---------------------------------------- |
| `ticker`               | str                    | yes      | Exchange-qualified (`1846.HK`).          |
| `company_name`         | str                    | yes      |                                          |
| `document_type`        | DocumentType enum      | yes      | See `document_types.md`.                 |
| `extraction_type`      | `numeric` / `narrative` | yes     |                                          |
| `reporting_currency`   | Currency (3-letter ISO) | yes     |                                          |
| `unit_scale`           | `units`/`thousands`/`millions` | yes |                                       |
| `fiscal_year`          | int (optional)         | no       | 1.5.3: relaxed to optional.              |
| `extraction_date`      | ISODate                | yes      |                                          |
| `extractor`            | str                    | no       | Default: `"human + Claude.ai Project"`.  |
| `source_file_sha256`   | str                    | no       |                                          |
| `extraction_version`   | int ≥ 1                | no       |                                          |
| `extraction_notes`     | str                    | no       | Free-form; provenance / restatement notes. |
| `fiscal_periods`       | list[FiscalPeriodData] | yes      | ≥ 1 entry. At most one `is_primary: true`. |

## 2. `LineItem`

The atomic building block. Every statement is a list of these.

| Field           | Type                 | Notes                                                                 |
| --------------- | -------------------- | --------------------------------------------------------------------- |
| `order`         | int ≥ 0              | Reading order within the statement. Validator walks ordered items.    |
| `label`         | str (min 1 char)     | **Verbatim label** from the PDF.                                      |
| `value`         | Decimal \| None      | Signed (parentheses → `-`). `None` for items the issuer doesn't report. |
| `is_subtotal`   | bool (default false) | True for Gross profit / Operating profit / PBT / NI / section totals. |
| `section`       | str \| None          | BS: `current_assets` / `non_current_assets` / `total_assets` / `current_liabilities` / `non_current_liabilities` / `total_liabilities` / `equity`. CF: `operating` / `investing` / `financing` / `fx_effect` / `subtotal`. IS: typically unset. |
| `source_note`   | int \| None          | Cross-reference to note number in the PDF.                            |
| `source_page`   | int \| None          | Page in the PDF.                                                      |
| `notes`         | str \| None          | Extractor comment (e.g. "originally in EUR, translated at 8.31").     |

### Example: EuroEyes FY2024 IS

```yaml
income_statement:
  FY2024:
    reporting_period_label: "Year ended 31 December 2024"
    line_items:
      - {order: 1, label: "Revenue", value: "580.0"}
      - {order: 2, label: "Cost of sales", value: "-290.0"}
      - {order: 3, label: "Gross profit", value: "290.0", is_subtotal: true}
      - {order: 4, label: "Selling and marketing expenses", value: "-95.0"}
      - {order: 5, label: "General and administrative expenses", value: "-65.0"}
      - {order: 6, label: "Depreciation and amortisation", value: "-20.0"}
      - {order: 7, label: "Operating profit", value: "110.0", is_subtotal: true}
      - {order: 8, label: "Finance income", value: "4.0"}
      - {order: 9, label: "Finance costs", value: "-18.0"}
      - {order: 10, label: "Profit before taxation", value: "96.0", is_subtotal: true}
      - {order: 11, label: "Income tax", value: "-21.0"}
      - {order: 12, label: "Profit for the year", value: "75.0", is_subtotal: true}
    profit_attribution:
      parent: "75.0"
      non_controlling_interests: "0.0"
      total: "75.0"
    earnings_per_share:
      basic_value: "0.375"
      basic_unit: "HKD"
      diluted_value: "0.370"
      diluted_unit: "HKD"
      basic_weighted_avg_shares: "200.0"
      diluted_weighted_avg_shares: "202.7"
      shares_unit: "millions"
```

### The subtotal flag

Mark as `is_subtotal: true` any line the company presents as a running
subtotal. The validator walks line items in order and verifies that
each subtotal equals the running sum of preceding non-subtotal items.

Typical IS subtotals: Gross profit, Operating profit, Profit before
tax, Profit for the year. Typical BS subtotals: Total current assets,
Total non-current assets, Total assets, Total current liabilities,
Total non-current liabilities, Total liabilities, Total equity. CF:
each section total + the overall Δcash line.

**Don't guess.** If the company doesn't present a line as a subtotal
(e.g. no "Operating profit" line on a condensed IS), don't mark one.

## 3. `IncomeStatementPeriod` extras

- `reporting_period_label`: free-form ("Year ended 31 December 2024").
- `profit_attribution`: `parent` / `non_controlling_interests` /
  `total`. Populate when the IS discloses the split.
- `earnings_per_share`: `basic_value`, `basic_unit` (e.g. "HKD" or
  "HK cents"), `diluted_value`, `diluted_unit`, weighted-average
  share counts.

## 4. `BalanceSheetPeriod`

- `period_end_date`: `ISODate`.
- `line_items`: list[LineItem] with `section` set for every leaf.

## 5. `CashFlowPeriod`

- `reporting_period_label`.
- `line_items`: list[LineItem]. Each section-subtotal uses
  `section` and `is_subtotal: true`; the overall Δcash line uses
  `section: "subtotal"` and `is_subtotal: true`.

## 6. `Note` + `NoteTable`

Notes replace the 17 typed note classes from Phase 1.5. A note has a
verbatim title and zero or more tables; modules look for notes by
title-regex match and scan tables by row label.

```yaml
notes:
  - note_number: "6"
    title: "Income tax expense"
    source_pages: [84, 85]
    tables:
      - table_label: "Rate reconciliation"
        columns: ["Description", "HKD millions"]
        rows:
          - ["Profit before tax at statutory rate", "15.84"]
          - ["Non-deductible expenses", "1.5"]
          - ["Prior-year adjustments", "0.8"]
          - ["Effective tax rate", "21.9"]
        unit_note: "Figures in HK$'millions"
    narrative_summary: "Brief factual summary of the note."
```

- `note_number`: verbatim ("5", "5(a)", "3.1").
- `source_pages`: list of page numbers.
- `tables`: list of `NoteTable` — every table in the note.
- `narrative_summary`: optional factual summary (no judgement).

Numeric-looking string cells in `rows` are coerced to `Decimal` at
load time; plain-text row labels stay as strings.

## 7. `SegmentReporting`

One entry per (period × axis) combination.

```yaml
segments:
  - period: "FY2024"
    segment_type: "geography"  # or "product" / "business_line" / "operating"
    segments:
      - segment_name: "Greater China"
        metrics: {revenue: "420.0", operating_income: "85.0"}
      - segment_name: "Germany / Europe"
        metrics: {revenue: "160.0", operating_income: "25.0"}
    inter_segment_eliminations: {revenue: "-5.0"}  # optional
```

`metrics` is free-form: capture whatever the company discloses per
segment.

## 8. `HistoricalDataSeries`

Multi-year summary, parallel-array style (years + one list per metric):

```yaml
historical:
  source: "Five-Year Financial Summary, p.172"
  years: [2020, 2021, 2022, 2023, 2024]
  metrics:
    revenue: ["380.0", "440.0", "485.0", "520.0", "580.0"]
    net_income: [null, "45.0", "52.0", "60.0", "75.0"]
    total_assets: [null, null, "2900.0", "3050.0", "3200.0"]
```

`null` entries preserve alignment when a metric wasn't disclosed for
a specific year.

## 9. `OperationalKPI`

```yaml
operational_kpis:
  - metric_label: "Total clinics and consultation centres worldwide"
    source: "MD&A"
    unit: "count"
    values: {FY2020: "28", FY2024: "38"}
  - metric_label: "Patient visits"
    source: "MD&A"
    unit: "thousands"
    values: {FY2024: "285"}
  - metric_label: "Expansion outlook 2025"
    source: "MD&A"
    unit: null
    values: {FY2024: "Strong growth in mainland China"}
```

- Verbatim label from the company.
- `source` lists where it was disclosed.
- `unit` — free-form; include currency when monetary (`"HKD millions"`).
  The parser scales KPI values only when `unit` contains a
  currency ISO code (USD / EUR / GBP / CHF / JPY / HKD / CNY / RMB).
- `values` entries can be Decimal (coerced from numeric strings) or
  plain strings (narrative KPIs).

## 10. `narrative` (required when `extraction_type = "narrative"`)

Unchanged from Phase 1.5. See the schema file for the full shape:
`key_themes`, `guidance_changes`, `risks_mentioned`,
`q_and_a_highlights`, `forward_looking_statements`,
`capital_allocation_comments`.

## 11. DocumentType decision tree

High-level selector — full list in `document_types.md`. The
extraction workflow remains the same as Phase 1.5.

## 12. What downstream consumes

| Schema element                        | Consumed by                              |
| ------------------------------------- | ---------------------------------------- |
| IS/BS/CF `line_items` ordered + flagged | `ExtractionValidator` walking subtotals |
| Note titles (regex)                   | Module A (taxes), B (provisions, goodwill, discontinued), C (leases) |
| Note table rows by label              | Same modules, for specific row values.   |
| IS labels (regex)                     | Module B (IS non-op lines); AnalysisDeriver (labels + sections) |
| BS `section` + labels                 | AnalysisDeriver IC computation           |
| Segments / historical / KPIs          | Pass through to canonical state         |

## 13. Migration from Phase 1.5 fixed-field schema

The Phase 1.5 schema had typed fields like `revenue`, `cost_of_sales`,
`operating_income` on `IncomeStatementPeriod`. Phase 1.5.3 replaces
them with `list[LineItem]`. The migration rule:

- **Every typed field → one `LineItem`** with the same conceptual
  value, using the company's actual label.
- **Typed subtotal fields** (`gross_profit`, `operating_income`,
  `net_income`, `total_assets`, `total_equity`, etc.) → `LineItem`
  with `is_subtotal: true`.
- **Typed notes** (`TaxNote`, `LeaseNote`, `GoodwillNote`, …) → one
  `Note` each with `tables` carrying the movement / reconciliation
  rows.
- **Classification enums** (`TaxItemClassification`,
  `ProvisionClassification`) are gone. Modules classify locally by
  label keyword.

See `tests/fixtures/euroeyes/raw_extraction.yaml` for a realistic
Phase 1.5.3 fixture.
