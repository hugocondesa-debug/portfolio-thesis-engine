# Pre-submit validation checklist

Run these checks on every `raw_extraction.yaml` before shipping it
to `~/data_inputs/<ticker>/`. Most are also enforced by
`pte validate-extraction` — this checklist lets you self-audit
before the command runs.

## 1. Arithmetic identities

| Check                | Formula                                                | Tolerance |
| -------------------- | ------------------------------------------------------ | --------- |
| **BS identity**       | `total_assets = total_liabilities + total_equity`     | 0         |
| **BS current**        | `total_current_assets = Σ(current-asset lines)`       | 1 %       |
| **BS non-current**    | `total_non_current_assets = Σ(non-current lines)`     | 1 %       |
| **IS gross**          | `gross_profit ≈ revenue + cost_of_sales`              | 1 %       |
| **IS operating**      | `operating_income ≈ gross_profit − Σ(opex) − D&A`     | 1 %       |
| **IS below-the-line** | `net_income ≈ op_income + fin_inc + fin_exp + tax`    | 2 %       |
| **CF walk**           | `net_change_in_cash = CFO + CFI + CFF + fx_effect`    | 0         |
| **CF cash movement**  | `cash_opening + net_change_in_cash = cash_closing`    | 0         |

Strict validation catches the **BS identity** and **CF walk**. The
others are warn-level checks (`W.GP`, `W.OI`, `W.NI_WALK`). Fix
even warn-level failures before shipping unless you can point at a
specific reconciling footnote.

## 2. Cross-statement identities

| Check                       | What ties                                                            |
| --------------------------- | -------------------------------------------------------------------- |
| **NI on IS = NI on CF**      | `income_statement.<period>.net_income = cash_flow.<period>.net_income_cf` (when populated) |
| **D&A on IS = D&A on CF**    | `income_statement.<period>.depreciation_amortization ≈ cash_flow.<period>.depreciation_amortization_cf` |
| **CapEx on CF ≈ PPE walk**   | `|capex| ≈ ΔPPE_net + |D&A|` (warn at 5%)                             |
| **Cash on BS = end of CF**   | `balance_sheet.<period>.cash_and_equivalents = cash_at_end_of_period` |
| **RE walk**                  | `RE_open + net_income − dividends_paid ≈ RE_close` (tolerance 2%; small variance from OCI reclass acceptable) |
| **Lease liab walk**          | `lease_liab_close = lease_liab_open + additions − principal_payments` (from `LeaseNote`) |
| **Goodwill walk**            | `goodwill_close = goodwill_open + additions + impairment + fx_moves` (from `GoodwillNote`) |

The validator runs walks for W.CAPEX, W.DIV, W.RE, W.LEASE_WALK, and
W.GOODWILL_WALK. When a walk trips and your numbers are clean,
add an `extraction_notes` line pointing at the reconciling item the
PDF discloses (FX movements, acquisitions, OCI releases).

## 3. Completeness — P1 Industrial

Required notes (all 10 must be populated):

- [ ] `notes.taxes` (Module A)
- [ ] `notes.leases` (Module C)
- [ ] `notes.ppe`
- [ ] `notes.inventory`
- [ ] `notes.trade_receivables`
- [ ] `notes.trade_payables`
- [ ] `notes.employee_benefits`
- [ ] `notes.financial_instruments`
- [ ] `notes.commitments_contingencies`
- [ ] `notes.provisions` (Module B)

Recommended notes (aim for ≥ 4 of 5):

- [ ] `notes.goodwill` — required when the company has acquisitions.
- [ ] `notes.intangibles`
- [ ] `notes.share_based_compensation` — required when SBC expense
      is disclosed on the IS.
- [ ] `notes.pensions` — required when DB plan exists.
- [ ] `notes.acquisitions` — required when material deals in period.

Completeness target: ≥ 90 % of (required + recommended). The
validator surfaces per-note status (`C.R.<name>` and `C.O.<name>`).

## 4. Unit scale sanity

- [ ] `metadata.unit_scale` is declared (`units` / `thousands` /
      `millions`).
- [ ] Eyeball test: revenue in the YAML matches the magnitude in the
      PDF cover page. If the PDF says "HKD 580 million" and the
      YAML declares `unit_scale: "millions"` with `revenue: "580.0"`,
      that's consistent.
- [ ] Per-share fields (`eps_basic`, `eps_diluted`) are NOT scaled.
      They should look like per-share amounts (0.x, 1.x — not
      millions).
- [ ] Share counts (`shares_basic_weighted_avg`) are the raw count
      in the company's unit (sometimes millions, sometimes absolute).
      Confirm with the PDF header.
- [ ] All note `Decimal` fields use the same `unit_scale` as the
      statements.

## 5. Sign conventions

- [ ] `cost_of_sales`, `selling_marketing`, `general_administrative`,
      `research_development`, `other_operating_expenses`,
      `depreciation_amortization`, `finance_expenses`, `income_tax`
      are **negative**.
- [ ] `capex`, `acquisitions` (outflow), `dividends_paid`,
      `debt_repayment`, `share_repurchases` are **negative**.
- [ ] `treasury_shares`, `accumulated_depreciation` are **negative**.
- [ ] No parentheses anywhere in the YAML values. `(100)` → `-100`.
- [ ] Tax reconciling items' `amount` signs match the direction of
      effect on tax.
- [ ] Provision items' `amount` signs match the direction of P&L
      effect (negative for charge, positive for release).

## 6. External sanity (optional but strongly recommended)

For tickers on major exchanges (US / UK / EU / HK listed — anything
on FMP or yfinance):

- [ ] Revenue in YAML ≈ revenue on FMP for the same fiscal year
      (within 5 % — translation/restatement differences are
      normal).
- [ ] Net income ≈ FMP reported.
- [ ] Total assets ≈ FMP.
- [ ] Cash & equivalents ≈ FMP.

The pipeline's `cross_check` stage runs these automatically and
blocks on FAIL. Eyeballing before you ship catches the unit-scale
bug + sign bug + period-label-typo cases that would otherwise
surface as a blocking gate failure.

## 7. Metadata

- [ ] `metadata.ticker` is exchange-qualified (`1846.HK`, `MSFT`,
      `ASML.AS`).
- [ ] `metadata.document_type` is one of the 42 enum values (see
      [`document_types.md`](../document_types.md)).
- [ ] `metadata.fiscal_periods` has at least one entry.
- [ ] Exactly one fiscal period has `is_primary: true`.
- [ ] Every period-key in `income_statement` / `balance_sheet` /
      `cash_flow` matches a `fiscal_periods.period` entry.
- [ ] `source_file_sha256` is populated (helpful for re-run
      detection).

## 8. Running the validator

```bash
pte validate-extraction path/to/raw_extraction.yaml --profile P1
```

Expected output on a clean extraction:

```
Summary: strict=OK · warn=OK · completeness=OK
```

Acceptable output:

```
Summary: strict=OK · warn=WARN · completeness=OK
```

`warn=WARN` is normal — real companies trip close-call walks (CapEx
vs. ΔPP&E + D&A within 1 % of the tolerance, dividend walk with a
small OCI reclass, etc.). Read each warn and confirm it's benign.

**Not acceptable:**

```
Summary: strict=FAIL · ...
```

Fix every strict FAIL before shipping. The pipeline blocks on these.

## 9. Final sanity

Before committing the YAML:

- [ ] Every uncertain extraction has a page-reference comment:
      `revenue: "580.0"  # AR p.42 consolidated`.
- [ ] `unknown_sections` entries all have `reviewer_flag: true`.
- [ ] `extraction_notes` mentions any restatement, reclassification,
      or unusual one-off the PDF discloses.
- [ ] `extraction_date` = today's date.
- [ ] `extraction_version` incremented if you're revising a prior
      extraction of the same document.

When all nine sections are clean, ship it.
