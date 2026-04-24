# Capital Allocation Schema — v1.0

**Source of truth**: [`src/portfolio_thesis_engine/forecast/capital_allocation_consumer.py`](../../src/portfolio_thesis_engine/forecast/capital_allocation_consumer.py)
**Used by**: three-statement forecast engine (Sprint 4A-beta) — consumed by DCF / DDM / RI downstream (Sprint 4B).
**File location**: `data/yamls/companies/<TICKER>/capital_allocation.yaml`
**Companion**: [scenarios_schema.md](./scenarios_schema.md)

## Purpose

Declares the company's forward capital-deployment policy. The forecast orchestrator reads this file once per ticker and threads the parsed policies into per-year capex / dividend / buyback / M&A deployment / debt-delta schedules. The three-statement solver then converges cash balance against the resulting CFI + CFF flows.

Policies here are **scenario-agnostic today**. Sprint 4B.2 will add scenario-level tilts (e.g. `m_and_a_accelerated` getting a 1.5× deployment multiplier); the loader preserves raw YAML for that future work.

## Loader behaviour

`load_capital_allocation(ticker)` returns `ParsedCapitalAllocation` or `None` when the file is missing. Orchestrators fall back to `default_policies()` (30% payout, no buybacks, no M&A, zero debt, no issuance).

## Top-level `ParsedCapitalAllocation`

| Field | Type | Required | Notes |
|---|---|---|---|
| `ticker` | `str` | Yes | Matches the company directory name. |
| `last_updated` | `str` | Yes | ISO-8601 date; loader keeps as string. |
| `dividend_policy` | `ParsedDividendPolicy` | Yes | See below. |
| `buyback_policy` | `ParsedBuybackPolicy` | Yes | See below. |
| `debt_policy` | `ParsedDebtPolicy` | Yes | See below. |
| `ma_policy` | `ParsedMAPolicy` | Yes | See below. |
| `share_issuance_policy` | `ParsedShareIssuancePolicy` | Yes | See below. |
| `net_cash_baseline` | `Decimal` | No | Pulled from `historical_context.cash_evolution[-1].net_cash` when present. |

### Raw YAML shape

The on-disk YAML wraps the five policies under a `policies:` block. The loader flattens them onto `ParsedCapitalAllocation`. Additional free-form blocks (`evidence_sources`, `historical_context`, `source_documents`) are preserved by the YAML but ignored by the current parser — reserved for Sprint 4B.2.

```yaml
target_ticker: 1846.HK
last_updated: 2026-04-24
policies:
  dividend_policy: {...}
  buyback_policy: {...}
  debt_policy: {...}
  ma_policy: {...}
  share_issuance_policy: {...}
historical_context: {...}
evidence_sources: [...]
```

---

## Policy schemas

### `ParsedDividendPolicy`

| Field | Type | Default | Notes |
|---|---|---|---|
| `type` | `str` | `"PAYOUT_RATIO"` | `PAYOUT_RATIO`, `FIXED_AMOUNT`, `GROWTH_PATTERN`, `CONDITIONAL`, `ZERO`. |
| `payout_ratio` | `Decimal \| None` | `None` | Required when `type == "PAYOUT_RATIO"`. |
| `fixed_amount` | `Decimal \| None` | `None` | Required when `type == "FIXED_AMOUNT"` or `"GROWTH_PATTERN"`. |
| `growth_rate` | `Decimal \| None` | `None` | Annual growth applied to `fixed_amount` under `GROWTH_PATTERN`. |
| `rationale` | `str` | `""` | Free-form narrative. |
| `confidence` | `str` | `"MEDIUM"` | `HIGH` / `MEDIUM` / `LOW`. |

Forecast engine behaviour: `PAYOUT_RATIO` applies `max(0, net_income × payout_ratio)` per year; `FIXED_AMOUNT` is flat; `GROWTH_PATTERN` compounds `fixed_amount` by `growth_rate`; anything else (including `ZERO` and unmet `CONDITIONAL`) produces zero dividends.

### `ParsedBuybackPolicy`

| Field | Type | Default | Notes |
|---|---|---|---|
| `type` | `str` | `"NONE"` | `FIXED_ANNUAL`, `PROGRAMMATIC`, `CONDITIONAL`, `NONE`. |
| `annual_amount` | `Decimal` | `0` | Absolute outflow when the policy is active. `annual_amount_if_condition_met` is accepted as YAML synonym. |
| `condition` | `str \| None` | `None` | Freeform; e.g. `NEW_MANDATE_APPROVED`. |
| `rationale` | `str` | `""` | |
| `confidence` | `str` | `"MEDIUM"` | |

Forecast engine: any of `FIXED_ANNUAL` / `PROGRAMMATIC` / `CONDITIONAL` with non-zero `annual_amount` fires every year of the horizon. `CONDITIONAL` is treated as "condition holds" in Sprint 4B — a conservative midpoint. Sprint 4B.2 will add per-scenario toggling.

### `ParsedDebtPolicy`

| Field | Type | Default | Notes |
|---|---|---|---|
| `type` | `str` | `"MAINTAIN_CURRENT"` | `MAINTAIN_ZERO`, `MAINTAIN_CURRENT`, `TARGET_RATIO`, `LEVER_UP`, `REPAY`. |
| `current_debt` | `Decimal` | `0` | Opening debt value (informational; base-year debt comes from canonical state). |
| `target_debt_to_ebitda` | `Decimal \| None` | `None` | Reserved — `TARGET_RATIO` wiring lands in Sprint 4B.2. |
| `alternative_for_ma` | `dict \| None` | `None` | Sub-block describing how debt reacts to M&A deployment (see below). |
| `rationale` | `str` | `""` | |
| `confidence` | `str` | `"MEDIUM"` | |

**`alternative_for_ma`** (optional): `{"type": "LEVER_UP", "target_debt_to_ebitda_if_ma": <Decimal>}`. Fires only when `ma_policy.funding_source` is `DEBT` or `MIXED` — cash-funded M&A does **not** trigger it even when this block is present.

Forecast engine behaviour (Sprint 4B):

| `type` | Per-year debt delta |
|---|---|
| `MAINTAIN_ZERO` | `0` unless `alternative_for_ma` fires (sketch: Y1 = M&A deployment, Y2–YN = 0) |
| `MAINTAIN_CURRENT` | `0` |
| `REPAY` | `−current_debt / horizon` per year |
| `TARGET_RATIO` / `LEVER_UP` | `0` in Sprint 4B (implementation deferred to 4B.2) |

### `ParsedMAPolicy`

| Field | Type | Default | Notes |
|---|---|---|---|
| `type` | `str` | `"NONE"` | `OPPORTUNISTIC`, `PROGRAMMATIC`, `ACQUIRE_ONLY`, `SELL_ONLY`, `NONE`. |
| `annual_deployment_target` | `Decimal` | `0` | Outflow magnitude (HKD for EuroEyes). |
| `funding_source` | `str` | `"CASH"` | `CASH`, `DEBT`, `MIXED`, `EQUITY`. Key for debt-policy LEVER_UP wiring. |
| `geography_focus` | `list[str]` | `[]` | Reference only — no engine branch on geography today. |
| `rationale` | `str` | `""` | |
| `confidence` | `str` | `"MEDIUM"` | |

Forecast engine: `OPPORTUNISTIC`, `PROGRAMMATIC`, `ACQUIRE_ONLY` deploy `annual_deployment_target` every year; anything else returns zero.

### `ParsedShareIssuancePolicy`

| Field | Type | Default | Notes |
|---|---|---|---|
| `type` | `str` | `"ZERO"` | `ZERO`, `OPPORTUNISTIC`, `DILUTIVE_PROGRAM`. |
| `annual_dilution_rate` | `Decimal` | `0` | Reserved — share-count evolution hook. |
| `rationale` | `str` | `""` | |
| `confidence` | `str` | `"HIGH"` | |

Share issuance does not yet feed the forecast engine (shares are held constant unless `IncomeStatementYear.shares_outstanding_evolution` is supplied explicitly). Sprint 4B.2+ work.

---

## Example — EuroEyes (1846.HK)

The EuroEyes policy pack is the canonical reference — net-cash, cash-funded M&A, progressive dividend:

```yaml
target_ticker: 1846.HK
last_updated: 2026-04-24

policies:
  dividend_policy:
    type: PAYOUT_RATIO
    payout_ratio: 0.115
    growth_with_ni: true
    rationale: "FY2023 final + FY2024 final + H1 2025 interim show progressive per-share growth with blended payout ~11-12% of NI ..."
    confidence: MEDIUM

  buyback_policy:
    type: CONDITIONAL
    condition: NEW_MANDATE_APPROVED
    annual_amount_if_condition_met: 20_000_000
    rationale: "January 2025 execution (HK$18.33M deployed, 5.21M shares cancelled) demonstrates willingness ..."
    confidence: MEDIUM

  debt_policy:
    type: MAINTAIN_ZERO
    current_debt: 0
    alternative_for_ma:
      type: LEVER_UP
      target_debt_to_ebitda_if_ma: 1.0
    rationale: "Zero long-term borrowings maintained consistently FY2020 through H1 2025 ..."
    confidence: HIGH

  ma_policy:
    type: OPPORTUNISTIC
    annual_deployment_target: 50_000_000
    timing_uncertainty: MEDIUM
    geography_focus: ["Germany", "Denmark", "France", "Europe", "Americas"]
    funding_source: CASH              # cash-funded → debt policy's LEVER_UP alternative does NOT fire
    rationale: "Goodwill progression HK$7.6M (FY2021) → HK$298.4M (H1 2025) evidences active mid-market acquisition programme ..."
    confidence: MEDIUM

  share_issuance_policy:
    type: ZERO
    annual_dilution_rate: 0.00
    rationale: "No material primary equity issuance observed FY2020 through H1 2025 ..."
    confidence: HIGH
```

### Resulting forecast behaviour (EuroEyes base scenario)

- **Dividends**: ≈ 11.5% of NI each year.
- **Buybacks**: HK$20M / year (conditional treated as active midpoint).
- **M&A**: HK$50M / year, cash-funded.
- **Debt**: stays at 0 (cash-funded M&A does not fire `LEVER_UP`).
- **Share count**: held constant at base-year value.

See [phase2_architecture.md](../phase2_architecture.md) for how these numbers flow through the three-statement solver into forward ratios.

---

## Design rationale

- **`funding_source` governs leverage**: the Sprint 4B solver only fires `LEVER_UP` when `ma_policy.funding_source ∈ {DEBT, MIXED}`. `CASH` keeps the projected balance sheet debt-free even if `debt_policy.alternative_for_ma` is populated — prevents accidental leverage introduction for net-cash names.
- **Conditional buybacks treated as active**: in the absence of scenario-level toggling, assuming the buyback mandate holds is the conservative midpoint. Sprint 4B.2 will introduce per-scenario overrides (`bull_operational` → full mandate; `bear_structural` → suspended).
- **Scenario-agnostic today**: a single policy pack serves every scenario. The orchestrator's `_scenario_adjusted_capital_allocation` is a placeholder returning the input unchanged — future hook for tilts.

---

## Drift prevention

Pydantic is the canonical contract (`ParsedCapitalAllocation` and its five sub-classes). This document is regenerated from the schema's defaults and docstrings; keep them synchronised when extending policy types.

## Changes vs pre-v1.0

Field names, defaults and enum string values above match Sprint 4B's `capital_allocation_consumer.py`. The loader is forgiving — unknown YAML keys are silently ignored so analyst-authored files can carry metadata (`timing_uncertainty`, `growth_with_ni`, evidence references) without rejection.
