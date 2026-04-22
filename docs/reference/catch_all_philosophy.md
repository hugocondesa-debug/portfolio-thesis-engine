# The catch-all principle

**Read this first. Re-read it whenever you feel the urge to
interpret something.**

## The principle

**Extract everything. Classify nothing. Judge nothing.**

Extraction produces a YAML of **facts as reported by the company**.
It does not produce analysis, interpretation, or evaluation. Those
happen downstream, in the Phase 2 modules, the Ficha composer, and
the portfolio dashboard — which are all app-side, deterministic, and
auditable.

When a Claude.ai chat during extraction says "this looks like a
meaningful tax inefficiency" or "depreciation is up 30% YoY", it is
doing the wrong job. The extractor's job is to write the effective
tax rate and the depreciation number into the YAML, not to judge
them.

## The three things to NOT do during extraction

### 1. Do not calculate or derive

If the PDF reports `revenue = 580` and `cost_of_sales = -290`, the
YAML gets both numbers. The extractor does **not** compute
`gross_profit = 290` unless the PDF reports it explicitly.

Why: derived fields are the job of `AnalysisDeriver` downstream. It
re-computes `EBITDA = operating_income + |D&A|`, `ROIC`, `NOPAT`,
margins, and every ratio from the raw fields — deterministically and
reproducibly. If the extractor computes them, the YAML carries a
shadow value that may silently disagree with the downstream
computation.

**Bad (derived during extraction):**

```yaml
# Don't do this — gross_profit not disclosed in the PDF
income_statement:
  FY2024:
    revenue: "580.0"
    cost_of_sales: "-290.0"
    gross_profit: "290.0"            # ← extractor-derived, not reported
```

**Good (extract what's reported; leave the rest None):**

```yaml
income_statement:
  FY2024:
    revenue: "580.0"
    cost_of_sales: "-290.0"
    # gross_profit omitted — the company didn't publish it on this IS
```

### 2. Do not interpret

Words like "meaningful", "material", "inefficient", "concerning",
"elevated", "strong", "weak" have no place in the YAML. Not in the
narrative strings. Not in `extraction_notes`. Not in
`content_summary`.

The extractor describes; it does not evaluate.

**Bad (observed during early EuroEyes extraction):**

```yaml
notes:
  taxes:
    extraction_commentary: >
      ETR 33.3% represents meaningful tax inefficiency vs. the 16.5%
      HK statutory rate — FX differential and German rate-diff drive it.

    # Also bad:
    effective_tax_rate_percent: "33.3"
    # "Tax inefficiency — FX translation + German subsidiary high-rate impact"

# Or in notes.financial_instruments.market_risk:
market_risk: >
  Multi-currency exposure EUR 89.7% creates FX risk. Material
  translation headwind YTD.
```

**Good (facts only):**

```yaml
notes:
  taxes:
    effective_tax_rate_percent: "33.3"
    statutory_rate_percent: "16.5"
    reconciling_items:
      - description: "German subsidiary rate differential (30% vs 16.5% HK)"
        amount: "3.7"
        classification: "operational"
      - description: "FX translation on tax balances"
        amount: "1.2"
        classification: "operational"

  financial_instruments:
    market_risk: >
      Cash by currency at FY2024 year-end: HKD 42M, EUR 586M. Reporting
      currency HKD. No FX derivatives outstanding.
```

The downstream Ficha composer and Phase 2 analytics will look at
`effective_tax_rate_percent=33.3` vs. `statutory=16.5` and produce
the observation "ETR > statutory by 16.8 percentage points". That's
where interpretation belongs.

### 3. Do not classify beyond the schema

The schema has closed classification vocabularies:

- `TaxItemClassification`: `operational` / `non_operational` /
  `one_time` / `unknown`.
- `ProvisionClassification`: `operating` / `non_operating` /
  `restructuring` / `impairment` / `other`.

These are **not** analytical judgments — they are routing labels for
Module A / Module B. Pick the value that corresponds to the
disclosure, not the one that makes the company look better / worse.

**Unknown vs. a guess:**

- If the PDF clearly labels a reconciling item as "prior-year
  adjustment" → `classification: "one_time"`.
- If the PDF is ambiguous ("Other reconciling items") → use the
  `unknown` (taxes) or `other` (provisions) value. Do not guess.
  The downstream module has a label-keyword fallback for the
  `unknown` case.

## Facts vs. judgements — concrete examples

| Observation during extraction                                   | Kind      | Where it goes                        |
| --------------------------------------------------------------- | --------- | ------------------------------------ |
| "ETR is 33.3%"                                                  | Fact      | `notes.taxes.effective_tax_rate_percent` |
| "ETR is 33.3% — meaningful inefficiency"                        | Judgement | **Nowhere**. Drop the second clause. |
| "Depreciation +30% YoY"                                         | Derived   | **Nowhere**. Write both years' D&A; let downstream compute. |
| "Depreciation: FY2024 107.4, FY2023 82.9"                       | Facts     | `income_statement.FY2024.depreciation_amortization` + `.FY2023` |
| "Cash held 89.7% in EUR — FX risk"                              | Judgement + derived | Cash by currency → `notes.financial_instruments.market_risk` or BS extensions. No "89.7%" calculation. No "risk". |
| "Cash by currency: HKD 42M, EUR 586M"                           | Facts     | Narrative string or `BalanceSheetPeriod.extensions`. |
| "Goodwill impairment of HKD 20M recorded against Germany CGU"    | Fact      | `notes.goodwill.impairment: -20.0` + `by_cgu: {"Germany": ...}` |
| "Goodwill impairment signals weakness in German business"       | Judgement | **Nowhere**.                         |
| "Material acquisition — SmallCo for HKD 45M in May"              | Mixed     | Facts → `notes.acquisitions.items[0]`. "Material" is a judgement — drop. |
| "SmallCo acquired 2024-05-10 for HKD 45M, fair value 38M"       | Facts     | `notes.acquisitions.items[0]`       |

## Where factual observations go

Factual context about the extraction itself (as opposed to the
company's disclosures) goes in `metadata.extraction_notes`. Two kinds
of content are appropriate:

- **Provenance metadata.** "Restated FY2023 comparative per FY2024
  AR narrative." "IFRS 16 adopted 1 Jan 2019." "Segment taxonomy
  changed in FY2023."
- **One-off events the PDF discloses.** "M&A completed May 2024:
  SmallCo." "Goodwill impairment recorded against Germany CGU this
  period." "New product line launched Q3 2024."

What does **not** belong there:

- Judgements ("material", "significant", "concerning").
- Calculations ("revenue growth +11%").
- Forward-looking statements ("management expects further growth").
  These go in `narrative.forward_looking_statements` if this is a
  narrative extraction.

## The extraction / downstream boundary

```
┌──────────────────────────┐       ┌──────────────────────────────┐
│  Extraction              │       │  Downstream (Phase 1.5 + 2)  │
│  (Claude.ai Project)     │       │  (the app, deterministic)    │
│                          │       │                              │
│  INPUT:  the PDF          │──►   │  Module A: taxes adjustment  │
│  OUTPUT: facts as YAML    │      │  Module B: provisions        │
│                          │       │  Module C: leases            │
│  Describes.               │      │  AnalysisDeriver: IC, NOPAT  │
│  Does not:                │      │  Guardrails: identity checks │
│  - derive                 │      │  Valuation: DCF, equity      │
│  - interpret              │      │  Ficha: aggregate view       │
│  - judge                  │      │                              │
│  - classify beyond schema │      │  This layer derives,         │
│                          │       │  interprets, and judges.     │
└──────────────────────────┘       └──────────────────────────────┘
```

Every interpretation the extractor skips is an interpretation
downstream does correctly. Every interpretation the extractor makes
is a shadow calculation that may conflict with the downstream one
— and the YAML is where the conflict becomes invisible.

## The mental test

Before you write anything into the YAML, ask:

> "Is this on the page, or am I adding it?"

If you're adding it → don't. The field goes blank, or the
`unknown_sections` bucket gets a flagged-for-review entry.

If it's on the page → copy it as reported. Sign, unit, precision,
label. Everything.

## When you genuinely can't tell

If a disclosure is ambiguous and you're tempted to guess, do this
instead:

1. Leave the typed field empty (`None`).
2. Add a `reviewer_flag: true` entry to `notes.unknown_sections`
   with `content_summary` describing what's ambiguous and why.
3. Note in `metadata.extraction_notes`: "See unknown_sections entry
   'X' — needs Hugo review."

The pipeline runs with `None`; the audit surfaces the entry; Hugo
decides. Guessing is the one thing you don't do.

## One-sentence summary

**Extraction captures what the company reported. Downstream decides
what it means.**
