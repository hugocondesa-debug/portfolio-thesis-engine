# Sign conventions

**When to use this guide:** every time you copy a number from a PDF.
Getting signs wrong is the second-most common extraction bug (after
unit scale).

## The one rule the schema enforces

**Use `-` for negatives. Never parentheses.**

PDFs routinely use the accounting convention `(100)` for `-100`. The
YAML schema does not. Convert every parenthesised number before
writing.

```yaml
# BAD — parentheses leak into the YAML
cost_of_sales: "(290.0)"    # rejected by the parser
capex: "(75.0)"             # rejected by the parser

# GOOD — explicit "-"
cost_of_sales: "-290.0"
capex: "-75.0"
```

## Sign expectations by statement

### Income statement

| Field                         | Typical sign | Why                                            |
| ----------------------------- | ------------ | ---------------------------------------------- |
| `revenue`                     | **+**        | Top line.                                      |
| `cost_of_sales`               | **−**        | Subtracts from revenue.                        |
| `gross_profit`                | **+**        | Revenue + cost_of_sales (both with sign).      |
| `selling_marketing`           | **−**        | Opex.                                          |
| `general_administrative`      | **−**        | Opex.                                          |
| `research_development`        | **−**        | Opex.                                          |
| `other_operating_expenses`    | **−**        | Opex.                                          |
| `depreciation_amortization`   | **−**        | Expense line.                                  |
| `operating_expenses_total`    | **−**        | Sum of opex lines.                             |
| `operating_income`            | **+**        | Residual after opex; positive for profitable.  |
| `finance_income`              | **+**        | Interest / dividend income.                    |
| `finance_expenses`            | **−**        | Interest expense.                              |
| `income_tax`                  | **−**        | Tax expense — NOT the rate.                    |
| `net_income`                  | **+**        | Positive when profitable.                      |

**Verification walk:** `revenue + cost_of_sales + opex + D&A
≈ operating_income` (all fields carry their sign, so the sum equals
operating income). If your numbers don't walk, a sign is wrong.

### Balance sheet

Assets and liabilities are **always positive** with three exceptions:

| Field                         | Sign | Why                                                |
| ----------------------------- | ---- | -------------------------------------------------- |
| `treasury_shares`             | **−** | Reduction of equity — reported as negative.        |
| `accumulated_depreciation`    | **−** | Deduction from gross PP&E.                         |
| Any "allowance for X" on AR   | **−** | Reduction of the receivable.                       |

**Verification walk:** `total_assets = total_liabilities + total_equity`
(sum exactly — this is an identity).

### Cash flow

CF is the trickiest because the direction of the cash movement
determines sign:

| Field                         | Typical sign | Why                                            |
| ----------------------------- | ------------ | ---------------------------------------------- |
| `net_income_cf`               | Sign of NI   | Usually positive.                              |
| `depreciation_amortization_cf`| **+**        | Non-cash add-back.                             |
| `working_capital_changes`     | Varies       | Positive = WC release; negative = WC build.    |
| `operating_cash_flow`         | **+**        | Usually positive for going concern.            |
| `capex`                       | **−**        | Cash outflow for PP&E.                         |
| `acquisitions`                | **−**        | Cash outflow.                                  |
| `divestitures`                | **+**        | Cash inflow from sale.                         |
| `investing_cash_flow`         | **−** (usually) | Growing companies invest net.              |
| `dividends_paid`              | **−**        | Cash outflow to shareholders.                  |
| `debt_issuance`               | **+**        | Cash inflow.                                   |
| `debt_repayment`              | **−**        | Cash outflow.                                  |
| `share_issuance`              | **+**        | Cash inflow.                                   |
| `share_repurchases`           | **−**        | Cash outflow.                                  |
| `financing_cash_flow`         | Varies       | Depends on debt/dividend mix.                  |
| `fx_effect`                   | Varies       | FX translation residual.                       |
| `net_change_in_cash`          | Varies       | `CFO + CFI + CFF + fx_effect`.                 |

**Verification walk:** `CFO + CFI + CFF + fx_effect = net_change_in_cash`
(identity). And `cash_opening + net_change_in_cash = cash_closing`.

## Signs within notes

### Tax reconciling items

`TaxReconciliationItem.amount` is signed **in the direction of the
effect on tax expense**:

- A non-deductible expense *increases* tax → **positive** amount.
- A credit / lower foreign-rate *decreases* tax → **negative** amount.

```yaml
notes:
  taxes:
    reconciling_items:
      - description: "Non-deductible expenses"
        amount: "1.5"                 # adds 1.5 to statutory tax
        classification: "operational"
      - description: "Foreign-rate differential (DE 15% vs HK 16.5%)"
        amount: "-0.2"                # reduces tax by 0.2
        classification: "operational"
```

### Provisions

`ProvisionItem.amount` is signed **in the direction of the P&L impact**:

- A charge (expense) → **negative** amount.
- A release (credit to P&L) → **positive** amount.

```yaml
notes:
  provisions:
    - description: "Site closure restructuring charge"
      amount: "-30.0"                 # expense
      classification: "restructuring"
    - description: "Warranty provision release"
      amount: "5.0"                   # credit
      classification: "operating"
```

### Goodwill impairment

`GoodwillNote.impairment` is **negative** when there is an impairment
(it reduces goodwill).

```yaml
notes:
  goodwill:
    opening: "620.0"
    impairment: "-20.0"               # 20 of impairment
    closing: "600.0"                  # 620 - 20
```

### PP&E / intangibles movements

On the `PPENote` / `IntangiblesNote` movement tables:

- `additions` → **positive** (increase).
- `disposals` → **negative** (decrease).
- `accumulated_depreciation` → **negative** (contra-asset).
- `amortization` → **negative** (expense movement).
- `impairment` → **negative** (expense movement).

## Parentheses — what to do when you see them

Every PDF uses parentheses differently. Some rules:

1. `(290)` → `-290`. Always.
2. `290` where context says it's a subtraction → `-290`. You need to
   read the column header: "Cost of sales" column typically has
   positive numbers that *represent* a negative. Always confirm by
   checking the walk (revenue + cost_of_sales = gross_profit).
3. `290 negative` / `(290) negative` → `-290`. Double negative = still
   negative. Rare, but happens in narrative summaries.

## Sanity-check algorithm before submission

For every period, walk the IS:

```
residual = revenue + cost_of_sales + sum(opex_lines) + D&A
if |residual - operating_income| > 1% of operating_income:
    a sign is wrong. Find it.
```

For the BS:

```
identity = total_assets - (total_liabilities + total_equity)
if |identity| > 0:
    a sign is wrong OR you missed a line.
```

For the CF:

```
walk = operating_cash_flow + investing_cash_flow + financing_cash_flow + fx_effect
if |walk - net_change_in_cash| > 1% of |net_change_in_cash|:
    a sign is wrong OR a subtotal is wrong.
```

## Common sign traps

- **Tax expense as a positive number.** Some PDFs report "income tax
  expense 21.0" without the minus because it's a separate line in a
  deduction column. On the YAML it is `income_tax: "-21.0"`.
- **Finance expenses shown as positive in notes.** Note 6 may show
  "Interest on borrowings 18.0" — in the note context it's an
  absolute number. On the IS line `finance_expenses: "-18.0"`.
- **Working capital changes sign confusion.** "Increase in
  receivables" on a CF reconciliation is a *use* of cash — negative
  on the CF. "Decrease in receivables" is a *source* of cash —
  positive. Always read the arrow direction on the walk.
- **Dividends paid reported positively in headline.** CF line is
  `dividends_paid: "-25.0"`. Press releases describe "we paid 25.0 in
  dividends" — absolute number. Convert to negative in the YAML.
- **Treasury shares reported positively in share-capital note.** The
  movement table may list "Treasury shares 12.0" as an addition to
  the negative balance. On the BS line `treasury_shares: "-12.0"`
  (the balance itself, not the movement).
