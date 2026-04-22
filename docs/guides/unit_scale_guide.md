# Unit scale — the single most common extraction bug

**When to use this guide:** before you start extracting, and again
when the validator surfaces suspicious magnitudes.

If revenue comes out 1000× too large or too small, check `unit_scale`
first. It's the cause 80% of the time.

## The one rule

**`metadata.unit_scale` is a single value for the whole document.**

Allowed values: `units`, `thousands`, `millions`.

The app's parser multiplies every monetary `Decimal` by the
corresponding factor (`1` / `1_000` / `1_000_000`) on load. Modules,
analysis, valuation, and the ficha all see base-unit values.

**You do NOT multiply when extracting.** Copy the number as reported.
Declare `unit_scale: "millions"` once in metadata, and the pipeline
handles it.

```yaml
metadata:
  unit_scale: "millions"

income_statement:
  FY2024:
    revenue: "580.0"        # The PDF says "580.0" in its millions column.
                            # Parser produces Decimal("580000000") downstream.
```

## Fields that ARE scaled

Every monetary `Decimal` on:

- `IncomeStatementPeriod` — revenue, costs, expenses, subtotals, net
  income, all below-the-line items.
- `BalanceSheetPeriod` — every asset / liability / equity line.
- `CashFlowPeriod` — every CFO / CFI / CFF line.
- Every `Decimal` in the note types (`TaxNote`, `LeaseNote`, etc.).
- `HistoricalData.*_by_year` values.
- `Segments` metric values.
- `extensions` dicts on statements / notes.
- `OperationalKPIs` values **when the metric name implies a monetary
  unit** (e.g. `total_compensation_hkd`). If the metric is a count
  (`patient_visits_thousands`), **it is not scaled** — the parser
  treats every OperationalKPIs value as-is. To avoid ambiguity,
  **include the unit in the metric name**.

## Fields that are NOT scaled — exceptions

**Per-share amounts** — `eps_basic`, `eps_diluted`.

```yaml
income_statement:
  FY2024:
    revenue: "580.0"           # millions → Decimal(580M) downstream
    eps_basic: "0.375"         # per-share → stays Decimal("0.375")
    eps_diluted: "0.370"       # per-share → stays Decimal("0.370")
```

**Share counts** — `shares_basic_weighted_avg`,
`shares_diluted_weighted_avg`, `non_controlling_interests` when
expressed as a share count (rare).

```yaml
shares_basic_weighted_avg: "200.0"     # 200 million shares — but the
                                       # field is a count, not a monetary
                                       # value. Stays as 200.0 base unit.
```

**Tax rates** — `effective_tax_rate_percent`,
`statutory_rate_percent`. These are percentages; they pass through
the parser unchanged.

```yaml
notes:
  taxes:
    effective_tax_rate_percent: "21.9"   # stays 21.9, NOT 21_900_000
```

**Operational KPIs** — free-form, always as reported. The parser does
not touch them.

## Detecting mid-document scale changes

Some filings mix scales. Japanese `tdnet_disclosure` filings are
notorious: IS in millions, segment tables in thousands. Before
extracting:

1. **Read the cover page of every statements section.** It will say
   "All figures in JPY millions" (or thousands, or units).
2. **Read the cover page of every note.** Most notes inherit the
   statements' scale, but disclosure of SBC grants often switches to
   absolute units.
3. **Read segment tables.** Segment disclosures sometimes use
   thousands while the primary statements use millions.
4. **Compare a cross-check:** take a line that appears on both the
   IS and a note (e.g. `D&A`). If the numbers don't match, scales
   differ.

**When scales differ within the document:**

- **Pick one scale for the whole YAML** (usually `millions` — most
  natural for large caps).
- **Manually normalise every number** from the other scale BEFORE
  writing the YAML. The YAML must have one consistent scale.
- **Add a note in `extraction_notes`:**
  `"IS in HKD millions; SBC note in HKD units — normalised to
   millions in this YAML."`

## Common scale traps

- **Declared `millions`, extracted actual base-unit values.** Parser
  multiplies the already-huge number by 1M. Revenue becomes
  $580_000_000_000_000. The cross-check gate catches this (delta >
  1M% vs FMP), but you've already wasted an hour.
- **Declared `units`, extracted values reported in thousands.**
  Opposite of above. Numbers look suspiciously small; guardrail A
  identity checks may still pass if everything was scaled
  consistently wrong, but the cross-check gate flags the gap vs FMP.
- **Mixed thousands/millions in segment tables.** See above.
- **US 10-K filings sometimes use `units` for some line items and
  `thousands` for others.** Check footnotes. Most file in either
  pure thousands or pure millions; the mixed case is rare.
- **Operational KPI scaled by mistake.** You wrote
  `patient_visits: "285"` for "285,000 visits" — the parser keeps
  it as 285 (correct for operational KPIs). But then a downstream
  script interprets `patient_visits` as "visits" and reads 285. Fix
  by using the suffix: `patient_visits_thousands: "285"` — the name
  encodes the unit.

## Example — EuroEyes AR 2024

Cover of the consolidated financial statements:

> "The consolidated financial statements are presented in Hong Kong
> dollars (`HKD`), and all values are rounded to the nearest million
> (`HKD'm`) except when otherwise indicated."

So:

```yaml
metadata:
  reporting_currency: "HKD"
  unit_scale: "millions"
```

Revenue row: "580,034" (PDF says 580,034, in thousands? Or 580 in
millions?). Read the column header: "HKD'm" → millions. So the PDF
is rounding; the actual number is 580.034 million. Extract:

```yaml
income_statement:
  FY2024:
    revenue: "580.0"           # Rounded to 1 dp for consistency.
```

Parser produces `Decimal("580000000.0")` downstream.

EPS in the same IS: "0.375" — per-share, not scaled. Stays `0.375`.

## Verify after extraction

After writing the YAML, run:

```bash
pte validate-extraction path/to/yaml --profile P1
```

Warnings labelled `W.MAG` or `W.CROSS_CHECK` are the validator
telling you a magnitude looks off. The cross-check gate (when the
ticker is on FMP / yfinance) compares extracted revenue / net_income
/ total_assets vs live external data — a 1000× discrepancy is the
unmistakable fingerprint of a scale bug.
