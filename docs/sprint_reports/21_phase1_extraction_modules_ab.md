# Phase 1 · Sprint 6 — Extraction Modules A + B

**Date:** 2026-04-21
**Phase 1 Step (Parte E):** 6 — Extraction coordinator + Modules A & B
**Status:** ✅ Complete

---

## What was done

First pass of the reclassification engine. Consumes the
`ExtractionResult.sections` produced by `section_extractor` and applies
the Module A (taxes) + Module B (provisions) methodology, emitting
`ModuleAdjustment` objects + a decision/estimates log. Module C
(leases) + `AnalysisDeriver` follow in Sprint 7.

- **`extraction/__init__.py`** — public surface:
  `ExtractionContext`, `ExtractionModule`, `ExtractionResult`,
  `ExtractionCoordinator`, `ModuleATaxes`, `ModuleBProvisions`.
- **`extraction/base.py`** — `ExtractionContext` dataclass (mutable,
  threaded between modules), `ExtractionModule` ABC, `ExtractionResult`
  dataclass, and `parse_fiscal_period(label)` helper that turns
  `FY2024` / `Q3 2024` / unknown into a valid `FiscalPeriod`.
- **`extraction/module_a_taxes.py`** — `ModuleATaxes(ExtractionModule)`.
  Reads `notes_taxes.parsed_data` produced by Pass 2, classifies each
  reconciling item as operating vs non-operating by enum + label
  heuristic, applies A.2.0 materiality, computes the operating tax
  rate (A.1), emits one adjustment per non-operating item (A.2) plus
  the operating-rate adjustment, and logs A.3 (DTA/DTL), A.4 (cash
  taxes), A.5 (BS treatment).
- **`extraction/module_b_provisions.py`** — `ModuleBProvisions`. Walks
  the IS line_items, flags non-operating items by `category` enum +
  label patterns (goodwill impairment, restructuring, disposal
  gains/losses, generic impairment, litigation settlements), emits one
  adjustment per match with a canonical sub-type.
- **`extraction/coordinator.py`** — `ExtractionCoordinator(profile, llm,
  cost_tracker, modules=None)`. Loads `[ModuleATaxes, ModuleBProvisions]`
  for P1_INDUSTRIAL; explicit `modules=` override for tests and
  Sprint 7. `extract(section_result, wacc_inputs) -> ExtractionResult`
  runs modules in declared order, enforces per-company cost cap
  between modules, returns a result carrying adjustments + logs +
  `modules_run`.

**Tests:** 39 new unit tests.

- `test_module_a_taxes.py` (15 tests): happy path with mixed
  operating/non-op items, decision-log counts, A.2.0 materiality gate,
  label heuristic for `category == "other"` (goodwill keyword wins;
  neutral labels stay operating), fallbacks (no section, empty
  parsed_data, missing effective_rate, zero-effective edge, PBT
  derived from reported_tax/effective_rate), A.3/A.4/A.5 notes,
  robustness (malformed amounts ignored, empty list still emits rate).
- `test_module_b_provisions.py` (12 tests): goodwill / restructuring /
  disposal detection, specificity (goodwill beats generic
  "impairment"), multiple items all captured, non-detection when IS
  has no flagged items, B.0 applicability paths (no IS, empty
  line_items, `parsed_data=None`), robustness (malformed amounts,
  empty labels).
- `test_extraction_coordinator.py` (12 tests): P1 loads Modules A+B,
  unsupported profile raises `NotImplementedError`, explicit
  `modules=` override, declared-order module execution, context
  propagates between modules, end-to-end P1 with real modules,
  cost-cap enforcement before first module + between modules,
  `parse_fiscal_period` covers FY/Q/unknown/empty.

## Decisions taken

1. **Modules mutate the shared `ExtractionContext` rather than
   returning a new one.** Matches the spec's sketches (E.4–E.7),
   keeps module call-sites tiny, and makes ordering explicit: the
   Nth module always sees the first N-1 modules' adjustments in
   `context.adjustments`. Tests pin this by inspecting "saw
   X existing adj" from a recording module.
2. **Module A is deterministic — no LLM call.** The LLM-driven part
   already happened in `section_extractor` Pass 2, which returned a
   category-tagged reconciling-items list. A second classification
   call would add cost without adding accuracy. The category enum
   from `TAX_RECON_TOOL` is the canonical classification; label
   heuristics fill in for items tagged `other`. If real-world data
   ends up producing too many `other` items, we can add a fallback
   LLM classifier later.
3. **Non-operating category → non-operating bucket, `prior_year_adjustment`
   also non-operating, everything else operating.** `prior_year_adjustment`
   is mechanically a reconciling item but conceptually a true-up, not a
   recurring driver of the operating tax rate. Tests pin this.
4. **A.2.0 materiality uses `|Σ non-op| / |statutory_tax|`, threshold
   5 %.** When non-operating items are tiny relative to the statutory
   tax, we skip the split entirely and use `effective_rate` as
   `operating_rate`. Reduces noise for single-year outliers.
5. **Label heuristic for `category == "other"` is conservative.**
   Matches on a short keyword list (`goodwill`, `impairment`,
   `disposal`, `restructuring`, `one-off`, `prior year`, `acquisition`,
   `settlement`, `litigation`). Anything else stays operating. Rationale:
   false-positive non-op reclassifications distort ROIC; false-negative
   stays in operating, which is the spec's default anyway.
6. **Label-pattern table in Module B is ordered by specificity.**
   `goodwill impairment` (specific) appears before `impairment of`
   (generic) so `_classify_is_line` picks the right sub-type on the
   first match. One test pins the precedence directly.
7. **PBT is derived when not disclosed.** `pbt = reported_tax /
   (effective_rate / 100)`. When both PBT and effective_rate are
   missing or zero, we fall back to the WACC statutory rate (A.1
   fallback path). Edge case covered by `test_zero_effective_rate_forces_statutory_fallback`.
8. **Sign convention on Module B adjustments: amount matches the IS
   value as-reported.** Negative for expenses/losses, positive for
   gains. The NOPAT-bridge constructor in Sprint 7 reads this amount
   and subtracts it from operating income; downstream consumers
   never need to re-interpret signs.
9. **`parse_fiscal_period` sentinel: `year=1990`.** When the label
   doesn't match `FY\d{4}` or `Q\d \d{4}`, we still return a valid
   `FiscalPeriod` (the floor year) so constructing
   `ModuleAdjustment.affected_periods` never raises. This keeps the
   extraction engine resilient to upstream identifier noise.
10. **Cost cap enforced _between_ modules, not per LLM call.** Same
    pattern as `section_extractor` Sprint 2: a stage boundary check.
    One `_enforce_cost_cap` call before each module via the
    shared `CostTracker.ticker_total` reader. Tests pin both
    "cap hit before first module" and "cap hit mid-run" paths.

## Spec auto-corrections

1. **Spec E.4 sketched `canonical_state = build_canonical_state(...)`.**
   Sprint 6 doesn't yet build the full `CanonicalCompanyState` —
   that's Sprint 7's job once `AnalysisDeriver` produces `InvestedCapital`,
   `NOPATBridge`, and `KeyRatios`. The Sprint 6 `ExtractionResult`
   carries just `adjustments + logs + modules_run`; Sprint 7 will
   extend this dataclass with `canonical_state`.
2. **Spec E.4 `ExtractionContext` didn't include a `ticker` field.**
   The cost-cap check needs `ticker` to call
   `CostTracker.ticker_total`, so we carry it on the context itself
   instead of plumbing it as a separate parameter to every module.
3. **Spec E.5 sketched `context.current_period`.** We renamed to
   `primary_period` to match `section_extractor`'s `primary_fiscal_period`
   convention — the two are the same value, but the extraction engine
   uses the section-extractor spelling.
4. **Spec didn't define per-category operating/non-operating mapping.**
   Decision 3 above documents the rule. Tests pin every enum value
   in both the operating and non-operating buckets.
5. **Spec didn't specify PBT-derivation fallback.** When notes_taxes
   doesn't disclose PBT explicitly, we back it out from
   `reported_tax / effective_rate`. When both are zero we bail to
   the statutory fallback. Decision 7 above.

## Files created / modified

```
A  src/portfolio_thesis_engine/extraction/__init__.py
A  src/portfolio_thesis_engine/extraction/base.py
A  src/portfolio_thesis_engine/extraction/coordinator.py
A  src/portfolio_thesis_engine/extraction/module_a_taxes.py
A  src/portfolio_thesis_engine/extraction/module_b_provisions.py
A  tests/unit/test_module_a_taxes.py                        (15 tests)
A  tests/unit/test_module_b_provisions.py                   (12 tests)
A  tests/unit/test_extraction_coordinator.py                (12 tests)
A  docs/sprint_reports/21_phase1_extraction_modules_ab.md   (this file)
```

No existing files were modified. Section extractor, ingestion,
cross_check and storage remain untouched.

## Verification

```bash
$ uv run pytest
# 561 passed, 5 skipped in 7.07s

$ uv run ruff check src tests
# All checks passed!

$ uv run mypy src
# Success: no issues found in 70 source files
```

## Tests passing / failing + coverage

All 561 unit tests pass; 5 integration tests skipped (gated across
Phase 0 + 1).

| Sprint 6 module                                        | Stmts | Miss | Cover |
| ------------------------------------------------------ | ----- | ---- | ----- |
| `extraction/__init__.py`                               |   5   |  0   | 100 % |
| `extraction/base.py`                                   |  46   |  0   | 100 % |
| `extraction/coordinator.py`                            |  36   |  0   | 100 % |
| `extraction/module_a_taxes.py`                         | 100   |  0   | 100 % |
| `extraction/module_b_provisions.py`                    |  61   |  0   | 100 % |
| **Sprint 6 subtotal**                                  | 248   |  0   | **100 %** |

Target was ≥85 %; delivered 100 %.

## Cost estimate

LLM cost this sprint: **$0** (Modules A and B are deterministic —
they consume the parsed data already produced by section_extractor).
Sprint 7 will introduce one LLM call per run via Module C (leases
disclosure parse).

## Problems encountered

1. **First test iteration on A.2 happy-path tripped A.2.0 materiality.**
   Original fixture used a `-2.0` non-op amount against `statutory_tax=50.0`
   → ratio 4 % < 5 % → module took the immaterial branch and the test
   assertion on the A.2 log line didn't fire. Bumped the non-op amount
   to `-6.0` in `test_decision_log_records_counts_and_rates`.
2. **`ruff` flagged unused `statutory_rate` variable.** Parsed from
   `notes_taxes.statutory_rate_pct` but never used — the module
   computes the operating rate directly from PBT + non-operating sum.
   Removed. Decision: we don't need `statutory_rate_pct` explicitly
   in Sprint 6; A.3/A.4/A.5 paths use `statutory_tax` instead.
3. **Zero-effective-rate edge case was uncovered** — lines 185-189 of
   `module_a_taxes.py` (fallback when PBT can't be derived). Added
   `test_zero_effective_rate_forces_statutory_fallback` to pin it.
   Coverage went from 98 % to 100 %.

## Next step

**Sprint 7 — Module C + AnalysisDeriver + end-to-end smoke**
(Hugo's next authorised batch):

- `extraction/module_c_leases.py` (IFRS 16 base, capitalization,
  lease additions for FCFF, C.0–C.3 subset).
- `extraction/analysis.py` — `AnalysisDeriver` produces
  `InvestedCapital` (IC = Op Assets − Op Liab), `NOPATBridge` (EBITA
  − Op Taxes → NOPAT + Fin Inc − Fin Exp − Non-op → Reported NI)
  and `KeyRatios` (ROIC, ROE, margins, Net Debt/EBITDA, Revenue
  CAGR).
- Extend `ExtractionCoordinator` to add Module C + run
  `AnalysisDeriver` after modules + build the full
  `CanonicalCompanyState`.
- End-to-end smoke with the EuroEyes synthetic fixture + mocked LLM,
  asserting the pipeline produces a valid `CanonicalCompanyState`.
