# Schema evolution across fiscal years

**When to use this guide:** whenever you're extracting multiple
fiscal years from the same issuer and the line-item names or
classifications differ between them.

The core rule: **preserve what the company reported, for the year it
reported it.** Do not silently re-bucket prior-year numbers into the
current-year taxonomy.

## The preserve-as-reported principle

Each fiscal year is extracted using that year's reported line names.
When FY2024 introduces `"Selling and marketing expenses"` where
FY2023 reported `"Distribution costs"` and FY2022 reported `"Selling
expenses"`, all three go in separately:

```yaml
income_statement:
  FY2024:
    selling_marketing: "-95.0"         # as reported in FY2024
  FY2023:
    selling_marketing: "-88.0"         # FY2023 column on FY2024 AR
                                       # (restated to match new name —
                                       # the company did the restatement
                                       # in the AR narrative)
  FY2022:
    # FY2022 original AR used different name entirely
    extensions:
      selling_expenses: "-82.0"        # FY2022's original label
```

**The extractor does not restate.** If the company's AR re-casts
prior-year numbers into the new taxonomy (most ARs do for the
immediately prior year), extract that restated number. If the AR
presents only the current year and the historical `*_by_year` table
uses the old name, use extensions + a note in `extraction_notes`.

## Common evolution patterns

### IFRS 16 adoption (typical 2019–2020)

Pre-adoption years have no `rou_assets`, no `lease_liabilities_*`, no
`lease_interest_expense`. Operating leases were in the `commitments`
note.

```yaml
balance_sheet:
  FY2024:
    rou_assets: "380.0"
    lease_liabilities_current: "60.0"
    lease_liabilities_noncurrent: "310.0"
  FY2019:
    # IFRS 16 adoption year — transitional
    rou_assets: "340.0"                # post-adoption balance
  FY2018:
    # Pre-adoption — no IFRS 16 fields
    # Operating lease commitments in notes:
    pass                               # simply omit these fields
```

And in metadata:

```yaml
metadata:
  extraction_notes: >
    IFRS 16 adopted 1 January 2019 with modified retrospective
    approach. Pre-FY2019 periods do not populate rou_assets or
    lease_liabilities_* on the BS or the LeaseNote. Pre-FY2019
    operating lease commitments captured in
    notes.commitments_contingencies.operating_lease_future.
```

### Segment reorganisations

A common issue: FY2024 reports three geographic segments (`"Greater
China"`, `"Germany / Europe"`, `"Rest of World"`); FY2022 reported
two (`"Asia"`, `"Europe"`).

**Extract each year in its own taxonomy:**

```yaml
segments:
  by_geography:
    FY2024:
      "Greater China": {revenue: "420.0"}
      "Germany / Europe": {revenue: "160.0"}
      "Rest of World": {revenue: "0.0"}    # or omit if the segment
                                           # doesn't exist in FY2024
    FY2022:
      "Asia": {revenue: "380.0"}            # FY2022's own segmentation
      "Europe": {revenue: "105.0"}
```

And flag in `extraction_notes`:

```yaml
metadata:
  extraction_notes: >
    Segment taxonomy changed in FY2023 (Asia split into Greater China
    + Rest of World; Europe renamed to Germany / Europe). Historical
    segment data not restated by the issuer — each year uses its own
    segment names. Do not naively sum across years.
```

### Restatements

When an AR restates a prior-year number due to IFRS 15 revenue
recognition, a material error correction, or a discontinued operation
reclassification:

1. Extract the **restated** numbers (from the current AR) for the
   restated year. These are the comparable numbers.
2. In `extraction_notes`, describe the restatement:

   ```yaml
   metadata:
     extraction_notes: >
       FY2023 IS restated in FY2024 AR: revenue down HKD 8M, net income
       down HKD 2M following correction of over-accrued warranty
       provision. Original FY2023 AR reported revenue HKD 528M; this
       YAML uses the FY2024 AR restated number (HKD 520M).
   ```

3. Do NOT extract both original and restated as separate periods.
   The "FY2023" key carries one set of numbers — use the restated
   one.

### Reclassifications between years

A line that was in "Other operating expenses" in FY2022 may move to
"General and administrative" in FY2024. Options:

- **If the AR restates FY2023 (the comparative year) to the new
  taxonomy** — extract FY2024 + restated FY2023 in the new taxonomy.
- **If the AR does not restate** — extract FY2023 in its original
  taxonomy; note the discontinuity.

Never silently combine. If you're uncertain whether the movement is
material, err toward extensions:

```yaml
income_statement:
  FY2024:
    general_administrative: "-65.0"
    extensions:
      g_and_a_inclusive_of_formerly_other_opex: "true"
  FY2023:
    general_administrative: "-55.0"
    other_operating_expenses: "-5.0"
    extensions:
      g_and_a_comparable_to_fy2024: "false"
```

### Share-count changes

Splits, consolidations, and weighted-average shifts mean FY2024's
`shares_basic_weighted_avg` is not comparable to FY2022's. That's
fine — the YAML carries each year as reported. Downstream CAGR math
works with `historical.shares_outstanding_by_year`, which is a
single series.

```yaml
historical:
  shares_outstanding_by_year:
    "2020": "198.0"
    "2022": "200.0"         # share issuance in 2021
    "2024": "200.0"
```

## When to use extensions vs. typed fields

- **Typed field exists and the company's line clearly maps to it** →
  use the typed field. Names don't have to match exactly.
- **Typed field exists but the line only partially maps** → use the
  typed field + add an extensions row documenting the partial match:

  ```yaml
  income_statement:
    FY2024:
      selling_marketing: "-95.0"
      extensions:
        selling_marketing_includes_brand_investment: "true"
  ```

- **No typed field exists and the line is sector-specific** → use
  extensions with a descriptive snake_case key.
- **Line is truly one-off and low-signal** → `notes.unknown_sections`
  with `reviewer_flag: true`. See
  [`unknown_sections_protocol.md`](unknown_sections_protocol.md).

## Extractor doesn't infer

If the FY2022 AR doesn't report `gross_profit` because the company
only started disclosing it in FY2024, **do not compute it**. Leave
`gross_profit: None`. Phase 2 multi-period analytics will handle
back-filling where the inputs support it — the extractor's job is to
capture what's on the page.

```yaml
income_statement:
  FY2022:
    revenue: "485.0"
    cost_of_sales: "-248.0"
    # gross_profit not reported by the company in FY2022 — omit
    operating_income: "85.0"
```

## Common evolution traps

- **Silently re-bucketing.** Moving FY2022 "Distribution costs"
  (reported under `"Other operating expenses"` column) into the
  FY2024 `selling_marketing` field without a note. Breaks CAGR math
  + hides the reclassification.
- **Extracting both original and restated numbers as two periods.**
  One period per label. Restated wins.
- **Over-populating early-year fields that the company didn't
  report.** Leave them `None`. The validator won't complain — it
  only checks identities and required notes.
- **Assuming segment taxonomy stability.** Always read the narrative
  around segment tables — reorganisations get a footnote; honour it.
- **Copying the prior-year column without reading the footnote.**
  "Comparative amounts have been restated to conform with current
  period presentation" — that footnote tells you FY2023 = restated.
