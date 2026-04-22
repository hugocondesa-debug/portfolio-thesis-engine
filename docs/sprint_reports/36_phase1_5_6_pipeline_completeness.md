# Phase 1.5.6 — Pipeline completeness + module extraction fixes

**Date:** 2026-04-22
**Scope:** 8 independent fixes revealed by the first real EuroEyes
pipeline run. Modules consume the as-reported schema correctly at
the structural layer; business-level extraction (rates, D&A,
metadata) needed the same treatment.

## Before / after on the real EuroEyes FY2024 run

| Metric                               | Before (1.5.5)     | After (1.5.6)                     |
| ------------------------------------ | ------------------ | --------------------------------- |
| Identity.name                        | "1846.HK"          | "EuroEyes International Eye Clinic Limited" |
| Identity.exchange                    | "—"                | "HKEX"                            |
| Identity.country_domicile            | "XX"               | "HK"                              |
| Methodology.total_api_cost_usd       | 0.720747 (stale)   | 0 (run-local)                     |
| Effective tax rate                   | 30% (statutory)    | 33.30% (IS arithmetic)            |
| EBITDA (HKD)                         | 115.8M = OI        | 228.0M = OI + D&A                 |
| EBITDA margin                        | 16.18% (= OI margin) | 31.86%                          |
| Net Debt / EBITDA                    | broken denominator | -1.47x                            |
| A.1.IS_CHECKSUM                      | FAIL (stale algo)  | PASS (walking subtotals)          |
| V.1.CROSSCHECK_NET_INCOME            | false-positive WARN (group vs parent) | uses parent NI |
| Pipeline stages completed            | 8/11 (SKIP 9-11)   | 11/11                             |
| Ficha viewable via `pte show`        | no                 | yes                               |

## Changes by issue

### Issue 1 — Module A effective tax rate from IS arithmetic

File: `src/portfolio_thesis_engine/extraction/module_a_taxes.py`

Priority order:

1. **IS arithmetic** — `|income_tax| / profit_before_tax` (deterministic,
   always available when IS has both fields).
2. **Tax-note "Effective rate" row** — parseable recon table.
3. **Statutory rate from WACCInputs** — loud fallback.

For EuroEyes: 42,107 / 126,466 = 33.30% (was using WACC statutory 30%).

### Issue 2 — AnalysisDeriver D&A from notes

File: `src/portfolio_thesis_engine/extraction/analysis.py`

New helper `_sum_da_from_notes(raw)` walks notes whose title matches
PP&E or Intangibles, within each finds current-year rollforward tables
(by year in `table_label`), and sums the "Depreciation charge" /
"Amortisation charge" row totals (last Decimal cell = "Total" column
of multi-asset rollforward).

For EuroEyes: 107,355 (PP&E) + 4,859 (intangibles) = 112,214k →
EBITDA = Op Income 115.8M + D&A 112.2M = 228.0M.

Cascades into correct EBITDA margin (31.86%) and Net Debt / EBITDA
(-1.47x).

### Issue 3 — Net Debt / EBITDA — cascade fix only

No direct change. Correct denominator once Issue 2 lands.

### Issue 4 — Identity metadata from raw_extraction

File: `src/portfolio_thesis_engine/pipeline/coordinator.py`

- `metadata.company_name` → `identity.name` (was ticker fallback).
- Ticker suffix → exchange / country domicile via
  `_TICKER_SUFFIX_EXCHANGE` mapping (`.HK → (HKEX, HK)`,
  `.L → (LSE, GB)`, `.DE → (XETRA, DE)`, +17 more).
- ISIN scavenged from `extraction_notes` free text via regex
  `\bISIN[:\s]+([A-Z]{2}[A-Z0-9]{9}\d)\b`.
- SQLite row wins when populated; suffix-derived is the fallback.

### Issue 5 — Methodology cost = session-local, not cumulative

File: `src/portfolio_thesis_engine/extraction/coordinator.py`

Switched from `CostTracker.ticker_total()` (reads the full JSONL log,
including legacy Phase 1 experiments) to summing
`CostTracker.session_entries()` filtered by ticker. Phase 1.5+
pipelines are LLM-free, so the session-local total is typically 0.

### Issue 6 — Guardrail A.1.IS_CHECKSUM uses raw extraction

Files: `src/portfolio_thesis_engine/guardrails/checks/arithmetic.py`,
`src/portfolio_thesis_engine/pipeline/coordinator.py`

- Pipeline now passes `raw_extraction` into the guardrail context.
- `ISChecksum.check()` rewritten: walks the IS `line_items` from the
  start, sums every non-subtotal leaf, stops at the first PFY-style
  subtotal (matching `/profit for the (year|period)|net (income|
  profit|earnings)/`). Compares Σ leaves vs PFY with 0.1% PASS /
  0.5% FAIL thresholds.
- Respects `is_subtotal` and stops walking at OCI header (OCI items
  don't belong in the PnL checksum).
- Nested subtotals (e.g. "Finance income/(expenses), net") no longer
  double-count — they're subtotals and the walker skips them.

For EuroEyes: Σ leaves = 84,359k = PFY → PASS.

### Issue 7 — Cross-check uses parent NI

File: `src/portfolio_thesis_engine/pipeline/coordinator.py`

`_extract_cross_check_values` prefers
`income_statement.profit_attribution.parent` over the group-NI
subtotal when the extraction populates it. Matches FMP's `netIncome`
semantics (which is parent-attributable).

For EuroEyes: 82,285 (parent) vs FMP 82,285 → PASS 0.00 %. Was WARN
at 2.46 % because we compared group NI (84,359) vs FMP parent
(82,285).

### Issue 8 — Pipeline wire-up for stages 9-11

File: `src/portfolio_thesis_engine/cli/process_cmd.py`

`_build_coordinator` now wires:

- `valuation_composer=ValuationComposer()`
- `scenario_composer=ScenarioComposer(dcf_engine=FCFFDCFEngine(n_years=5))`
- `valuation_repo=ValuationRepository()`
- `market_data_provider=fmp`
- `ficha_composer=FichaComposer()`
- `company_repo=CompanyRepository()`

All 11 stages now complete end-to-end. `pte show 1846.HK` renders
the ficha.

## Tests

**+10 new + 5 rewritten:**

- `TestModuleAFallbacks` rewritten:
  - `test_no_taxes_note_uses_is_computed_rate` — IS has tax + PBT → compute 20%, not statutory 25%.
  - `test_missing_effective_rate_in_note_uses_is` — same path when note lacks rate row.
  - `test_missing_income_tax_line_falls_back` — both sources missing → statutory.
  - `test_no_tax_note_no_is_tax_falls_back` — same.
- `TestISChecksum` rewritten to pass `raw_extraction` in context:
  - `test_exact_match_passes`, `test_small_drift_warns`, `test_big_drift_fails`,
    `test_no_ni_line_skips`, `test_empty_state_skips`.
  - `test_nested_subtotal_not_double_counted` — new regression for
    "X, net" pattern.
- `TestGuardrailFailure.test_guardrail_fail_marks_outcome_unsuccessful`
  refactored: injects an always-FAIL `Guardrail` via monkeypatch on
  `default_guardrails`. The old canonical-state-based approach can't
  trigger failures any more because Phase 1.5.6 guardrails read from
  `raw_extraction` (which strict validation gates).

## Validation

- **Tests:** 793 passed (+10), 6 skipped, 93 % coverage.
- **Ruff + mypy --strict:** clean.
- **Real EuroEyes pipeline:** 11/11 stages complete. Overall guardrail
  status WARN (real WACC + cross-check discrepancies, not arithmetic
  bugs). Ficha saved and viewable via `pte show 1846.HK`.
