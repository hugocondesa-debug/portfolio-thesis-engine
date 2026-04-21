# Phase 1.5 · Sprint 2 — Pipeline refactor + CLI

**Date:** 2026-04-21
**Scope:** Kill `section_extractor/` package, replace SECTION_EXTRACT
pipeline stage with LOAD_EXTRACTION + VALIDATE_EXTRACTION, add
`pte validate-extraction` + `pte audit-extraction` CLI commands,
update `pte ingest` + `pte process`. All 11 stages run end-to-end
on the EuroEyes raw_extraction fixture with no LLM calls in the
pipeline.
**Status:** ✅ Complete

---

## Why this sprint

Sprint 1 (FULL SCOPE) shipped the `RawExtraction` schema + validator
+ parser as the new human/Claude.ai → system boundary. Sprint 2
replaces the Phase 1 in-app LLM pipeline with a deterministic one
that consumes the YAML artefact directly.

The `section_extractor/` package (Phase 1 Sprints 2–4) is the
single biggest liability from the old architecture — 300+ LOC of
LLM tool-use wiring + Pass 1/2/3 prompts that hallucinate on
real reports. Removing it + wiring the validator in its place
eliminates the accuracy failure mode and drops the per-run LLM
cost from ~$5–$10 to $0 (the only remaining in-app LLM consumer
was this package).

## What shipped

### Deleted

```
src/portfolio_thesis_engine/section_extractor/        (7 files, ~1200 LOC)
  ├── __init__.py
  ├── base.py              SectionExtractor ABC + dataclasses
  ├── p1_extractor.py      P1 LLM-driven 3-pass extractor
  ├── prompts.py           Section identification + parsing prompts
  ├── tools.py             7 Anthropic tool definitions
  └── validator.py         Pass 3 checker (superseded by ExtractionValidator)

tests/unit/test_section_toc.py                        (Pass 1 tests)
tests/unit/test_section_parsers.py                    (Pass 2 tests)
tests/unit/test_section_validator.py                  (Pass 3 tests)

tests/fixtures/euroeyes/annual_report_2024_minimal.md (Phase 1 markdown)
tests/fixtures/euroeyes/interim_h1_2025_minimal.md    (Phase 1 markdown)
```

### Added

**`extraction/raw_extraction_adapter.py`** — Sprint-2 shim, deleted
in Sprint 3:

- Carries the `StructuredSection` + `SectionExtractionResult`
  dataclasses that the extraction modules still consume (copied
  verbatim from the deleted package so the modules don't need to
  change yet).
- `adapt_raw_extraction(raw, doc_id=None) → SectionExtractionResult`
  synthesises the Phase 1 `parsed_data` shape from a
  :class:`RawExtraction`:
  - IS / BS / CF field → category mappings (revenue / cost_of_sales /
    opex / d_and_a / cash / operating_assets / intangibles / …).
  - Tax note: `TaxReconciliationItem.classification` →
    old `category` enum (operational → non_deductible,
    non_operational → non_operating, one_time →
    prior_year_adjustment, unknown → other).
  - Lease note: `LeaseNote` → `lease_liability_movement` +
    `rou_assets_by_category` (aggregated from BS.rou_assets).
  - `statutory_tax` derived from `income_before_tax × statutory_rate /
    100` so Module A's materiality gate keeps working.
- Field labels preserved for guardrails that match on specific text
  (Net Income / Operating Income / Total Assets / …).

**`pipeline/coordinator.py`** — substantial refactor:

- **Removed**: `SectionExtractor` constructor parameter +
  `SECTION_EXTRACT` stage + `_stage_section_extract` method.
- **Added**: `LOAD_EXTRACTION` + `VALIDATE_EXTRACTION` stages +
  `extraction_path: Path` parameter on `process()`.
- **`LOAD_EXTRACTION`** calls `parse_raw_extraction(path)` (which
  also normalises unit scale); logs document metadata on the run
  log; wraps parser errors as `PipelineError`.
- **`VALIDATE_EXTRACTION`** runs all three tiers (`strict / warn /
  completeness`) and stores the reports on `PipelineOutcome`.
  Strict FAIL raises :class:`ExtractionValidationBlocked` (new
  pipeline exception, analogous to `CrossCheckBlocked`). Warn +
  completeness land in the log but don't halt.
- **Adapter bridge**: after `VALIDATE_EXTRACTION`, calls
  `adapt_raw_extraction(raw)` once and passes the resulting
  `SectionExtractionResult` into the existing cross-check +
  extract-canonical stages. Sprint 3 removes this line + rewrites
  the modules.
- **`PipelineOutcome`** gains `raw_extraction`,
  `extraction_validation_strict/warn/completeness` fields.
- Default validator injected (`ExtractionValidator()`) so tests
  can skip plumbing; constructor also accepts an override.

**`cli/process_cmd.py`**:

- `_build_coordinator` drops the Anthropic + section-extractor
  wiring (no LLM for Phase 1.5 pipeline).
- Added `--extraction-path` flag + `_resolve_extraction_path`
  helper (DocumentRepository → `~/data_inputs/{ticker}/
  raw_extraction.yaml` fallback).
- Rich output now includes an extraction-validation summary row +
  FAIL details when strict fails.
- Exit code 1 on `ExtractionValidationBlocked` (same as
  `CrossCheckBlocked`).

**`cli/ingest_cmd.py`**: added `--extraction / -e` shortcut that
appends the YAML path to `--files`.

**`cli/validate_extraction_cmd.py`** (new, 45 stmts, 100% cov):
`pte validate-extraction <path> [--profile P1]` runs all three
validator tiers and emits a Rich table per tier. Exit 0/1/2 per
the policy (strict FAIL → 2; any WARN / completeness FAIL → 1;
else 0).

**`cli/audit_extraction_cmd.py`** (new, 26 stmts, 100% cov):
`pte audit-extraction <ticker>` resolves the ingested copy first,
then the `~/data_inputs` default, and delegates to
`validate_extraction`.

**`cli/app.py`**: wires both new commands.

### Tests

- **`test_pipeline_coordinator.py`** — rewritten for the new
  signature (10 tests): happy-path 11-stage run + log lines,
  missing docs / bad WACC / bad extraction path → PipelineError,
  cross-check block with/without skip, `force_cost_override`
  probes the settings cap at call-time, strict validation FAIL
  raises `ExtractionValidationBlocked`, guardrail FAIL flips
  `outcome.success`.
- **`test_cli_process.py`** — updated: `_fake_paths` fixture stubs
  both resolvers, added `--extraction-path` to the help test +
  explicit-paths test + `ExtractionValidationBlocked` → exit 1.
  11 tests (was 10).
- **`test_raw_extraction_adapter.py`** (new, 22 tests): top-level
  shape, IS / BS / CF translations, tax note remapping
  (classification → category), lease note movement, ROU from BS,
  edge cases (no tax note → no section, no CF → no section),
  classification-map parametrised.
- **`test_cli_validate_extraction.py`** (new, 6 tests): clean
  fixture exits 0/1 (warns present), broken BS → exit 2, missing
  file → exit 2, profile flag, unknown profile → exit 2, help.
- **`test_cli_audit_extraction.py`** (new, 4 tests): resolves
  ingested copy; falls through to `~/data_inputs` default;
  missing both → exit 2; help.
- **`test_phase1_pipeline_e2e.py`** — rewritten for the new flow:
  real raw_extraction fixture + wacc_inputs fixture, mocked FMP/yf
  cross-check + market data, asserts 11 stages run, strict
  validation OK, canonical + valuation + ficha persisted. 1 test.
- **`test_euroeyes_real_smoke.py`** — rewritten for the new flow:
  expects `~/data_inputs/euroeyes/raw_extraction.yaml` +
  `wacc_inputs.md`; no LLM (extraction is the YAML). Still gated
  by `PTE_SMOKE_HIT_REAL_APIS=true`.

### Repointed imports

Every `from portfolio_thesis_engine.section_extractor...` import in
the extraction modules + pipeline + tests was repointed to
`portfolio_thesis_engine.extraction.raw_extraction_adapter` — nine
files updated, zero behavioural changes to the extraction modules
themselves (Sprint 3 rewrites them).

## Decisions taken

1. **Adapter shim over immediate module refactor.** Sprint 2 scope
   is pipeline + CLI. Module refactor is Sprint 3. The adapter
   keeps modules working against the same `parsed_data` dicts they
   were built for; Sprint 3 deletes both the adapter and the
   modules' dict-reading logic in favour of direct `RawExtraction`
   access.
2. **Strict FAIL blocks, warn does not.** The pipeline's
   `VALIDATE_EXTRACTION` stage raises
   `ExtractionValidationBlocked` only on strict FAIL (accounting
   identities broken — Hugo has to fix the YAML). Warn-tier and
   completeness-tier verdicts surface on the run log + CLI output
   but don't halt — they're informational.
3. **`pte validate-extraction` exit codes**: strict FAIL → 2 (same
   as a guardrail FAIL), any non-OK warn / completeness → 1
   (actionable but non-blocking), else 0. This matches the
   pipeline's treatment so scripts can chain validate → process
   predictably.
4. **`pte audit-extraction` is a thin wrapper.** It only does path
   resolution (DocumentRepository → `~/data_inputs` fallback) +
   delegates to `validate_extraction`. Keeps the validation logic
   in one place and means future changes to the validator
   automatically apply to both commands.
5. **`--extraction` on `pte ingest` is a shortcut, not a new
   command.** The existing ingestion flow handles arbitrary files;
   the flag just appends the YAML to the `--files` list. Hugo's
   workflow can `pte ingest --ticker 1846.HK --extraction
   path/to/raw_extraction.yaml` and later `pte process 1846.HK`
   picks it up via path resolution.
6. **Default `ExtractionValidator()` injected** into the pipeline
   coordinator's constructor. Tests that don't care about the
   validator skip plumbing; tests that do pass a mock. The
   validator's own behaviour is locked down by
   `test_raw_extraction_validator.py` (Sprint 1) — re-testing
   every branch through the pipeline would be duplication.
7. **Old integration test rewritten wholesale** rather than
   adapted. The Phase 1 test had ~200 lines of LLM dispatch
   mocking; the new version is ~180 lines without any LLM
   involvement. Cleaner in both the test and what it tests.

## Files created / modified

```
D  src/portfolio_thesis_engine/section_extractor/*                (7 files deleted)
D  tests/unit/test_section_toc.py
D  tests/unit/test_section_parsers.py
D  tests/unit/test_section_validator.py
D  tests/fixtures/euroeyes/annual_report_2024_minimal.md
D  tests/fixtures/euroeyes/interim_h1_2025_minimal.md

A  src/portfolio_thesis_engine/extraction/raw_extraction_adapter.py (148 stmts, 95% cov)
A  src/portfolio_thesis_engine/cli/validate_extraction_cmd.py       (45 stmts, 100% cov)
A  src/portfolio_thesis_engine/cli/audit_extraction_cmd.py          (26 stmts, 100% cov)

M  src/portfolio_thesis_engine/pipeline/coordinator.py              (rewired stages, 95% cov)
M  src/portfolio_thesis_engine/cli/process_cmd.py                   (+ extraction_path resolver)
M  src/portfolio_thesis_engine/cli/ingest_cmd.py                    (+ --extraction shortcut)
M  src/portfolio_thesis_engine/cli/app.py                           (+ 2 commands)
M  src/portfolio_thesis_engine/extraction/base.py                   (adapter import)
M  src/portfolio_thesis_engine/extraction/coordinator.py            (adapter import)

A  tests/unit/test_raw_extraction_adapter.py                        (22 tests)
A  tests/unit/test_cli_validate_extraction.py                       (6 tests)
A  tests/unit/test_cli_audit_extraction.py                          (4 tests)
M  tests/unit/test_pipeline_coordinator.py                          (rewritten, 10 tests)
M  tests/unit/test_cli_process.py                                   (11 tests, + extraction flag)
M  tests/integration/test_phase1_pipeline_e2e.py                    (rewritten for new flow)
M  tests/integration/test_euroeyes_real_smoke.py                    (rewritten for new flow)
M  tests/unit/test_module_a_taxes.py                                (adapter import)
M  tests/unit/test_module_b_provisions.py                           (adapter import)
M  tests/unit/test_module_c_leases.py                               (adapter import)
M  tests/unit/test_analysis_deriver.py                              (adapter import)
M  tests/unit/test_extraction_coordinator.py                        (adapter import)
M  tests/unit/test_extraction_end_to_end.py                         (adapter import)

A  docs/sprint_reports/29_phase1_5_pipeline_cli.md                  (this file)
```

## Verification

```bash
$ uv run pytest
# 857 passed, 6 skipped in ~8 s  (883 → 857, net −26 after deleting
# the 3 section_extractor test files + adding 42 new tests)

$ uv run ruff check src tests
# All checks passed!

$ uv run mypy src
# Success: no issues found in 92 source files
```

## Coverage on new code

| Module                                                   | Stmts | Miss | Cover |
| -------------------------------------------------------- | ----- | ---- | ----- |
| `extraction/raw_extraction_adapter.py`                   | 148   |  7   |  95 % |
| `cli/validate_extraction_cmd.py`                         |  45   |  0   | 100 % |
| `cli/audit_extraction_cmd.py`                            |  26   |  0   | 100 % |
| `pipeline/coordinator.py` (Sprint-2 additions)           | 355   | 18   |  95 % |
| **Sprint 2 subtotal**                                    | 574   | 25   |  96 % |

Above ≥85% target. Uncovered lines on the adapter / pipeline are
defensive arms (OS-level write failures, branches the fixture
doesn't hit) + the unhandled `Exception` catch-all in the pipeline
wrapper.

## Problems encountered

1. **Duplicate `r` variable in `_render`.** When I added the
   extraction-validation row to the CLI's render loop, I
   accidentally shadowed the guardrail-iterator variable. mypy
   caught it (`GuardrailResult` ≠ `ValidationResult`). Renamed to
   `fail` / `gr`.
2. **`ExtractionValidationBlocked` declared before
   `PipelineError`.** The ruff autofix put imports in sorted order
   and my hand-added class declaration ended up above its parent.
   Python runtime would have NameError'd on import. Moved back to
   the correct order.
3. **Test mocks for the new flow.** The `test_cli_process.py`
   fixture had to stub two resolvers (wacc + extraction) — the
   old `_fake_wacc` fixture became `_fake_paths` returning both.
   Every test that used `_fake_wacc` needed renaming too.
4. **Integration test scope creep risk.** Tempted to keep the
   Phase 1 LLM-dispatch mocks alive so test_phase1_pipeline_e2e
   could test "either pipeline flow". Resisted — the LLM flow is
   dead code now. Rewrote the test to use raw_extraction.yaml
   directly; simpler and faster.
5. **Adapter coverage miss on discontinued-ops branch.** The
   fixture doesn't exercise `net_income_from_discontinued` so
   the adapter's `non_operating` category mapping for that field
   is uncovered. Acceptable — the mapping is trivial and the
   module-level tests would catch a regression.

## What's unchanged (intentionally)

- Extraction modules (A taxes / B provisions / C leases) —
  Sprint 3 rewrites them.
- AnalysisDeriver — also Sprint 3.
- Cross-check gate + guardrails + valuation engine + ficha
  composer — pipeline-downstream, schema-agnostic.
- Streamlit UI — doesn't depend on section_extractor.

## Next step

**Sprint 3 (Fase 1.5)** — extraction modules refactor:
- `extraction/coordinator.py` takes `RawExtraction` instead of
  `SectionExtractionResult`.
- Module A reads `raw.notes.taxes` directly (no more
  `section.parsed_data` lookup).
- Module B reads `raw.income_statement[primary]` + `raw.notes.
  provisions` + `raw.notes.goodwill`.
- Module C reads `raw.notes.leases` directly.
- AnalysisDeriver reads statements + notes directly.
- Delete `extraction/raw_extraction_adapter.py` — the shim
  disappears along with the need for it.

Estimated 2h.
