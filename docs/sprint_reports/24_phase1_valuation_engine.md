# Phase 1 · Sprint 9 — Valuation engine (Parte F)

**Date:** 2026-04-21
**Phase 1 Step (Parte F):** 9 — DCF / equity bridge / IRR / composer + pipeline integration
**Status:** ✅ Complete

---

## What was done

Sprint 9 delivers the full Phase 1 valuation engine and wires it into
the end-to-end pipeline. `pte process <ticker>` now produces **both** a
`CanonicalCompanyState` and a `ValuationSnapshot` in a single run.

47 new unit tests + the existing integration smoke extended to cover
valuation; total suite at **681 passing**.

### EBITA → EBITDA patch (pre-Sprint-9, commit `f8b6db9`)

Spotted before Sprint 9 started: `NOPATBridge.ebita` was computing
EBITDA (operating income + |D&A total|) because the P1 IS parser
aggregates depreciation + amortisation under the ``d_and_a`` category.
Renamed the field to its accurate label and added an optional
``ebita: Money | None = None`` for Phase 2, when the parser will split
D from A. Operating taxes + NOPAT anchor off EBITA when populated,
otherwise off EBITDA. Seven files touched; 634 → 634 tests stayed
green after the migration.

### Sprint 9 — Valuation engine

- **`valuation/base.py`** — `ValuationEngine` ABC plus frozen-dataclass
  result objects: `DCFResult`, `EquityValue`, `IRRResult`. Sibling
  modules import these instead of each other so there's no cycle.
- **`valuation/dcf.py`** — `FCFFDCFEngine`:
  - `project_fcff` walks the N-year explicit period, growing revenue
    at `revenue_cagr`, linearly interpolating margin to
    `terminal_operating_margin`, holding CapEx / D&A ratios constant
    at base-year, ΔWC = 0 for Phase 1.
  - `compute_terminal` Gordon growth with explicit ``WACC > g`` check.
  - `compute_ev` mid-year discounting (year-i exponent = i−0.5; TV
    exponent = N).
  - Base-year inputs pulled off `CanonicalCompanyState` — revenue,
    operating margin, CapEx/revenue, D&A/revenue (back-solved from
    `NOPATBridge.ebitda − operating_income`), operating tax rate from
    Module A.1.
- **`valuation/equity_bridge.py`** — `EquityBridge.compute(dcf, state,
  preferred_equity=None)`. Subtracts net debt (`financial_liabilities −
  financial_assets`, read from IC), preferred equity (caller-supplied,
  zero in Phase 1), NCI. **Leases stay in EV** per the Sprint 7
  FCFF economic-view convention (doc pinned in the module's docstring
  and tested directly).
- **`valuation/irr.py`** — `IRRDecomposer.decompose(target, current,
  scenario, state, horizon_years=3)`. Total IRR from the
  ``(target/current)^(1/horizon) − 1`` formula; fundamental derived
  from `scenario.revenue_cagr`; re-rating solved algebraically so the
  three components sum to the total. Dividend yield stays at zero for
  Phase 1 (Phase 2 wires it from `capital_allocation`). Negative
  targets (deep bear) → total IRR = −100 % instead of crashing on
  complex-root math.
- **`valuation/scenarios.py`** — `ScenarioComposer.compose(wacc_inputs,
  canonical_state)`. Iterates in `bear → base → bull` order, skipping
  labels the WACC file doesn't supply, and for each one runs DCF +
  equity bridge + IRR. Per-scenario `wacc_override` honoured when set.
  Clips `Percentage` fields at `[−100, 1000]` before instantiating
  `Scenario` so deep-bear schemas don't reject.
- **`valuation/composer.py`** — `ValuationComposer.compose(state,
  scenarios, market)` builds the final `ValuationSnapshot`:
  probability-weighted `expected_value`, `fair_value_range_low/high`,
  `upside_pct` vs current market price, `asymmetry_ratio` clipped at
  999 when entire range is upside. Phase 1 stubs for `conviction`
  (all-MEDIUM) and `guardrails` (empty PASS).

### Pipeline integration

Added two stages to `PipelineCoordinator`:

- **`VALUATE`** — fetches a `MarketSnapshot` from the market-data
  provider (falling back to WACC-file price on provider failure), runs
  `ScenarioComposer` + `ValuationComposer`.
- **`PERSIST_VALUATION`** — `ValuationRepository.save`.

Both stages SKIP (not fail) when the valuation wiring isn't injected,
so pre-Sprint-9 tests still pass. `process()` now runs 9 stages total
(7 Sprint-8 + 2 valuation).

## Tests shipped

- **`test_valuation_dcf.py`** (11): projection (revenue CAGR, margin
  interpolation, full N-year run), A.1 tax rate threading, terminal
  Gordon value, WACC ≤ g validation, mid-year discount math with
  hand-calculated expected numbers, compute_target integration,
  config validation (n_years ∈ [1, 25], describe()).
- **`test_valuation_equity_bridge.py`** (9): EV → Equity with net
  debt, preferred, NCI, shares-outstanding / zero-shares paths, leases
  stay in EV, missing IC graceful.
- **`test_valuation_irr.py`** (9): total IRR from hand-calculated
  case, components sum to total, fundamental = revenue CAGR, zero
  current price raises, deep bear (negative upside) yields negative
  IRR, no CAGR → fundamental zero.
- **`test_valuation_scenarios.py`** (8): three scenarios composed in
  `bear → base → bull` order, each carries drivers + targets + IRR,
  probabilities preserved, bull > bear on target, single-scenario
  compose, `wacc_override` consumed.
- **`test_valuation_composer.py`** (10): probability-weighted E[V]
  math, fair value range, upside, asymmetry (normal + clamped), IRR
  weighting, YAML round-trip.
- **`test_phase1_pipeline_e2e.py`** extended: now wires the valuation
  services and asserts the 9-stage run, 3-scenario snapshot, snapshot
  persistence via `ValuationRepository`.

## Decisions taken

1. **EBITDA/EBITA rename as a pre-sprint patch.** Two separate commits
   so the schema change is reviewable independently of the valuation
   additions. The schema change is mechanically small but semantically
   load-bearing — it sits in its own `f8b6db9` for blame clarity.
2. **Mid-year discounting is the default** per the spec. Decimal
   doesn't natively support non-integer exponents, so we round-trip
   through float for discount factors. Precision loss is at the
   10⁻¹⁵ level — irrelevant for DCF use, verified by the hand-
   calculated test cases.
3. **EBITDA-based NOPAT proxy.** True NOPAT = EBIT × (1 − tax_rate),
   but we don't have EBIT separately (operating income is already
   EBIT when D&A is broken out; the Phase 1 parser aggregates D&A
   inside operating expenses in some layouts). We use EBITDA × (1 − t)
   as a cash-flow proxy and let the CapEx line in reinvestment handle
   the capex/depreciation dynamics. Phase 2 with split D/A will
   revert to proper EBIT-based NOPAT.
4. **Linear margin interpolation** from base to terminal across N
   years. Alternative would be user-supplied per-year curves; Phase 1
   scope says "scenario with three drivers", linear is the simplest
   compliant option.
5. **ΔWC = 0 for Phase 1.** Spec F.4 sketches "WC change: % of revenue
   change"; Phase 1 keeps it zero because the IS-line schema doesn't
   carry `category` info and DSO/DPO/DIO aren't populated by default
   in `KeyRatios`. Decision flagged in the DCF docstring.
6. **Leases stay in EV, not subtracted.** Sprint 7 decision 8 already
   documented this: Module C.3 counts lease additions as investment in
   the FCFF economic view, so the bridge must not double-count them
   by subtracting lease liabilities. Tests pin the rule directly.
7. **Re-rating is the residual in IRR decomposition.** Three
   components, one equation; fundamental comes straight from the
   scenario CAGR, dividend is zero, re-rating absorbs everything else.
   Cleaner than deriving two independently and accepting the sum won't
   match.
8. **Deep-bear negative-target handling.** When the DCF + equity
   bridge produces a per-share below zero (can happen when the bear
   scenario's Gordon TV is very low vs net debt), IRR decomposition
   sets `total_p_a = −1` (100 % wipeout) instead of crashing on
   `(negative) ** (1/n)`. Composer clips all `Percentage` fields at
   the schema bounds [−100, 1000]. Phase 2 guardrails will flag these
   states, but the engine shouldn't crash.
9. **Valuation stages SKIP when wiring is absent.** The coordinator
   accepts `valuation_composer`, `scenario_composer`, `valuation_repo`
   and `market_data_provider` as optional kwargs. When any is missing,
   both valuation stages record SKIP instead of failing. Sprint 8
   tests that don't wire valuation services still pass.
10. **Market snapshot falls back to WACC-file price** on provider
    failure. The WACC manual already has `current_price` (the analyst's
    source of truth for the valuation date); it's reasonable to lean
    on that when FMP hiccups rather than fail the whole run.

## Spec auto-corrections

1. **Spec F.4 used "Year 1 discount exponent: 0.5"** — implemented as
   year-i exponent = `i − 0.5` (same thing, indexed from 1). Clear
   from the hand-calculated test cases.
2. **Spec F.5 `ScenarioInputs`** is the spec's sketch for a helper;
   Phase 1 reuses `WACCInputs.ScenarioDriversManual` directly because
   it already has all four fields the spec wanted (probability,
   revenue_cagr, terminal_growth, terminal_operating_margin,
   wacc_override). One fewer indirection.
3. **Spec F.7 IRR decomposition** sketched three components:
   fundamental + dividend + re-rating. Phase 1 drops dividend to zero
   and keeps the other two; re-rating is the residual. Dividend wires
   up in Phase 2.
4. **Spec F.8 composer** mentioned `scenario_response` and
   `reverse_analysis`; Phase 1 leaves both at `None`. Reverse DCF is
   explicitly out-of-scope (Phase 2).
5. **Spec didn't define behaviour for negative per-share targets.**
   Decision 8 above.

## Files created / modified

```
M  src/portfolio_thesis_engine/schemas/company.py             (NOPATBridge: +ebitda, ebita optional)
M  src/portfolio_thesis_engine/extraction/analysis.py         (EBITDA/EBITA split, anchor tax base)
A  src/portfolio_thesis_engine/valuation/__init__.py
A  src/portfolio_thesis_engine/valuation/base.py
A  src/portfolio_thesis_engine/valuation/dcf.py
A  src/portfolio_thesis_engine/valuation/equity_bridge.py
A  src/portfolio_thesis_engine/valuation/irr.py
A  src/portfolio_thesis_engine/valuation/scenarios.py
A  src/portfolio_thesis_engine/valuation/composer.py
M  src/portfolio_thesis_engine/pipeline/coordinator.py        (+VALUATE, +PERSIST_VALUATION stages)
M  tests/conftest.py                                          (NOPATBridge fixture update)
M  tests/unit/test_analysis_deriver.py                        (EBITDA assertions)
M  tests/unit/test_extraction_end_to_end.py                   (EBITDA assertions)
M  tests/unit/test_guardrails_arithmetic.py                   (NOPATBridge fixture update)
M  tests/unit/test_pipeline_coordinator.py                    (9-stage assertions)
A  tests/unit/test_valuation_dcf.py                           (11 tests)
A  tests/unit/test_valuation_equity_bridge.py                 (9 tests)
A  tests/unit/test_valuation_irr.py                           (9 tests)
A  tests/unit/test_valuation_scenarios.py                     (8 tests)
A  tests/unit/test_valuation_composer.py                      (10 tests)
M  tests/integration/test_phase1_pipeline_e2e.py              (valuation assertions)
A  docs/sprint_reports/24_phase1_valuation_engine.md          (this file)
```

## Verification

```bash
$ uv run pytest
# 681 passed, 5 skipped in 7.24s

$ uv run ruff check src tests
# All checks passed!

$ uv run mypy src
# Success: no issues found in 85 source files
```

E2E smoke transcript (synthetic EuroEyes fixture, 9 stages):

```
stage             status  duration_ms  message
check_ingestion   ok           <10     2 document(s) found
load_wacc         ok           <10     WACC loaded (wacc=8.62%)
section_extract   ok           ~200    11 sections across 1 doc (LLM mocked)
cross_check       ok           <10     overall=PASS blocking=False (10 metrics)
extract_canonical ok            <50    modules=[A,B,C] adjustments=3
persist           ok            <30    canonical_state saved
guardrails        ok            <10    overall=PASS across 8 checks
valuate           ok            <30    E[V]=X range=[L,H] upside=Y% across 3 scenarios
persist_valuation ok            <30    valuation snapshot saved

overall_guardrail_status = PASS
```

## Tests passing / failing + coverage

All 681 unit / in-suite integration tests pass; 5 external-API tests
skipped (gated).

| Sprint 9 module                                       | Stmts | Miss | Cover |
| ----------------------------------------------------- | ----- | ---- | ----- |
| `valuation/__init__.py`                               |   7   |  0   | 100 % |
| `valuation/base.py`                                   |  35   |  0   | 100 % |
| `valuation/dcf.py`                                    | 114   | 11   |  90 % |
| `valuation/equity_bridge.py`                          |  24   |  0   | 100 % |
| `valuation/irr.py`                                    |  28   |  0   | 100 % |
| `valuation/scenarios.py`                              |  63   |  1   |  98 % |
| `valuation/composer.py`                               |  59   |  1   |  98 % |
| **Sprint 9 valuation subtotal**                       | 330   | 13   | **96 %** |
| `pipeline/coordinator.py` (extended)                  | 316   | 21   |  93 % |

Target ≥85 %; delivered 96 % on valuation. Uncovered lines are
defensive arms (DCF base-year with no nopat bridge; lease-only branch
when FMP get_quote fails hard).

## Cost estimate

LLM cost this sprint: **$0** (valuation engine is deterministic; no
LLM calls). The pipeline integration adds one market-data provider
call per run (`get_quote`), already covered under the FMP flat-fee
subscription.

## Problems encountered

1. **`Decimal` non-integer exponents crash on negative bases.** The
   IRR decomposition raised `InvalidOperation` when the bear scenario
   produced a negative per-share target (Gordon TV too low, net debt
   too high in the synthetic state). Fixed by clamping total IRR at
   −100 % for non-positive targets instead of evaluating the root.
2. **`Percentage` schema bounds reject deep-bear IRRs.**
   `fundamental + rerating = −100 %` can mean rerating at −103 % if
   fundamental is +3 %. The composer now clips every `Percentage`
   field at the schema bounds [−100, 1000] before instantiating the
   `Scenario`. Semantics: ≤ −100 % is a wipeout; lower is degenerate.
3. **Sprint-8 tests expected 7 pipeline stages.** The two new
   valuation stages (SKIP by default) bumped the count to 9. Updated
   `test_pipeline_coordinator.py` and the e2e integration to expect
   9 stages. No behavioural change for callers who don't wire
   valuation services.
4. **`EBITDA/EBITA` naming caught in code review.** Spotted by Hugo
   that the Sprint 7 `AnalysisDeriver` was computing EBITDA but
   calling it EBITA. Shipped as a separate commit (`f8b6db9`) so the
   schema migration is reviewable in isolation.

## Sprint 9 summary + Phase 1 scope coverage

Phase 1 now has a working DCF-based valuation engine and a full-
pipeline `pte process` that produces both canonical state + valuation
snapshot. 681 tests passing, mypy-strict clean, 96 % coverage on the
Sprint 9 surface.

Remaining Phase 1 work (per the original 10-sprint plan):

- **Sprint 10** — Ficha composer + Streamlit UI + `pte valuate` /
  `pte ficha` / `pte ui` CLI commands. **Hugo's AR + Interim + WACC
  smoke with the real EuroEyes markdown scheduled here.**

## Next step

Sprint 10 — Ficha composer + Streamlit UI + real EuroEyes smoke.
Hugo's call on scope + timing.
