# Phase 2 Architecture — Valuation Engine

**Scope**: Sprints 2A through 4A-alpha.9.
**Tag at time of writing**: `v0.9.5-phase2-sprint4a-alpha-9-polish-and-docs`.
**Predecessor**: [`phase1_architecture.md`](./phase1_architecture.md) (extraction → cross-check → canonical state).

Phase 2 builds the valuation and forecast engine on top of Phase 1's canonical company state. Multi-methodology, multi-scenario, multi-profile. This document focuses on what is **new in Phase 2** and how Phase 1 artefacts flow into the valuation layer; it does not duplicate Phase 1 content.

---

## Data-flow diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│  Phase 1 outputs (see phase1_architecture.md)                       │
│  ├── CanonicalCompanyState (reclassified IS/BS/CF + NOPAT bridge)  │
│  ├── wacc_inputs.md (geographic mix, β, ERP/CRP, current_price)    │
│  └── Analyst YAMLs                                                  │
│      ├── valuation_profile.yaml   (P1-P6)                          │
│      ├── scenarios.yaml            (base + bull/bear/tail)         │
│      ├── capital_allocation.yaml   (deployment policies)           │
│      ├── leading_indicators.yaml   (sector signals, v1.1 buckets)  │
│      ├── peers.yaml / revenue_geography.yaml                       │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Sprint 3 — Cost of Capital (capital/)                              │
│  └── WACCGenerator + DamodaranReference                             │
│      ├── Bottom-up levered β                                        │
│      ├── Revenue-weighted CRP                                       │
│      ├── Currency-regime Fisher conversion                          │
│      └── Synthetic-rating CoD from interest coverage                │
│      Returns WACCComputation(cost_of_equity, cost_of_debt, wacc)    │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Sprint 2A/2B — Analytical layer (analytical/, briefing/)           │
│  ├── Historical normalisation + 5-way DuPont                        │
│  ├── Economic balance sheet                                         │
│  ├── Trend analysis + preliminary-signal cross-check                │
│  └── Analytical briefing (cost structure, leading indicators)       │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Sprint 4A-beta — Three-statement forecast engine (forecast/)       │
│  ├── IncomeStatement projection (margin fade + growth pattern)      │
│  ├── BalanceSheet roll-forward (PPE, goodwill, WC, equity)         │
│  ├── CashFlow derivation (indirect method)                          │
│  ├── Fixed-point iterative solver (cash convergence)                │
│  ├── ForwardWACCContext per-year (leverage-aware)                   │
│  └── Writes data/forecast_snapshots/<ticker>/*.json                 │
└─────────┬────────────────────────────────────────────────┬──────────┘
          │                                                 │
          ▼                                                 ▼
┌─────────────────────────────────────┐   ┌─────────────────────────────────────┐
│  Sprint 4A-alpha — DCF engines      │   │  Sprint 4B — Non-DCF engines        │
│  (dcf/)                             │   │  (valuation_methodologies/)         │
│  ├── P1 three-stage DCF             │   │  ├── DDM (consumes CF.dividends)    │
│  ├── Multiple-exit                  │   │  └── Residual Income (BV + PV(RI))  │
│  └── Transaction-precedent          │   └─────────────────────────────────────┘
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  ValuationEngine dispatcher (dcf/engine.py)                         │
│  Routes each scenario by methodology.type → wraps every result      │
│  in DCFValuation for uniform aggregation (E[V], P25, P75).         │
└──────────────────────────────┬──────────────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────────────┐
│  Outputs                                                             │
│  ├── Valuation snapshots     data/yamls/companies/<t>/valuation/   │
│  ├── Forecast snapshots       data/forecast_snapshots/<t>/          │
│  └── Ficha (markdown)         data/yamls/companies/<t>/ficha.yaml   │
└─────────────────────────────────────────────────────────────────────┘
```

---

## Module boundaries

| Path | Scope | Key sprint |
|---|---|---|
| `capital/` | `WACCGenerator`, geographic loaders, `WACCComputation` schema. | 3 |
| `analytical/` | Historical restatement, DuPont, economic BS, trend analysis. | 2A / 2B |
| `briefing/` | Analytical briefing + leading indicators loader. | 4A-alpha.5 |
| `dcf/` | DCF scenarios, methodology configs, `ValuationEngine` dispatcher, P1 3-stage / 2-stage / multiple-exit / transaction-precedent engines. | 4A-alpha |
| `forecast/` | Three-statement forecast orchestrator + fixed-point solver + `forward_wacc` / `forward_ratios` + persistence. | 4A-beta, 4A-beta.1 |
| `valuation_methodologies/ddm/` | Dividend Discount Model engine. | 4B |
| `valuation_methodologies/residual_income/` | Residual Income engine. | 4B |
| `cross_check/` | FMP + yfinance validation gate. | 4A-alpha.7 (period-aware) |
| `schemas/scenario_bucket.py` | `ScenarioBucket` enum + name inference. | 4A-alpha.8 |
| `validation/` | Cross-yaml reference validation (`expand_scenario_relevance`, `validate_scenario_cross_reference`). | 4A-alpha.8 |

---

## Methodology dispatch

`ValuationEngine._dispatch` routes each `Scenario` by `methodology.type`. Every engine produces something that fits `DCFValuation` so the aggregation pipeline (probability weighting, P25/P75, warnings list) is methodology-agnostic.

| `methodology.type` | Engine | Typical profile | Sprint | Notes |
|---|---|---|---|---|
| `DCF_3_STAGE` | `P1DCFEngine` (3-stage) | P1 | 4A-alpha | Explicit + fade + Gordon / terminal-multiple. |
| `DCF_2_STAGE` | `P1DCFEngine` (`fade_years=0`) | P1 | 4A-alpha | |
| `MULTIPLE_EXIT` | `MultipleExitEngine` | P1 / P2 | 4A-alpha.2 | Terminal EV = metric × multiple. |
| `TRANSACTION_PRECEDENT` | `TransactionPrecedentEngine` | P1 | 4A-alpha.2 | M&A comparable + control premium. |
| `DDM` | `DDMEngine` | P2 insurance, P3 utilities, P5 holdings | 4B | Consumes forecast `CF.dividends_paid`. |
| `RESIDUAL_INCOME` | `RIEngine` | P5 banks | 4B | EV = BookValue + Σ PV(RI). |
| `FFO_BASED` | — | P6 REITs | 4C (planned) | Raises `NotImplementedError`. |
| `NORMALIZED_DCF` | — | P4 cyclicals | 4C (planned) | Raises. |
| `THROUGH_CYCLE_DCF` | — | P4 | 4C (planned) | Raises. |
| `ASSET_BASED` | — | Special (sum-of-parts) | 4D (planned) | Raises. |

**Lazy forecast run** (Sprint 4B): `DCFOrchestrator.run` only invokes the forecast orchestrator when at least one scenario's methodology needs a three-statement projection (DDM or RESIDUAL_INCOME). DCF-only scenario sets skip the projection cost.

---

## Three-statement forecast as a shared building block

The Sprint 4A-beta projection is **consumed by DCF, DDM, and RI** — no engine rebuilds it. This is why so many downstream decisions (WACC, market price, capital allocation) live in the forecast orchestrator even though they look cross-cutting:

| Consumer | Reads from projection |
|---|---|
| DCF | Revenue, operating margin, NOPAT, capex, D&A, ΔWC → FCFF by year. |
| DDM | `CashFlowYear.dividends_paid` (sign-flipped to positive). |
| Residual Income | `BalanceSheetYear.equity` (beginning + ending) and `IncomeStatementYear.net_income`. |

See [`docs/schemas/forecast_snapshots_schema.md`](./schemas/forecast_snapshots_schema.md) for the output structure.

---

## Iterative solver (forecast/iterative_solver.py)

The three statements are interdependent: CFO depends on ΔWC (BS), debt-delta depends on M&A financing (which depends on cash availability), and the cash balance on the BS must equal prior cash + CFO + CFI + CFF. Pure-Python fixed-point iteration converges in 1–5 steps for well-posed scenarios; no scipy dependency, all arithmetic on `Decimal`.

- Residual metric: absolute relative delta of the summed cash series between successive iterations.
- Tolerance: `1e-4`, max 20 iterations. Non-converged scenarios return last-iteration values plus a warning string — **never** fail the forecast.
- EuroEyes base scenario typically converges in 2 iterations.

---

## Per-scenario forward WACC

`ForwardWACCContext` (Sprint 4A-beta.1) bridges the Sprint-3 `WACCGenerator` output into the forecast's forward ratios:

```
ForwardWACCContext(
    cost_of_equity  = WACCComputation.cost_of_equity.cost_of_equity_final,
    cost_of_debt    = WACCComputation.cost_of_debt.cost_of_debt_aftertax,
    tax_rate        = marginal rate,
    base_wacc       = WACCComputation.wacc,
)
```

Each projected year re-weights equity / debt from the projected BS, so `LEVER_UP` scenarios (debt added mid-horizon) show WACC falling as the tax-shielded CoD enters the weighted average.

---

## Scenario bucket taxonomy (v1.1)

Sprint 4A-alpha.8 introduced `ScenarioBucket = {BASE, BULL, BEAR, TAIL}`. Used by:

- `Scenario.resolved_bucket` — explicit `bucket` field wins; otherwise inferred from `name` prefix (`base*` / `bull*` / `bear*` / `takeover_*` etc.).
- `leading_indicators.yaml::scenario_relevance` — accepts buckets **and** specific names (hybrid). `expand_scenario_relevance` resolves buckets to the matching scenario names at runtime.

See [`docs/schemas/scenarios_schema.md`](./schemas/scenarios_schema.md) for the full inference table and hybrid relevance semantics.

---

## Pipeline stages (Phase 1 + 2)

End-to-end `pte process <ticker>` runs 12 stages (defined in `pipeline/coordinator.py`):

1. `check_ingestion` — verify documents exist.
2. `load_wacc` — parse `wacc_inputs.md` into `WACCInputs`.
3. `load_extraction` — load `raw_extraction.yaml` into `RawExtraction`.
4. `validate_extraction` — strict + warn + completeness validators.
5. `cross_check` — FMP / yfinance comparison (**period-aware** since Sprint 4A-alpha.7 via `fiscal_year` kwarg).
6. `decompose_notes` — Module D sub-item decomposition.
7. `extract_canonical` — Modules A / B / C canonical state build.
8. `persist` — write canonical state.
9. `guardrails` — arithmetic + validation checks.
10. `valuate` — scenario dispatch + aggregation.
11. `persist_valuation` — write valuation snapshot.
12. `compose_ficha` — summary composition.

`valuate` is the Phase 2 hook. Cross-check (`5`) was retrofitted for period-aware behaviour in Sprint 4A-alpha.7 so historical extractions (FY2021, FY2022, ...) validate against provider data for the matching year instead of the latest annual snapshot.

---

## Persistence layout

```
data/
├── forecast_snapshots/<ticker>/<ticker>_<timestamp>.json   # Sprint 4A-beta
├── logs/
│   ├── cross_check/<ticker>_<timestamp>.json               # Sprint 4A-alpha.7
│   └── runs/<ticker>_<timestamp>.jsonl
├── yamls/
│   ├── companies/<ticker>/
│   │   ├── scenarios.yaml                                  # analyst input
│   │   ├── capital_allocation.yaml                         # analyst input
│   │   ├── leading_indicators.yaml                         # analyst input
│   │   ├── valuation_profile.yaml                          # P1–P6 marker
│   │   ├── peers.yaml / revenue_geography.yaml             # Sprint 3
│   │   ├── extraction/<ticker>_<period>_<timestamp>.yaml   # canonical state (versioned)
│   │   └── valuation/<ticker>_<timestamp>.yaml             # valuation snapshot
│   └── library/                                            # shared reference data
└── documents/<ticker>/wacc_inputs/wacc_inputs.md            # Phase 1 analyst input
```

Canonical states are stored under `data/yamls/companies/<ticker>/extraction/`; frontends should pick the most recent version whose primary period matches `scenarios.yaml::base_year` (matching the logic the forecast orchestrator uses).

---

## Sprint chronology

| Sprint | Delivery |
|---|---|
| 1 | Raw extraction schemas, ingestion. |
| 2A | Historical normalisation, canonical state. |
| 2B | DuPont, trends, restatements. |
| 3 | `WACCGenerator` + peers. |
| 4A | DCF profiles (P1), methodology taxonomy. |
| 4A-alpha.2 | Per-scenario methodology config + dispatcher. |
| 4A-alpha.3 | Terminal-multiple method. |
| 4A-alpha.4 | Reverse DCF. |
| 4A-alpha.5 | Analytical briefing + cost structure + leading indicators. |
| 4A-alpha.6 | CF validator dual-convention support. |
| 4A-beta | Three-statement forecast engine (IS / BS / CF / solver). |
| 4A-beta.1 | WACC + market-price integration into forecast. |
| 4B | DDM + Residual Income engines. |
| 4A-alpha.7 | Cross-check period-aware fix. |
| 4A-alpha.8 | Schema v1.1 (scenario buckets + hybrid relevance). |
| 4A-alpha.9 | Override aliases + documentation suite **(this sprint)**. |

---

## Integration points for Frontend Sprint 1

### Expected API contracts

```
GET /api/tickers/{ticker}/ficha       → latest markdown ficha
GET /api/tickers/{ticker}/forecast    → latest forecast snapshot JSON
GET /api/tickers/{ticker}/valuation   → latest valuation snapshot YAML-as-JSON
GET /api/tickers/{ticker}/canonical   → latest canonical state JSON
```

Each endpoint selects the **latest timestamp** in the relevant directory. When the directory is empty, return 404 with an actionable hint (`Run pte forecast <ticker> to populate.`).

### Pre-computed fields (do not recompute client-side)

- `expected_value_per_share` (E[V]), P25 / P75 — written to valuation snapshot.
- Probability-weighted Y1 EPS / PER — written to forecast snapshot.
- Per-year WACC, forward ratios — written to forecast snapshot.

### Presentation notes

- Decimal values serialise as **strings**; parse with a Decimal-aware library on the front end.
- `cash_flow.*_paid` / `*_executed` / `capex` / `ma_deployment` are **negative** by convention (outflows). UI may flip sign for user display but round-trip should preserve.
- `solver_convergence.converged: false` must be surfaced (scenario still returned, but non-ideal).
- Methodology mix (DCF vs DDM vs RI across scenarios) is visible in each scenario's `methodology_used` — frontends can colour-code by engine.

---

## Testing strategy

- Unit tests per module (`tests/unit/`), naming convention `test_P<phase>_S<sprint>_<section>_<NN>`.
- Integration tests (`tests/integration/`) exercise the full pipeline against EuroEyes fixtures.
- CLI smoke tests via rich-text output parsing.
- Current test count (v0.9.5): **1461 tests**, zero known regressions.

---

## Known deferred work

- Sprint 4B.2 — scenario-specific capital allocation tilts (`_scenario_adjusted_capital_allocation` placeholder).
- Sprint 4C — FFO_BASED (REITs), NORMALIZED_DCF, THROUGH_CYCLE_DCF (cyclicals).
- Sprint 4D — ASSET_BASED / sum-of-parts.
- Frontend Sprint 1 — FastAPI service layer + Next.js ticker detail page.
- Frontend Sprint 2 — portfolio view.

See [`roadmap/`](./roadmap/) for the detailed backlog.
