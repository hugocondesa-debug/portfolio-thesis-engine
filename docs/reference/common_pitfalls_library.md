# Common extraction pitfalls — library

Twenty-plus antipatterns catalogued from real extractions. Each has a
concrete bad example, a good counter-example, and a detection
heuristic.

Pitfalls are grouped by root cause. When you see the validator flag
something, start at the relevant group.

## Phase 1.5.3 — obsolete pitfall classes

The Phase 1.5.3 schema migration eliminated whole classes of bugs:

- **D.1 Inventing classification values** — the `TaxItemClassification`
  and `ProvisionClassification` enums are gone. Classification now
  happens downstream in Modules A/B based on label keywords. Nothing
  for the extractor to invent.
- **D.2 Classifying on gut feel** — same as above. Capture the row
  label verbatim; let the module decide.
- **D.3 Squashing "Other" into `operational`** — same.
- **"selling_marketing or general_administrative?"** — no longer a
  question. Whatever the company reports is one `LineItem` with its
  own `label`. The schema doesn't force you to pick a bucket.

These pitfalls still apply as cautionary tales for the old schema;
they no longer happen in practice. The **new** pitfalls to watch for
are around `is_subtotal` flagging and `section` assignment — see
groups **G** and **H** below.

## Group A — Sign errors

### A.1 Parentheses slipping into the YAML

**Bad:**

```yaml
cost_of_sales: "(290.0)"     # parser rejects — literal "(" not valid for Decimal
```

**Good:**

```yaml
cost_of_sales: "-290.0"
```

**Detection:** pydantic validation error on load; parser exits with
`InvalidOperation`.

### A.2 Expense reported positive

**Bad:**

```yaml
income_tax: "21.0"            # income tax is an expense, should be negative
finance_expenses: "18.0"      # same
```

**Good:**

```yaml
income_tax: "-21.0"
finance_expenses: "-18.0"
```

**Detection:** IS walk — `op_income + fin_inc + fin_exp + tax`
doesn't equal `net_income`. See
[`sign_convention_guide.md`](../guides/sign_convention_guide.md).

### A.3 CapEx reported positive

**Bad:**

```yaml
capex: "75.0"                 # cash outflow — should be negative
```

**Good:**

```yaml
capex: "-75.0"
```

**Detection:** CF walk (`CFO + CFI + CFF + fx = net_change`)
disagrees with disclosed `net_change_in_cash`.

### A.4 Tax reconciling-item sign flipped

**Bad:**

```yaml
notes:
  taxes:
    reconciling_items:
      - description: "Foreign rate differential (Germany 30% vs HK 16.5%)"
        amount: "-3.7"        # Germany is higher → increases tax → positive
```

**Good:**

```yaml
- description: "Foreign rate differential (Germany 30% vs HK 16.5%)"
  amount: "3.7"
```

**Detection:** reconciling items don't sum to `(effective − statutory)
× PBT`.

## Group B — Unit-scale errors

### B.1 The EuroEyes "580 bug"

**Bad:** PDF reports "HKD 580 million" in the revenue row. The
`unit_scale` is declared `"millions"`, and the extractor writes the
**fully-expanded** number:

```yaml
metadata:
  unit_scale: "millions"
income_statement:
  FY2024:
    revenue: "580000000.0"    # ← this is base-unit; parser will × 1M → 580 trillion
```

**Good:** copy the number as displayed in the PDF:

```yaml
metadata:
  unit_scale: "millions"
income_statement:
  FY2024:
    revenue: "580.0"          # parser produces Decimal(580000000) downstream
```

**Detection:** cross-check gate reports revenue 1_000_000× off vs.
FMP. Validator's `W.MAG` warns at extreme magnitudes.

### B.2 EPS scaled by mistake

**Bad:**

```yaml
metadata:
  unit_scale: "millions"
income_statement:
  FY2024:
    eps_basic: "0.375"        # correct per-share
    # …but then a downstream reader multiplied it by 1M → 375_000
```

This is a reader bug, not an extraction bug — but the extraction
prevents it by convention. **EPS, EPS diluted, and share counts are
NOT scaled by the parser** (they pass through). Always extract them
as reported.

**Detection:** EPS shows up in the ficha as millions-of-units per
share. Obvious visually.

### B.3 Mixed-scale filing extracted as single scale

**Bad:** Japanese TDnet filing reports IS in `millions`, segment
table in `thousands`, SBC note in `units`. Extractor declares
`unit_scale: "millions"` and copies all numbers as shown without
normalising.

**Good:** convert every non-declared-scale section to the declared
scale before writing the YAML. Document in `extraction_notes`:

```yaml
metadata:
  unit_scale: "millions"
  extraction_notes: >
    Filed in JPY. Primary statements in millions. Segment table at
    p.42 was in thousands; divided by 1000 for this YAML. SBC note
    at p.78 in absolute units; divided by 1_000_000 for this YAML.
```

**Detection:** magnitudes wildly different between statements and
notes for the same conceptual line.

### B.4 Missing unit_scale entirely

**Bad:**

```yaml
metadata:
  ticker: "X"
  # unit_scale omitted
```

**Good:** always declare. If you genuinely can't tell, ask in the
Claude.ai chat before writing the YAML.

**Detection:** pydantic validation error — `unit_scale` is required.

## Group C — Currency errors

### C.1 Reporting currency = subsidiary currency

**Bad:** "EuroEyes has 55 % of revenue in Europe, so we declare
`reporting_currency: EUR`."

**Good:** reporting currency is the one on the cover page of the
consolidated statements. For EuroEyes (listed in HK, consolidated
in HKD): `"HKD"`.

**Detection:** magnitudes don't match FMP; narrative of the PDF
references HKD throughout.

### C.2 Cash by currency written without totalling

**Bad:**

```yaml
balance_sheet:
  FY2024:
    cash_and_equivalents: "450.0"
    extensions:
      cash_hkd: "210.0"
      cash_eur: "175.0"
      # Missed CNY entirely — extension sum 385 ≠ aggregate 450
```

**Good:** capture all currency buckets, or none. The sum should
equal the aggregate.

```yaml
balance_sheet:
  FY2024:
    cash_and_equivalents: "450.0"
    extensions:
      cash_by_currency_hkd: "210.0"
      cash_by_currency_eur: "175.0"
      cash_by_currency_cny: "65.0"
```

**Detection:** audit script sums extension components against
aggregate.

### C.3 CTA broken out into its own BS line

**Bad:**

```yaml
balance_sheet:
  FY2024:
    cta_reserve: "-45.0"      # no such typed field on BalanceSheetPeriod
```

**Good:** CTA belongs in `other_reserves`; break out only via
extensions if disclosed separately in the PDF.

```yaml
balance_sheet:
  FY2024:
    other_reserves: "125.0"
    extensions:
      cta_reserve: "-45.0"
```

**Detection:** schema validation error — unknown field.

## Group D — Classification errors

### D.1 Inventing classification values

**Bad:**

```yaml
notes:
  taxes:
    reconciling_items:
      - description: "Whatever"
        amount: "1.0"
        classification: "permanent_difference"  # ← not in the enum
```

**Good:** use only the four allowed values
(`operational` / `non_operational` / `one_time` / `unknown`).

```yaml
- description: "Whatever"
  amount: "1.0"
  classification: "unknown"         # when uncertain
```

**Detection:** pydantic validation error — value not in Literal.

### D.2 Classifying on "gut feel" rather than disclosure

**Bad:** reading "Prior-year adjustment for German deferred taxes"
and deciding the `classification: "operational"` because "it's a
real cost that recurs".

**Good:** "Prior-year adjustment" is textbook `one_time`. Route on
the disclosure word, not the interpretation.

**Detection:** second-pass review with a colleague flags the
judgement-based classification.

### D.3 Squashing "Other" reconciling items into `operational`

**Bad:**

```yaml
- description: "Other"
  amount: "2.5"
  classification: "operational"   # but it's literally labelled "Other"
```

**Good:**

```yaml
- description: "Other"
  amount: "2.5"
  classification: "unknown"
```

Module A has a label-keyword fallback for `unknown` — it will classify
based on keywords when possible. Don't pre-bin.

## Group E — Schema / completeness errors

### E.1 Silent omission of "Other" lines

**Bad:** the PDF's IS has eight lines; the YAML only captures six
because two were in the "Other" bucket and the extractor "didn't
feel they were material."

**Good:** capture every line that appears on the IS. Small items in
"Other" belong in `other_operating_expenses` (typed) or in
extensions. Never drop silently.

**Detection:** gross_profit walk fails — a line is missing.

### E.2 Inferring missing values from totals

**Bad:** PDF reports `total_current_assets` and `cash` but omits
`accounts_receivable`. Extractor back-calculates: `AR =
total_current_assets − cash − inventory − other`.

**Good:** leave `accounts_receivable: None` (omit). The downstream
ratio computation will skip DSO for that period rather than using a
synthetic number.

**Detection:** cross-check gate compares DSO against external data;
synthetic DSO is usually off.

### E.3 Fabricated director compensation (observed case)

**Observed bad pattern:** Pass 6 of the extraction scraped the
governance section and produced plausible-looking director
compensation figures. The specific individuals' comp was not
disclosed in the source AR — the extractor hallucinated a table
from industry norms.

**Good:** if the PDF doesn't disclose individual compensation, the
YAML doesn't either. `employee_benefits.total_compensation` captures
the aggregate; individual breakdowns go in extensions ONLY if
disclosed (with page references).

**Detection:** page-reference comment absent; spot-check the PDF.

### E.4 Missing a required note

**Bad:** P1 extraction omits `notes.financial_instruments` because
"the narrative was too long to summarise".

**Good:** populate the required field with a one-paragraph summary.
Use empty strings for sub-fields that weren't disclosed but keep
the field:

```yaml
notes:
  financial_instruments:
    credit_risk: "Trade receivables concentrated in HK insurance payers."
    liquidity_risk: "HKD 450M cash covers 18 months of opex."
    market_risk: "See multi-currency note."
```

**Detection:** `pte validate-extraction` → `C.R.financial_instruments
FAIL`.

### E.5 Squashing segment columns

**Bad:** PDF shows four columns (`Asia`, `Europe`, `Americas`,
`Corporate/Elim`). Extractor merges `Corporate/Elim` into `Americas`
because "it's small".

**Good:** every column is its own entry. Eliminations are their own
segment:

```yaml
segments:
  by_geography:
    FY2024:
      "Asia": {revenue: "420.0"}
      "Europe": {revenue: "160.0"}
      "Americas": {revenue: "75.0"}
      "Corporate / Eliminations": {revenue: "-5.0"}
```

**Detection:** segment revenues don't sum to consolidated revenue.

### E.6 Missing discontinued operations

**Bad:** the IS has a "Net income from continuing operations" line
AND a "Net income from discontinued" line. Extractor writes
`net_income` = continuing number and ignores discontinued.

**Good:**

```yaml
income_statement:
  FY2024:
    net_income_from_continuing: "75.0"
    net_income_from_discontinued: "-12.0"
    net_income: "63.0"                # continuing + discontinued
```

And populate `notes.discontinued_ops` with the revenue / op-income
breakdown.

**Detection:** net_income walk (continuing + discontinued) doesn't
reconcile to reported.

### E.7 Skipping extensions for sector-specific lines

**Bad:** REIT filing has "Straight-line rent adjustment" line in
CFO. Extractor drops it.

**Good:**

```yaml
cash_flow:
  FY2024:
    operating_cash_flow: "..."
    extensions:
      straight_line_rent_adjustment: "-3.5"
```

**Detection:** CFO walk off; the PDF line is visibly absent from
the YAML.

## Group F — Interpretation creep

### F.1 Analytical language in extraction_notes

**Bad:**

```yaml
metadata:
  extraction_notes: >
    ETR of 33.3% is meaningful tax inefficiency. Depreciation +30% YoY
    signals capex cycle peak. EUR 89.7% of cash exposes to FX risk.
```

**Good:**

```yaml
metadata:
  extraction_notes: >
    Effective tax rate FY2024: 33.3% (statutory HK 16.5%). See
    notes.taxes for reconciliation. Depreciation: FY2024 107.4M,
    FY2023 82.9M. Cash by currency at YE: HKD 42M, EUR 586M.
```

Facts. No judgements. See
[`catch_all_philosophy.md`](catch_all_philosophy.md).

**Detection:** read the notes aloud. If you hear "meaningful",
"material", "elevated", "concerning", "strong", rewrite.

### F.2 Derived fields populated during extraction

**Bad:** PDF reports `revenue` and `cost_of_sales`. Extractor
computes `gross_profit = 290` and writes it, even though the PDF
doesn't disclose it.

**Good:** leave `gross_profit: None`. AnalysisDeriver computes it
downstream from the same inputs.

**Detection:** `gross_profit` ends up with 6+ decimal places
(extractor's calculation) rather than the 1 decimal the PDF would
have rounded to.

### F.3 Judgement in `content_summary` of `unknown_sections`

**Bad:**

```yaml
notes:
  unknown_sections:
    - title: "Note 42 — Related-party transactions with founder's HoldCo"
      content_summary: >
        Indicates material related-party exposure; governance concern.
```

**Good:**

```yaml
content_summary: >
  Disclosed transactions with a founder-controlled holding company:
  rent expense HKD 2.5M, interest-free loan receivable HKD 8M. Also
  disclosed on notes.related_parties.
```

**Detection:** grep for "concern", "risk", "weakness", "strength" in
`unknown_sections`.

### F.4 Assigning `material_positive` / `material_negative` to any
  subsequent event

**Bad:** every subsequent event gets tagged `material_positive` or
`material_negative` based on whether the extractor thinks it's
good or bad.

**Good:** the `impact` field is an **evidenced** tag. Use
`material_positive` / `material_negative` only when the PDF or
management commentary explicitly frames it that way. Use `pending`
otherwise.

**Detection:** re-read the subsequent events footnote. If the
tag's polarity isn't in the text, default to `pending`.

## Group G — `is_subtotal` flagging (Phase 1.5.3)

### G.1 Flagging non-subtotal lines

**Bad:**

```yaml
- {order: 4, label: "Selling expenses", value: "-95", is_subtotal: true}
```

Selling expenses is a leaf line, not a subtotal.

**Good:**

```yaml
- {order: 4, label: "Selling expenses", value: "-95"}
```

**Detection:** validator S.IS walk FAILs — the subtotal-flagged line
doesn't equal the sum of preceding leaves.

### G.2 Missing subtotal flag on a reported subtotal

**Bad:**

```yaml
- {order: 3, label: "Gross profit", value: "290"}
```

The walker then treats Gross profit as a leaf, adds it to Revenue +
Cost of sales + Gross profit, and the next subtotal fails.

**Good:**

```yaml
- {order: 3, label: "Gross profit", value: "290", is_subtotal: true}
```

### G.3 Inventing a subtotal the PDF doesn't show

The issuer's condensed IS may not disclose "Gross profit". Don't add
one just to make the validator happy. Report only the subtotals the
PDF prints.

## Group H — BS `section` assignment (Phase 1.5.3)

### H.1 Mixing current and non-current under one section

**Bad:**

```yaml
- {order: 1, label: "Cash", value: "200", section: "current_assets"}
- {order: 2, label: "PP&E", value: "700", section: "current_assets"}
```

PP&E is a non-current asset. Setting section wrong breaks the section
walk.

**Good:**

```yaml
- {order: 1, label: "Cash", value: "200", section: "current_assets"}
- {order: 2, label: "PP&E", value: "700", section: "non_current_assets"}
```

### H.2 Using company labels instead of section enum values

**Bad:**

```yaml
- section: "Current Assets"
- section: "非流動資產"
```

**Good:**

The section field is a closed vocabulary:
`current_assets` / `non_current_assets` / `total_assets` /
`current_liabilities` / `non_current_liabilities` /
`total_liabilities` / `equity`. CF: `operating` / `investing` /
`financing` / `fx_effect` / `subtotal`. IS: leave unset.

### H.3 Forgetting the cross-section grand totals

The BS has "Total current assets" (current_assets subtotal), "Total
non-current assets" (non_current_assets subtotal), AND "Total
assets" (cross-section grand total). Each needs its own LineItem
with the appropriate section + `is_subtotal: true`:

```yaml
- section: "current_assets"      # in a current_assets section
  label: "Total current assets"
  is_subtotal: true
- section: "non_current_assets"
  label: "Total non-current assets"
  is_subtotal: true
- section: "total_assets"        # grand total → its own section
  label: "Total assets"
  is_subtotal: true
```

## Closing

Run the validator after every extraction. Read the warn list. Read
the completeness list. Fix the easy things. For everything else,
page-reference it and flag in `extraction_notes`.

The single habit that prevents most of the above:

> **"Am I copying what's on the page, or am I adding something?"**

If you're adding, stop.
