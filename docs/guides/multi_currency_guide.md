# Multi-currency operations

**When to use this guide:** whenever the issuer has material
operations in a currency different from the reporting currency.

The schema declares **one** `reporting_currency`. Everything else —
functional currencies of subsidiaries, transactional exposures, FX
translation — goes on the narrative notes or via extensions dicts.

## The three currencies you'll encounter

1. **Reporting currency** — the currency the consolidated statements
   are presented in. This is what `metadata.reporting_currency`
   declares. For EuroEyes it's `HKD`.

2. **Functional currency** — the currency of the primary economic
   environment each subsidiary operates in. German clinics' functional
   currency is `EUR`; Chinese clinics' is `CNY`. These don't appear
   on the YAML as typed fields — they surface in the
   `financial_instruments.market_risk` narrative and in extensions
   dicts.

3. **Transactional currency** — the currency of individual transactions
   (e.g. an equipment purchase billed in `USD`). Almost never
   captured in `raw_extraction.yaml`; too granular for the schema.

## Declaration pattern

```yaml
metadata:
  reporting_currency: "HKD"     # ISO 4217. One of: USD EUR GBP CHF JPY HKD.

# Every monetary Decimal in the YAML is in HKD (after unit-scale
# normalisation). No exceptions.
```

Narrative notes describe the FX exposure qualitatively:

```yaml
notes:
  financial_instruments:
    market_risk: >
      Reporting currency HKD. Functional currencies: HKD (Hong Kong
      operations), EUR (German clinics), CNY (Mainland China clinics).
      35% of operating costs are EUR-denominated; HKD is pegged to USD
      which provides partial natural hedge vs EUR. No FX derivatives
      outstanding at FY2024 year-end.
```

## Cash by currency — a common extension

Many issuers disclose **cash held by currency** in the financial
instruments or liquidity note. This is highly useful for FX-exposure
modelling but doesn't have a typed field on the schema. Use
`notes.extensions` or a dedicated extensions dict on the BS:

```yaml
balance_sheet:
  FY2024:
    cash_and_equivalents: "450.0"     # aggregate (all currencies, HKD-reported)
    extensions:
      cash_by_currency_hkd: "210.0"   # sum must equal cash_and_equivalents
      cash_by_currency_eur: "175.0"
      cash_by_currency_cny: "65.0"
```

Or on the narrative-friendly side:

```yaml
notes:
  financial_instruments:
    market_risk: >
      Cash by currency at FY2024 year-end: HKD 210M, EUR 175M, CNY 65M.
      Total HKD 450M matches the balance-sheet line.
```

**Pick one convention per issuer and stay consistent across years.**
Document the choice in `extraction_notes`.

## CTA — cumulative translation adjustment

When subsidiaries translate from functional → reporting, the residual
lands in `other_reserves` (sometimes called "foreign currency
translation reserve" or "CTA"). Two extraction rules:

1. Extract the CTA balance as **part of `other_reserves`** if the
   company aggregates it. Do not try to split the reserve into its
   components — that's downstream analytics work.
2. If the company breaks out the CTA separately (some Chinese
   issuers do), use the extensions dict on the BS:

   ```yaml
   balance_sheet:
     FY2024:
       other_reserves: "125.0"
       extensions:
         cta_reserve: "-45.0"         # CTA component of other_reserves
         statutory_reserve: "20.0"    # PRC companies
         hedging_reserve: "-12.0"     # IFRS 9 hedge reserve
   ```

   The sum of extension components should reconcile to the parent
   `other_reserves` line. Document in `extraction_notes`.

## FX effect on the cash flow

`CashFlowPeriod.fx_effect` is the translation impact on the cash
balance — not a cash flow in the operating sense. Extract it verbatim
from the CF reconciliation:

```yaml
cash_flow:
  FY2024:
    operating_cash_flow: "135.0"
    investing_cash_flow: "-75.0"
    financing_cash_flow: "-45.0"
    fx_effect: "0.0"                  # EuroEyes: pegged, minimal fx effect
    net_change_in_cash: "15.0"        # CFO + CFI + CFF + fx_effect
```

For issuers with material FX (e.g. UK company with 70% USD revenue),
this line can be in the millions.

## Reporting-currency pegs

Some reporting currencies are pegged (HKD ↔ USD, DKK ↔ EUR, XAF ↔ EUR).
The peg stabilises year-to-year comparability but does NOT make FX
exposure zero — underlying transactional currencies still matter.
Surface the peg in the narrative:

```yaml
notes:
  financial_instruments:
    market_risk: >
      HKD reporting currency is pegged to USD at 7.75-7.85/USD (Linked
      Exchange Rate System since 1983). Peg reduces translation noise
      on USD-functional cash but does not affect EUR or CNY exposure.
```

## Mixed-currency revenue tables

When the segment disclosure reports revenue by geography but the
underlying geographies have different functional currencies, the
reported numbers are **already translated to reporting currency**.
Do not adjust. Extract as reported:

```yaml
segments:
  by_geography:
    FY2024:
      "Greater China":
        revenue: "420.0"              # HKD, translated from CNY
      "Germany / Europe":
        revenue: "160.0"              # HKD, translated from EUR
```

Add an `extraction_notes` comment if the narrative surrounding the
segment table discloses pre-translation numbers that might be useful
for Phase 2 FX-exposure analysis:

```yaml
metadata:
  extraction_notes: >
    Segment revenue presented in HKD. Annex note discloses that Germany
    segment's EUR revenue was EUR 18.5M at average rate EUR/HKD 8.65
    (vs 8.95 prior year); not extracted as typed field — see Phase 2.
```

## Common multi-currency traps

- **Extracting a subsidiary's standalone statements as if they were
  consolidated.** Only the consolidated IS/BS/CF enters the YAML.
  Subsidiary standalone disclosures go to `extensions` or
  `unknown_sections` with `reviewer_flag: true`.
- **Declaring `reporting_currency: "EUR"` because "most revenue is in
  Europe".** Wrong. Reporting currency = the currency on the cover
  page of the consolidated statements. Doesn't matter where the
  revenue comes from.
- **Trying to re-translate segment numbers to original currency.**
  Don't. Accept the translated numbers as the company reported them.
  Downstream Phase 2 modules will handle FX-exposure analytics.
- **Confusing EUR-zone reporting with EUR functional currency.** An
  Irish company domiciled in Dublin can report in USD if its primary
  operations are in the US. `country_domicile: "IE"`,
  `reporting_currency: "USD"` — both true.
- **Treating CTA as an adjustment.** CTA is a balance (a reserve
  line). It doesn't get adjusted by Module A/B/C. Don't try.
