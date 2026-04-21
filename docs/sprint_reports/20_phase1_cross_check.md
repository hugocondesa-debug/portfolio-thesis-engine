# Phase 1 · Sprint 5 — Cross-Check Gate

**Date:** 2026-04-21
**Phase 1 Step (Parte K):** 5 — Cross-check gate
**Status:** ✅ Complete

---

## What was done

Built the pipeline's first correctness guardrail. Validates extracted
values against FMP `/stable/` and yfinance, blocks the pipeline on
FAIL, and persists a JSON log per run:

- **`cross_check/__init__.py`** — public surface:
  `CrossCheckGate`, `CrossCheckReport`, `CrossCheckMetric`,
  `CrossCheckStatus`, `load_thresholds`.
- **`cross_check/base.py`** — dataclasses + `CrossCheckStatus` StrEnum
  (`PASS`, `WARN`, `FAIL`, `SOURCES_DISAGREE`, `UNAVAILABLE`).
- **`cross_check/thresholds.py`** — `DEFAULT_THRESHOLDS` (PASS <2%,
  WARN 2–10%, sources_disagree >5%), `DEFAULT_METRIC_THRESHOLDS`
  (operating_income 5/15%, market_cap tighter 2/5%), and
  `load_thresholds(override_json)` that merges `PTE_CROSS_CHECK_THRESHOLDS_JSON`
  on top of defaults. Invalid JSON silently falls back to defaults
  (thresholds are advisory — don't block the pipeline on a typo).
- **`cross_check/gate.py`** — `CrossCheckGate.check(ticker,
  extracted_values, period)` runs two concurrent pairs of provider
  calls (`get_fundamentals` + `get_key_metrics` on FMP and yfinance,
  4 calls via `asyncio.gather(... return_exceptions=True)`),
  extracts the 10 canonical metrics via a dispatch table, computes
  `max_delta_pct` per metric, checks source agreement, assigns status
  per thresholds, rolls up `overall_status`, sets `blocking` on FAIL,
  and persists a JSON report. Provider errors are captured on the
  report — one flaky source doesn't tear down the whole check.
- **`cli/cross_check_cmd.py`** — `pte cross-check <ticker> [--period …]
  [--values-json …] [--override-thresholds …]`. Rich table per metric;
  exit 0 (pass/warn) / 1 (block).
- **Settings.cross_check_thresholds_json** added for the env-var
  override path.
- **29 unit tests** across two files plus 1 gated integration test:
  - 9 tests on `thresholds.py` (defaults, override merge, invalid
    JSON fallback, per-metric shadowing).
  - 14 tests on `gate.py` (happy path, WARN tier, FAIL blocks,
    SOURCES_DISAGREE elevation, UNAVAILABLE neutrality in both
    directions, metric-specific thresholds, env-var override,
    report persistence, log-dir failure is non-fatal, parallel
    fetch count, single-provider outage captured, both-providers-down
    yields all-unavailable, zero-extracted handled without ZeroDivisionError).
  - 6 CLI tests (happy path, FAIL exits 1, invalid JSON errors,
    non-numeric value errors, --override-thresholds accepted, --help
    lists flags).
  - 1 integration test `test_1846_hk_cross_check_runs_end_to_end`
    gated by `PTE_SMOKE_HIT_REAL_APIS=true`.

Plus a minor extension to **`yfinance_provider.get_key_metrics`**:
now surfaces `sharesOutstanding` + `marketCap` so the gate can
cross-check both metrics from both sources. Updated its test.

## Decisions taken

1. **10 canonical metrics, fixed catalogue.** `revenue`,
   `operating_income`, `net_income`, `total_assets`, `total_equity`,
   `cash`, `operating_cash_flow`, `capex`, `shares_outstanding`,
   `market_cap`. Adding a new metric is one entry in
   `_METRIC_CATALOGUE` mapping `(fmp_bundle, fmp_extractor, yf_bundle,
   yf_extractor)`. Tests guard that this set is exactly what's
   produced — regressions surface immediately.
2. **`SOURCES_DISAGREE` only upgrades WARN, not FAIL.** A metric that
   would be FAIL with either source stays FAIL; a WARN-tier drift
   that's also accompanied by the two sources themselves
   disagreeing by >5% gets promoted to `SOURCES_DISAGREE`. Precedence
   for `overall_status` is `FAIL > SOURCES_DISAGREE > WARN > PASS`.
3. **`UNAVAILABLE` is neutral in overall roll-up.** The overall status
   computes the worst of the *non-UNAVAILABLE* statuses. A metric
   neither source publishes shouldn't penalise extraction. Tests
   pin this both ways — provider outage and extractor not supplying
   a metric.
4. **Provider-level errors are captured, not raised.** Uses
   `asyncio.gather(... return_exceptions=True)` so a 404 from FMP on
   a ticker it doesn't cover doesn't crash the gate. Those errors
   land in `report.provider_errors` keyed by bundle name
   (`fmp.fundamentals`, `fmp.key_metrics`, `yf.fundamentals`,
   `yf.key_metrics`) and the affected bundles become empty dicts.
5. **Log directory failure is non-fatal.** If the log dir can't be
   created (e.g., a file at the target path), `log_path` is `None`
   but the gate still returns the report. Operators never lose a
   check result because of a stale filesystem.
6. **Thresholds.py uses `TypedDict`** rather than a dataclass or
   Pydantic model. The shape is small (PASS / WARN / sources_disagree)
   and JSON-friendly, and `TypedDict` supports partial dicts natively.
   Three targeted `type: ignore` comments handle the
   `dict()[TypedDict]` pattern mypy can't currently round-trip.
7. **Metric-specific thresholds shadow defaults key-by-key.**
   `thresholds_for("operating_income", ...)` returns `{PASS: 0.05,
   WARN: 0.15}` (override wins for both keys); for a metric without
   an override, returns the defaults dict unchanged.
8. **Zero-extracted-value handling.** Division uses `scale = max(abs(extracted),
   Decimal("1"))` so a reported zero (e.g., no capex that year) doesn't
   ZeroDivisionError. Edge-case test pins this behaviour.
9. **Log filename normalises the ticker** (`TEST.L` → `TEST-L_…`) so
   filesystems that dislike dots in directory names stay happy. Uses
   the same normalisation pattern as the YAML repositories from Phase 0.
10. **Gate is stateless + single-instance.** One gate can cross-check
    many tickers; no per-ticker configuration is carried. Tests build
    one gate and invoke `check(...)` multiple times.

## Spec auto-corrections

1. **Spec Part D.5 sketched fetching only `get_fundamentals`.** The
   10-metric list in D.3 includes `shares_outstanding` and
   `market_cap` which come from `key_metrics`, not fundamentals.
   Extended the fetch to 4 calls (`get_fundamentals` +
   `get_key_metrics` × 2 providers) so every metric can be
   cross-checked without further round-trips.
2. **Spec mentioned `shares_outstanding` as an FMP metric.** yfinance
   surfaces it through `Ticker.info["sharesOutstanding"]` but our
   Phase 0 provider didn't expose it. Extended `get_key_metrics` by
   two lines (marketCap + sharesOutstanding); updated the existing
   yfinance tests.
3. **Spec didn't define the `SOURCES_DISAGREE` precedence.** Decision
   documented in decision 2 above — WARN-tier drift + >5% between
   sources → SOURCES_DISAGREE; FAIL survives the promotion. Tests
   exercise both paths.
4. **Spec didn't specify UNAVAILABLE semantics for overall roll-up.**
   Chose neutrality per decision 3. Tests pin both "outage" and
   "extractor didn't supply" paths.

## Files created / modified

```
A  src/portfolio_thesis_engine/cross_check/__init__.py
A  src/portfolio_thesis_engine/cross_check/base.py
A  src/portfolio_thesis_engine/cross_check/thresholds.py
A  src/portfolio_thesis_engine/cross_check/gate.py
A  src/portfolio_thesis_engine/cli/cross_check_cmd.py
M  src/portfolio_thesis_engine/cli/app.py                     (+cross-check)
M  src/portfolio_thesis_engine/shared/config.py               (+cross_check_thresholds_json)
M  src/portfolio_thesis_engine/market_data/yfinance_provider.py
                                                              (+sharesOutstanding, +marketCap
                                                               in key_metrics record)
A  tests/unit/test_cross_check_gate.py                        (23 tests)
A  tests/unit/test_cli_cross_check.py                         (6 tests)
M  tests/unit/test_yfinance_provider.py                       (+1 test for new fields)
A  tests/integration/test_cross_check_real.py                 (1 gated test)
A  docs/sprint_reports/20_phase1_cross_check.md               (this file)
```

## Verification

```bash
$ uv run pytest
# 522 passed, 5 skipped in 12.75s

$ uv run ruff check src tests
# All checks passed!

$ uv run mypy src
# Success: no issues found in 65 source files
```

Smoke transcript (synthetic extracted values, mocked providers):

```
revenue                    PASS  Δ=0.34%
operating_income           PASS  Δ=1.82%
net_income                 PASS  Δ=1.33%
total_assets               PASS  Δ=0.16%
total_equity               PASS  Δ=0.26%
cash                       PASS  Δ=0.22%
operating_cash_flow        PASS  Δ=0.74%
capex                      PASS  Δ=1.33%
shares_outstanding         PASS  Δ=0.50%
market_cap                 PASS  Δ=0.80%

overall = PASS  blocking = False
```

## Tests passing / failing + coverage

All 522 unit tests pass; 5 integration tests skipped (gated across
Phase 0 + this new one).

| Sprint 5 module                           | Stmts | Miss | Cover |
| ----------------------------------------- | ----- | ---- | ----- |
| `cross_check/__init__.py`                 |   4   |  0   | 100 % |
| `cross_check/base.py`                     |  29   |  0   | 100 % |
| `cross_check/thresholds.py`               |  39   |  1   |  97 % |
| `cross_check/gate.py`                     | 121   |  5   |  96 % |
| `cli/cross_check_cmd.py`                  |  55   |  4   |  93 % |
| **Sprint 5 subtotal**                     | 248   | 10   | **96 %** |

Comfortably above the ≥90 % target for this correctness-critical
module. Uncovered lines are defensive arms (log-write OSError, a
`typer.BadParameter` path when `values_json` is not a dict, the
`asyncio.run` entry inside the CLI that tests invoke via CliRunner).

## Cost estimate

LLM cost this sprint: **$0** (no LLM calls in the gate — only FMP +
yfinance which are already paid subscription / free). Integration
test under `PTE_SMOKE_HIT_REAL_APIS=true` adds zero incremental cost
per Hugo's brief (FMP is flat-fee, yfinance free).

## Problems encountered

1. **yfinance provider didn't expose `sharesOutstanding` or `marketCap`**
   on its key-metrics record. Two-line extension; added a dedicated
   test to guard against regression.
2. **`TypedDict` + `dict()` roundtrip** trips mypy's strict inference —
   needed three targeted `type: ignore[assignment|misc]` comments
   explaining the cast. Alternative was a full `Protocol`/dataclass
   approach which felt heavier for three keys.
3. **`asyncio.gather(..., return_exceptions=True)` mypy union return
   type** — the results are `dict | BaseException`; guarded with
   `isinstance` before assigning. Reads cleanly in the updated code.
4. **Log file path on a ticker with a dot** — first attempt used
   `report.ticker` as-is, which would make Windows nervous. Applied
   the same ticker normalisation pattern as storage (`.` → `-`).

## Next step

**Sprint 6 — Extraction Modules A + B** (Hugo's next batch):
`extraction/base.py`, `coordinator.py`, `module_a_taxes.py`,
`module_b_provisions.py`. Consumes `ExtractionResult.sections` from
Sprint 4 and applies the reclassification methodology (A core: A.1
statutory→effective→cash, A.2.0 materiality, A.2.1-A.2.5 tax table
recon; B minimal: B.0-B.2 operating vs non-operating). Tests with
synthetic section fixtures + a mocked LLM for the tax-recon parse.
