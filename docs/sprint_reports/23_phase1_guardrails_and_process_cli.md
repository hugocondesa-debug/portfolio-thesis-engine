# Phase 1 · Sprint 8 — Guardrails A+V core + `pte process` CLI

**Date:** 2026-04-21
**Phase 1 Step (Parte L + I):** 8 — Guardrails core + pipeline orchestration
**Status:** ✅ Complete

---

## What was done

Adds the first correctness guardrails on top of the canonical-state
output and wires the full end-to-end pipeline under a single
`pte process <ticker>` command. 53 new unit tests + 1 full-pipeline
integration smoke; 634 tests total.

### Guardrails (`src/portfolio_thesis_engine/guardrails/checks/`)

- **`arithmetic.py`** — four Group-A checks on `CanonicalCompanyState`:
  - **`A.1.IS_CHECKSUM`** — Σ atomic IS lines = reported Net Income
    within 0.1 % (PASS) / 0.5 % (FAIL). Subtotal labels (Gross Profit,
    Operating Income, PBT, EBIT/EBITDA) are filtered out of the sum
    so they don't double-count.
  - **`A.1.BS_CHECKSUM`** — Assets = Liabilities + Equity identity
    within 0.01 % / 0.1 %. Reads the BS categories populated by
    `section_extractor/tools.py`'s enum.
  - **`A.1.CF_CHECKSUM`** — CFO + CFI + CFF + FX = Δcash within
    0.5 % / 2 %. SKIPs when no `net_change_in_cash` line is published.
  - **`A.2.IC_CONSISTENCY`** — IC (from balance sheet) matches
    IC implied by NOPAT / ROIC within 0.5 % / 2 %. Non-blocking
    (ratio issue, not reclass issue). SKIPs when ROIC or NOPAT is
    missing / zero.
- **`validation.py`** — four Group-V checks against external sources:
  - **`V.1.CROSSCHECK_REVENUE`**, **`V.1.CROSSCHECK_NET_INCOME`**,
    **`V.1.CROSSCHECK_TOTAL_ASSETS`** — pass-through of each metric's
    verdict in `CrossCheckReport`. PASS/WARN/FAIL mapped 1:1;
    SOURCES_DISAGREE → WARN; UNAVAILABLE → SKIP. All blocking.
  - **`V.2.WACC_CONSISTENCY`** — recomputes WACC from the components
    and compares to the headline `wacc` property within 0.1 pp.
    Non-blocking (valuation will surface any downstream drift).
- **`__init__.py`** exposes `default_guardrails()` returning the eight
  checks in run order — the pipeline uses this bundle.

### Pipeline (`src/portfolio_thesis_engine/pipeline/`)

- **`coordinator.py`** — `PipelineCoordinator.process(ticker, *,
  wacc_path, force, skip_cross_check, force_cost_override)` runs seven
  stages in order and returns a :class:`PipelineOutcome`:
  1. **CHECK_INGESTION** — documents exist in `DocumentRepository`.
  2. **LOAD_WACC** — parse `wacc_inputs.md` → `WACCInputs`.
  3. **SECTION_EXTRACT** — run `P1IndustrialExtractor` over every
     non-WACC markdown report and merge sections.
  4. **CROSS_CHECK** — `CrossCheckGate.check`; blocks the pipeline on
     FAIL unless `skip_cross_check=True`.
  5. **EXTRACT_CANONICAL** — `ExtractionCoordinator.extract_canonical`.
  6. **PERSIST** — save via `CompanyStateRepository`.
  7. **GUARDRAILS** — run the eight default checks; aggregate.
- Writes a JSONL run log under `logs/runs/{ticker}_{timestamp}.jsonl`
  with header + per-stage rows + per-guardrail rows.
- `force_cost_override=True` temporarily raises the per-company cost
  cap to USD 10 000 for the duration of the run (restored in a
  `finally` block).

### CLI (`src/portfolio_thesis_engine/cli/process_cmd.py`)

- **`pte process <ticker>`** — wires real services (Anthropic LLM,
  FMP + yfinance providers, document + metadata + state repos) and
  invokes the coordinator. Flags:
  - `--wacc-path PATH` — explicit WACC file (otherwise resolved from
    the document repo).
  - `--force` — bypass cached-stage checks.
  - `--skip-cross-check` — bypass the gate (noisy warning logged).
  - `--force-cost-override` — raise cost cap for this run.
- Rich table of stages + guardrail details + final overall status.
- Exit codes: **0** on PASS / WARN, **1** on cross-check blocked,
  **2** on guardrail FAIL or `PipelineError`.

### Tests

53 new unit tests + 1 integration smoke:

- **`test_guardrails_arithmetic.py`** (21 tests): IS/BS/CF checksum
  PASS/WARN/FAIL tiers, IC consistency PASS/WARN/FAIL, SKIP paths for
  missing inputs (no state, no NI line, all zeros, no ROIC, zero
  NOPAT).
- **`test_guardrails_validation.py`** (13 tests): V.1 status
  mapping for every `CrossCheckStatus` tier, missing-report SKIP,
  metric-absent SKIP, check_id formatting, V.2 PASS + SKIP paths.
- **`test_pipeline_coordinator.py`** (9 tests): happy path (7 stages
  ran, canonical state persisted, log written), failure modes (no
  documents, cross-check blocked with/without skip, bad WACC),
  `force_cost_override` probes the cap at call-time, guardrail FAIL
  flips `outcome.success`.
- **`test_cli_process.py`** (10 tests): exit code 0 on PASS, flag
  plumbing (`--force`, `--skip-cross-check`, `--force-cost-override`
  threaded to the coordinator), exit 1 on cross-check block, exit 2
  on `PipelineError` + guardrail FAIL, missing-wacc exits 2, help.
- **`test_phase1_pipeline_e2e.py`** (1 integration): full EuroEyes
  synthetic end-to-end with mocked LLM + mocked FMP/yfinance, real
  everything else. Asserts 7 stages ran, canonical state persisted,
  run-log has 7 stage rows + 8 guardrail rows.

## Decisions taken

1. **Guardrails are context-dict driven (`Guardrail.check(context)`).**
   Matches the Phase 0 ABC we already have (`guardrails/base.py`).
   Context keys — `canonical_state`, `cross_check_report`,
   `wacc_inputs` — are stable and documented at the top of each
   check's docstring so call sites never guess.
2. **Tiered tolerances on arithmetic guardrails** (PASS/WARN/FAIL).
   The spec asked for "FAIL if delta > 0.5 %; WARN 0.1–0.5 %; PASS <
   0.1 %" on IS; generalised to per-check tuples. BS is tighter
   (0.01 % / 0.1 %) because the identity must hold; CF is looser
   (0.5 % / 2 %) because rounding + FX typically accumulate. A.2
   matches CF tolerance bands.
3. **Subtotal filtering on IS checksum.** The IS parser emits both
   atomic lines (Revenue, COGS, OpEx, D&A, finance, tax) and
   subtotals (Gross Profit, Operating Income, PBT, EBIT/EBITDA).
   Summing everything double-counts. The guardrail matches subtotal
   labels with a keyword filter; atomic lines + NI anchor give the
   identity. Documented in the check's docstring.
4. **V.1 pass-through rather than re-checking.** The cross-check
   gate is already authoritative; V.1 guardrails lift its verdict
   into the guardrail block so the pipeline's overall status
   reflects it and the audit trail shows it in one place. No
   duplicate network calls.
5. **V.2 recomputes independently of the @property.** Even though
   `WACCInputs.wacc` is a pure property, the guardrail re-implements
   the formula so a refactor of one side would surface as a WARN.
   Non-blocking because a WACC typo will propagate into valuation
   downstream and surface there.
6. **`UNAVAILABLE` cross-check metric → SKIP, not WARN.** A metric
   neither provider publishes isn't a fail signal; same neutrality
   as the cross-check gate's own roll-up (Sprint 5 decision).
7. **Pipeline stages are sequential, short-circuit on error.** If a
   stage fails (PipelineError or CrossCheckBlocked), downstream
   stages don't run. Guardrails run last; their FAIL doesn't stop
   downstream stages (there are none), but flips `outcome.success`
   and drives exit code 2.
8. **`force_cost_override` as a settings context manager.** Uses
   `contextmanager` to raise `settings.llm_max_cost_per_company_usd`
   to USD 10 000 for the duration of `process()` and restore it in
   `finally`. Cleaner than plumbing an override parameter through
   `ExtractionCoordinator` + `P1IndustrialExtractor`.
9. **Run log as JSONL, one record per stage + one per guardrail.**
   Machine-friendly; each line is a complete JSON object. Header
   record (type="run_header") carries overall timing + success.
   Never crashes the pipeline on disk failure (OSError caught).
10. **CLI exit codes mirror the spec.** 0 = PASS/WARN, 1 = cross-check
    blocked (actionable — retry with `--skip-cross-check` or fix the
    extraction), 2 = everything else that should stop the batch.

## Spec auto-corrections

1. **Spec Parte L sketched guardrails but not the canonical-state
   payload.** Implementation uses `canonical_state.reclassified_statements[0]`
   as the primary source (first period only — Phase 1 scope). Multi-
   period guardrails wait on Phase 2's multi-period extraction.
2. **Spec didn't define ``V.1.CROSSCHECK_TOTAL_ASSETS``'s fallback
   when the metric is absent.** Decision 6 above: SKIP. Tests pin it.
3. **Spec didn't specify IS subtotal handling.** Decision 3 above:
   keyword-filter "operating income", "gross profit", "profit before
   tax", "pretax income", "ebit", "ebitda". E2E smoke + unit tests
   pin that excluding subtotals is necessary and sufficient.
4. **Spec named the CLI flag `--force-cost-override` but didn't
   specify the bypass mechanism.** Decision 8 above: settings context
   manager raising the cap to USD 10 000 for the run.
5. **Spec said "if FAIL and not skip_cross_check: prompt user
   (CLI interactive) for override/abort/re-extract".** Phase 1 keeps
   the CLI non-interactive — cross-check FAIL exits 1 (actionable:
   the user inspects the report, fixes upstream, and retries with or
   without `--skip-cross-check`). Interactive prompting is a clean
   additive in Phase 2 if needed; deferring avoids CliRunner TTY
   plumbing for Sprint 8.

## Files created / modified

```
A  src/portfolio_thesis_engine/guardrails/checks/__init__.py
A  src/portfolio_thesis_engine/guardrails/checks/arithmetic.py
A  src/portfolio_thesis_engine/guardrails/checks/validation.py
A  src/portfolio_thesis_engine/pipeline/__init__.py
A  src/portfolio_thesis_engine/pipeline/coordinator.py
A  src/portfolio_thesis_engine/cli/process_cmd.py
M  src/portfolio_thesis_engine/cli/app.py                      (+process command)
A  tests/unit/test_guardrails_arithmetic.py                    (21 tests)
A  tests/unit/test_guardrails_validation.py                    (13 tests)
A  tests/unit/test_pipeline_coordinator.py                     (9 tests)
A  tests/unit/test_cli_process.py                              (10 tests)
A  tests/integration/test_phase1_pipeline_e2e.py               (1 integration)
A  docs/sprint_reports/23_phase1_guardrails_and_process_cli.md (this file)
```

## Verification

```bash
$ uv run pytest
# 634 passed, 5 skipped in 7.48s

$ uv run ruff check src tests
# All checks passed!

$ uv run mypy src
# Success: no issues found in 78 source files
```

## Tests passing / failing + coverage

| Sprint 8 module                                  | Stmts | Miss | Cover |
| ------------------------------------------------ | ----- | ---- | ----- |
| `guardrails/checks/__init__.py`                  |   7   |  0   | 100 % |
| `guardrails/checks/arithmetic.py`                | 142   |  4   |  97 % |
| `guardrails/checks/validation.py`                |  72   |  0   | 100 % |
| `pipeline/__init__.py`                           |   2   |  0   | 100 % |
| `pipeline/coordinator.py`                        | 262   | 18   |  93 % |
| `cli/process_cmd.py`                             |  83   | 12   |  86 % |
| **Sprint 8 subtotal**                            | 568   | 34   | **94 %** |

Target ≥85 %; delivered 94 %. Uncovered lines are defensive arms
(OSError on log write, unreachable safety guards, import-time branches
inside the CLI's real-service wiring that the mocked tests skip).

## Cost estimate

LLM cost this sprint: **$0** (guardrails are deterministic; the CLI
+ pipeline make no additional LLM calls beyond what section extractor
+ extraction coordinator already emit). The E2E integration smoke
mocks every external call — runs offline in <1 s.

## Problems encountered

1. **IS checksum double-counted subtotals.** First e2e run failed with
   `Σ components 365 vs NI 75 (386 % off)` — my test fixture included
   both atomic lines (Revenue, COGS, …) *and* the `Operating income`
   subtotal; summing both double-counts. Fixed in two complementary
   places: (a) the guardrail filters subtotal labels before summing;
   (b) the fixture was extended to include the S&M / G&A / D&A lines
   that were missing, so the atomic sum actually balances.
2. **`IncomeStatementLine` lacks a ``category`` field.** Unlike
   `BalanceSheetLine` / `CashFlowLine`, the IS line schema carries
   only `label` + `value`. Subtotal filtering must be label-based
   rather than category-based. Worked around with a keyword list;
   acceptable for Phase 1, worth revisiting in Phase 2 when we add
   ``category`` to the IS line schema.
3. **`contextmanager` inside an `async` function.** The
   `_temporary_cost_cap` wrapper uses plain `contextmanager` not
   `asynccontextmanager`; fine because it sets/restores a scalar
   on the settings object (no I/O). Used via `with cap_ctx: await
   coord.process(...)` inside the coroutine body.
4. **`ruff` caught an unused `Any` + trailing `del Any`** in the CLI
   (relic of an earlier iteration where the signature needed it).
   Cleaned up; no behavioural change.

## Sprint 8 summary + Phase 1 scope coverage

Phase 1 now has a working end-to-end pipeline: `pte ingest` →
`pte process` produces a fully-validated `CanonicalCompanyState`,
cross-checked against external sources, with a complete audit trail
(JSONL log + guardrail verdict). 634 tests passing, mypy-strict clean,
94 % coverage on the Sprint 8 surface.

Remaining Phase 1 work (per the original 10-sprint plan):

- **Sprint 9** — Valuation engine (DCF 3-scenario, equity bridge,
  IRR decomposition, `ValuationSnapshot` composer).
- **Sprint 10** — Ficha composer + Streamlit UI + `pte valuate` /
  `pte ficha` / `pte ui` CLI commands.

## Next step

Sprint 9 — Valuation engine (Parte F of the spec). Hugo's call on
scope + timing.
