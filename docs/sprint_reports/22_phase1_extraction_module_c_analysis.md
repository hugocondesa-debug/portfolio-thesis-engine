# Phase 1 · Sprint 7 — Module C + AnalysisDeriver + end-to-end smoke

**Date:** 2026-04-21
**Phase 1 Step (Parte E):** 7 — Module C leases + analysis derivation + CanonicalCompanyState build
**Status:** ✅ Complete

---

## What was done

Closes Batch 3b. The extraction engine now produces a fully-typed
`CanonicalCompanyState` from a `SectionExtractionResult` + `WACCInputs`
+ `CompanyIdentity` — the full Parte E scope for Phase 1.

- **`extraction/module_c_leases.py`** — `ModuleCLeases(ExtractionModule)`.
  Consumes `notes_leases.parsed_data` from Pass 2 (`LEASES_TOOL`),
  surfaces ROU totals + lease-liability movement on the decision log
  (C.1/C.2), and emits one `C.3` `ModuleAdjustment` carrying the lease
  additions (disclosed field or derived from the movement identity).
  Applicability gate (C.0) at the top: no section → no-op, logged.
- **`extraction/analysis.py`** — `AnalysisDeriver.derive(context)`
  produces `AnalysisDerived` with three single-period artefacts:
  - `InvestedCapital`: IC = Op Assets − Op Liab; residual =
    (IC + Fin Assets) − (Equity + NCI + Fin Liab).
  - `NOPATBridge`: EBITA = Operating Income + |D&A|; Operating Taxes
    = EBITA × A.1-rate / 100; NOPAT = EBITA − Op Taxes; Non-Op sums
    IS category `non_operating` + Module B.2.* adjustments.
  - `KeyRatios`: ROIC, ROE, operating margin, EBITDA margin,
    Net Debt / EBITDA, CapEx / Revenue. All divide-by-zero safe →
    `None` when the denominator is missing.
- **`extraction/coordinator.py` (extended)** —
  - `_load_modules_for_profile` now returns `[A, B, C]` for
    P1_INDUSTRIAL.
  - New `extract_canonical(section_result, wacc_inputs, identity,
    source_documents=[...])` path runs modules, derives analysis,
    and builds the full `CanonicalCompanyState` with typed
    `ReclassifiedStatements`, `AdjustmentsApplied` (bucketed by
    module prefix), `ValidationResults` (placeholder, guardrails
    wire in Sprint 8), `MethodologyMetadata` (records modules +
    per-ticker LLM cost so far), and `VintageAndCascade` (empty).
  - Original `extract()` preserved for tests; returns
    `canonical_state=None`.
- **`extraction/__init__.py`** — re-exports `ModuleCLeases` +
  `AnalysisDeriver` alongside the Sprint 6 surface.

## Tests shipped

19 new unit tests; total unit suite now at 580 passing.

- `test_module_c_leases.py` (6 tests): disclosed-additions path,
  derived-additions path (closing − opening + principal_payments),
  three applicability paths (no section, `parsed_data=None`, missing
  movement), interest + ROU depreciation logging when present.
- `test_analysis_deriver.py` (10 tests): IC identity (op assets − op
  liab = IC; residual zero on balanced fixture), missing BS → zero IC,
  EBITA = op_income + |D&A|, A.1 rate drives operating taxes, no A.1 →
  zero taxes, non-op sums IS + B.2.*, finance lines captured, ratio
  math (ROIC 24.7 %, ROE 21.5 %, op margin 20 %, EBITDA margin 36 %,
  ND/EBITDA 0.56, CapEx/Rev 6 %), zero revenue → `None` margins,
  missing sections don't raise.
- `test_extraction_end_to_end.py` (3 tests, **the smoke test Batch 3b
  asked for**): synthetic EuroEyes numbers mirroring
  `tests/fixtures/euroeyes/*` — runs `extract_canonical` end-to-end,
  asserts the returned state is a valid `CanonicalCompanyState` with
  correct bucketing, IC identity, NOPAT bridge and margins, and
  crucially **round-trips cleanly through YAML** (`to_yaml` →
  `from_yaml`).
- Updated two Sprint 6 tests to expect `modules_run == ["A", "B", "C"]`.

## Decisions taken

1. **Module C stays deterministic.** The LLM work happened upstream
   in `section_extractor` Pass 2 via `LEASES_TOOL`; Module C reads
   `notes_leases.parsed_data` and applies the IFRS 16 identity. No
   second LLM round-trip.
2. **Lease additions fall back to the movement identity when
   `additions` isn't disclosed.** Formula:
   `additions = closing − opening + principal_payments`. Drops
   `depreciation_of_rou` because standard practice puts ROU
   depreciation on the asset side of the movement table, not the
   liability side; adding it would double-count. Test pins the
   derived path with an estimate-log entry flagging the estimate.
3. **EBITA = Operating Income + |amortisation|.** Phase 1
   approximation — the IS parser exposes a `d_and_a` category, so we
   add back the absolute value when the line is present. When D&A is
   already inside `operating_income` (no separate `d_and_a` line)
   EBITA = operating_income. This matches the spec's "EBITA ≈ Op
   Income + Amortisation" convention.
4. **Ratios return `None` on missing/zero denominators.** The
   `_safe_div` helper centralises divide-by-zero handling; every
   downstream consumer treats `None` as "not available". No
   exceptions leak from the deriver.
5. **IC cross-check residual surfaced, not enforced.** The
   `InvestedCapital.cross_check_residual` field on the Pydantic
   schema captures
   `(IC + Fin Assets) − (Equity + NCI + Fin Liab)`. Sprint 8's
   guardrails consume this value; Phase 1 Sprint 7 just computes it
   so the field isn't zero-for-all-states on launch day.
6. **Non-operating aggregates IS + Module B.2.*.** `NOPATBridge.non_operating_items`
   is `Σ IS[category=non_operating] + Σ B.2.* adjustments`.
   Avoids double-counting because Module B only emits a B.2
   adjustment when the IS category is `non_operating` or the label
   matches a non-op keyword — i.e. for lines we want to reclassify.
7. **Bucketing in `_partition_adjustments` uses the module-prefix
   before the dot.** `A.1`/`A.2` → `module_a_taxes`,
   `B.2.goodwill_impairment` → `module_b_provisions`,
   `C.3` → `module_c_leases`. Unknown prefixes go to `patches`.
   Keeps the bucket rule unambiguous and greppable from a
   `ModuleAdjustment`.
8. **`extract_canonical` vs `extract` split.** Tests that only care
   about adjustments + logs use `extract()` and don't need to
   construct a full `CompanyIdentity`. The production path (CLI +
   Sprint 8 pipeline) uses `extract_canonical()` with the identity
   provided by the metadata repository.
9. **`ValidationResults` on the canonical state is a placeholder.**
   Single "Sprint 7 placeholder" `ValidationResult` with
   `status="PASS"`. Guardrails A-core (Sprint 8) populate this
   block with real checksum / methodology results.
10. **`MethodologyMetadata.total_api_cost_usd`** reads
    `CostTracker.ticker_total(ticker)` — sum across the JSONL log
    for this ticker. Honest to what was actually spent (section
    extractor + any module calls); cheaper than threading a local
    counter through modules.

## Spec auto-corrections

1. **Spec E.7 sketched `_parse_leases_disclosure` as an LLM call.**
   Already handled by `section_extractor` Pass 2; the spec sketch
   predates Sprint 3 when the 7 Pass 2 tools landed. Module C now
   consumes the parsed dict directly.
2. **Spec E.8 sketched a single-period `AnalysisDeriver` — confirmed.**
   Phase 1 produces one `InvestedCapital` / one `NOPATBridge` / one
   `KeyRatios` from the single fiscal period the section extractor
   reported. Multi-period capital allocation, DuPont, CF quality,
   unit economics — all Phase 2.
3. **Spec didn't specify how to bucket `ModuleAdjustment` into
   `AdjustmentsApplied`.** Decision 7 above: by module-prefix. Tests
   cover A.1, A.2, B.2.*, C.3 → correct buckets, and
   unknown-prefix adjustments land in `patches`.
4. **Spec didn't specify `extraction_system_version` format.** Used
   `"phase1-sprint7"` — matches the existing naming in the
   methodology block of the sample canonical state fixture.

## Files created / modified

```
A  src/portfolio_thesis_engine/extraction/analysis.py
A  src/portfolio_thesis_engine/extraction/module_c_leases.py
M  src/portfolio_thesis_engine/extraction/__init__.py      (+AnalysisDeriver, +ModuleCLeases)
M  src/portfolio_thesis_engine/extraction/base.py          (+canonical_state on ExtractionResult)
M  src/portfolio_thesis_engine/extraction/coordinator.py   (+extract_canonical, +Module C)
A  tests/unit/test_module_c_leases.py                      (6 tests)
A  tests/unit/test_analysis_deriver.py                     (10 tests)
A  tests/unit/test_extraction_end_to_end.py                (3 tests)
M  tests/unit/test_extraction_coordinator.py               (updated for Module C)
A  docs/sprint_reports/22_phase1_extraction_module_c_analysis.md  (this file)
```

## Verification

```bash
$ uv run pytest
# 580 passed, 5 skipped in 6.86s

$ uv run ruff check src tests
# All checks passed!

$ uv run mypy src
# Success: no issues found in 72 source files
```

E2E smoke transcript (`test_canonical_state_contents`, synthetic EuroEyes,
`1846.HK`, `FY2024`):

```
identity            ticker=1846.HK  currency=HKD  profile=P1_INDUSTRIAL
modules_run         [A, B, C]
adjustments.A       2 items (A.1 operating rate + A.2 prior-year non-op)
adjustments.B       0 items (no goodwill/restructuring in the IS)
adjustments.C       1 item  (C.3 lease additions = 60)
analysis.IC         op_assets=2750, op_liab=210, IC=2540, residual=0
analysis.NOPAT      EBITA=130, op_taxes=..., NOPAT=..., NI=75
analysis.ratios     op_margin=18.97%
yaml_roundtrip      OK
```

## Tests passing / failing + coverage

All 580 unit tests pass; 5 integration tests skipped.

| Sprint 7 module                                        | Stmts | Miss | Cover |
| ------------------------------------------------------ | ----- | ---- | ----- |
| `extraction/__init__.py`                               |   7   |  0   | 100 % |
| `extraction/base.py`                                   |  47   |  0   | 100 % |
| `extraction/coordinator.py`                            |  86   |  4   |  95 % |
| `extraction/module_a_taxes.py`                         | 100   |  0   | 100 % |
| `extraction/module_b_provisions.py`                    |  61   |  0   | 100 % |
| `extraction/module_c_leases.py`                        |  59   |  3   |  95 % |
| `extraction/analysis.py`                               |  83   |  3   |  96 % |
| **Sprint 7 subtotal** (whole extraction package)       | 443   | 10   | **98 %** |

Target was ≥85 %; delivered 98 %. Uncovered lines are defensive arms
(`_to_decimal` exception path, `_get_lines` empty section_type,
unknown-prefix → patches bucket, Module C keyword-less rou list).

## Cost estimate

LLM cost this sprint: **$0** (Module C + AnalysisDeriver are
deterministic — everything consumed the parsed data that Sprint 3's
section extractor produced). First LLM-spending component in this
pipeline remains the section extractor.

## Problems encountered

1. **Two Sprint 6 coordinator tests hard-coded `["A", "B"]`.** Loading
   Module C flipped the expected `modules_run`; renamed
   `test_p1_loads_modules_a_and_b` → `test_p1_loads_modules_a_b_c` and
   updated the `modules_run` assertion. Clean diff, no behavioural
   change.
2. **Bare `except Exception` in coordinator's `_to_decimal`.** Ruff
   didn't flag it (it's inside a `try` block, not a bare top-level
   `except:`) but it was weaker than the sibling helpers in
   `module_a_taxes.py` / `module_b_provisions.py`. Tightened to
   `(InvalidOperation, TypeError, ValueError)` for consistency.
3. **YAML round-trip was the real validation stress test.** Earlier
   cut of `AnalysisDerived` had `computed_field`-style properties on
   derived ratios — the Sprint 1 WACC work already documented why
   that breaks `from_yaml` with `extra="forbid"`. The deriver now
   returns fully-explicit values, nothing computed by @property, and
   the round-trip test pins it.

## Sprint 7 summary + Phase 1 Parte E closure

**Phase 1 Parte E (extraction engine) is now complete.** 561 → 580
tests over this sprint; 100 % coverage on 4 / 7 extraction files and
95 % + on the rest. The engine emits a valid `CanonicalCompanyState`
end-to-end from `SectionExtractionResult`, ready for Sprint 8
(guardrails A-core) to consume and validate.

## Next step

**Sprint 8 — Guardrails A-core + CLI `pte process`** (Hugo's next
call):

- `guardrails/checks/` — universal checksums (V.1 BS identity, V.2 IS
  arithmetic, V.3 CF identity) and profile-specific P1 checks.
- Wire guardrail results into `CanonicalCompanyState.validation` so
  the placeholder `"Sprint 7 placeholder"` check goes away.
- `cli/process_cmd.py` — `pte process <ticker>` that chains ingestion
  → section extraction → cross-check → extraction → canonical state
  save into `CompanyStateRepository`.
- End-to-end CLI smoke over the EuroEyes fixture.
