# Phase 1 · Sprint 1 — Ingestion (BulkMarkdownMode + WACC parser)

**Date:** 2026-04-21
**Phase 1 Step (Parte K):** 1 — Ingestion
**Status:** ✅ Complete

---

## What was done

Arranque da Fase 1. Built the first entry point into the pipeline:

- **`schemas/wacc.py`** — new Pydantic schema `WACCInputs` with nested `CostOfCapitalInputs`, `CapitalStructure`, `ScenarioDriversManual`. WACC and cost of equity are derived from components (CAPM + after-tax weighted average). Validators: capital-structure weights sum to 100 ± 0.5, scenario probabilities sum to 100 ± 0.5, scenario labels restricted to `{bear, base, bull}`.
- **`ingestion/`** package — 5 modules:
  - `base.py`: `IngestionMode` ABC, `IngestedDocument` (frozen dataclass), `IngestionResult`, `IngestionError`.
  - `bulk_markdown.py`: `BulkMarkdownMode` with validate() (UTF-8 check, 50 MB cap, keyword sniff, FATAL/WARN classification) and ingest() (SHA-256 hashing, doc-type inference from filename, ISO report-date heuristic, storage via DocumentRepository).
  - `pre_extracted.py`: stub that raises `NotImplementedError("PreExtractedMode is Phase 2 — …")`.
  - `wacc_parser.py`: `parse_wacc_inputs(path) → WACCInputs` reading YAML frontmatter between `---` delimiters. Normalises YAML-auto-parsed `datetime.date` back to ISO strings.
  - `coordinator.py`: `IngestionCoordinator` dispatches by mode and upserts the ticker in the metadata store with the supplied profile.
- **`cli/ingest_cmd.py`** + `cli/app.py` — `pte ingest --ticker … --files a.md,b.md,c.md [--mode …] [--profile …]`. Rich table output, correct exit codes (0 happy, 1 validation failure, 2 Phase-2 mode).
- **Storage prereq commit** (`1535eda`): `MetadataRepository.upsert_company(ticker, profile=None, name=None, …)` — partial-info registration that falls back to placeholders on first insert and preserves existing columns on update.
- **Fixtures** under `tests/fixtures/euroeyes/`:
  - `annual_report_2024_minimal.md` — synthetic HKD-reporting P1 healthcare operator with EUR segment, 4-item tax reconciliation, non-trivial IFRS 16 leases note, 2 segments, 2-year comparative IS/BS/CF.
  - `interim_h1_2025_minimal.md` — condensed H1 with consistent trajectory.
  - `wacc_inputs.md` — full YAML-frontmatter WACC file for EuroEyes.
  All fixtures carry an explicit "SYNTHETIC DATA — do not interpret as real EuroEyes financials" header.

## Decisions taken

1. **WACC and cost of equity as plain `@property`, not `computed_field`.**
   `computed_field` serialises into `model_dump` output; combined with
   `extra="forbid"` on load, that breaks YAML roundtrip (derived values
   land back as extras on the next import). Plain `@property` keeps them
   derivable from components and out of the wire format — single source
   of truth for components stays in the YAML.
2. **PyYAML date normalisation in the WACC parser.** PyYAML's
   `safe_load` auto-parses `2025-03-31` into a Python `date`; our
   `valuation_date` field is a regex-validated ISO string. The parser
   walks the decoded tree and coerces `date`/`datetime` → `.isoformat()`
   before handing data to Pydantic. Saves callers from quoting every
   date in the markdown.
3. **Ingestion content-hash uses SHA-256 on raw bytes**, not on the
   decoded string. Guarantees identical on-disk bytes → identical hash
   across OS line-ending variations. Callers can use this for
   idempotence (same hash = same content = skip re-processing).
4. **`doc_type` inference from filename only.** Cheap, deterministic,
   and independent of the LLM extractor. Content-based detection is a
   Phase 2 refinement; Phase 1 enforces a naming convention.
5. **`report_date` inference conservatively matches year → `YYYY-12-31`
   for annual, `YYYY-06-30` for interim/H1/Q.** Explicit — the caller
   can always override later through the metadata repo. WACC files
   return `None` deliberately (not a period-scoped document).
6. **Coordinator explicit-None default for `modes`**, not
   `modes or {...defaults}`. Empty dict (e.g. test that wants zero
   modes) doesn't silently fall back to defaults; only literal `None`
   does. Caught by a dedicated test.
7. **`upsert_company` preserves existing columns.** If ingestion seeds
   the row with only a profile, a later `add_company` with full details
   still works. Critical for the coordinator-only-knows-the-ticker
   scenario on first ingest.
8. **`IngestionCoordinator.ingest(profile="P1")` default.** Every Phase 1
   company is P1 Industrial by design; explicit override supported.
9. **Fixtures are synthetic but structurally rich** per Hugo's guidance:
   multi-currency (HKD reporting, EUR subsidiary), non-trivial leases
   disclosure, 4-row tax reconciliation, 2 operating segments. Exercises
   the extractor pipeline in Sprints 2–4 without creating dependence on
   real EuroEyes filings that may change or get restated.
10. **WACC parser raises `IngestionError` on structural issues** (missing
    frontmatter, unclosed delimiter, non-dict top level) but lets
    `pydantic.ValidationError` propagate unchanged when the YAML is
    well-formed but violates the schema. Callers get rich error messages
    without the parser second-guessing Pydantic's output.

## Spec auto-corrections

1. **`WACCInputs` field shape** — spec (L.1 of the kickoff answer to my
   clarifying questions) specified a dict of scenarios; implemented as
   `dict[str, ScenarioDriversManual]` with label validation restricting
   keys to the three allowed values. Alternative (a list of scenarios
   with `label` field) rejected because the dict shape guarantees
   uniqueness of labels at the schema level.
2. **`tax_rate_for_wacc` typed as `Annotated[Decimal, Field(ge=0, le=100)]`**
   not `Percentage`. The spec's `Percentage` alias allows negative values
   (loss carry-forwards generate negative effective rates). For WACC
   input, negative tax is not a sensible input from the analyst — we
   want hard rejection. Narrower type, tighter contract.
3. **Spec B.6 `metadata_repo.upsert_company(ticker=ticker, profile="P1")`** —
   method didn't exist; implemented per Hugo's bloqueante #2 decision
   (separate commit with full test coverage before the main Sprint 1
   commit).

## Files created / modified

```
# Committed separately first (prereq):
M  src/portfolio_thesis_engine/storage/sqlite_repo.py
M  tests/unit/test_sqlite_repo.py
# Sprint 1 proper:
A  src/portfolio_thesis_engine/schemas/wacc.py
A  src/portfolio_thesis_engine/ingestion/__init__.py
A  src/portfolio_thesis_engine/ingestion/base.py
A  src/portfolio_thesis_engine/ingestion/bulk_markdown.py
A  src/portfolio_thesis_engine/ingestion/pre_extracted.py
A  src/portfolio_thesis_engine/ingestion/wacc_parser.py
A  src/portfolio_thesis_engine/ingestion/coordinator.py
A  src/portfolio_thesis_engine/cli/ingest_cmd.py
M  src/portfolio_thesis_engine/cli/app.py                    (+ingest command)
A  tests/unit/test_schemas_wacc.py                           (19 tests)
A  tests/unit/test_ingestion_bulk_markdown.py                (23 tests)
A  tests/unit/test_ingestion_coordinator.py                  (8 tests)
A  tests/unit/test_wacc_parser.py                            (9 tests)
A  tests/unit/test_cli_ingest.py                             (10 tests)
A  tests/fixtures/euroeyes/wacc_inputs.md                    (synthetic)
A  tests/fixtures/euroeyes/annual_report_2024_minimal.md     (synthetic)
A  tests/fixtures/euroeyes/interim_h1_2025_minimal.md        (synthetic)
A  docs/sprint_reports/16_phase1_ingestion.md                (this file)
```

## Verification

```bash
$ uv run pytest
# 432 passed, 4 skipped in 12.30s

$ uv run ruff check src tests && uv run ruff format --check src tests
# All checks passed! / all files formatted

$ uv run mypy src
# Success: no issues found in 54 source files

$ uv run pte --help
# … now lists 'ingest' alongside setup / health-check / smoke-test
```

End-to-end smoke via the ingestion coordinator (3 docs → stored + metadata upserted + WACC parsed):

```python
docs=3
  annual_report  → 1846-HK/annual_report/2024-12-31_annual_report_2024.md
  interim_report → 1846-HK/interim_report/2025-06-30_interim_h1_2025.md
  wacc_inputs    → 1846-HK/wacc_inputs/wacc_inputs.md
metadata: ticker=1846-HK profile=P1
parsed WACC: ticker=1846.HK wacc=8.6172%
```

## Tests passing / failing + coverage

All 432 unit tests pass; 4 integration tests skipped (gated by
`PTE_SMOKE_HIT_REAL_APIS`).

| Phase 1 new module                     | Stmts | Miss | Cover |
| -------------------------------------- | ----- | ---- | ----- |
| `schemas/wacc.py`                      |  70   |  3   |  96 % |
| `ingestion/__init__.py`                |   6   |  0   | 100 % |
| `ingestion/base.py`                    |  31   |  0   | 100 % |
| `ingestion/bulk_markdown.py`           |  89   |  3   |  97 % |
| `ingestion/pre_extracted.py`           |   9   |  0   | 100 % |
| `ingestion/wacc_parser.py`             |  41   |  2   |  95 % |
| `ingestion/coordinator.py`             |  18   |  0   | 100 % |
| `cli/ingest_cmd.py`                    |  47   |  6   |  87 % |
| **Phase 1 subtotal**                   | 311   | 14   |  95 % |
| **Project total**                      | 2357  | 151  |  94 % |

Comfortably above the ≥80 % sprint target. The uncovered lines in
`bulk_markdown.py` are defensive branches for the 50 MB size warning
(materialising a 50 MB tmpfile in CI is wasteful); `wacc_parser.py` has
a couple of guard paths on rare PyYAML failure modes; `cli/ingest_cmd.py`
has the "real DocumentRepository" instantiation path which tests
substitute via a fixture.

## Cost estimate

LLM cost: **$0** this sprint. No real-API calls executed. Integration
tests continue to skip under `PTE_SMOKE_HIT_REAL_APIS=false` default.

## Problems encountered

1. **`computed_field` broke YAML roundtrip.** Derived fields land in
   `model_dump` output; on load, `extra="forbid"` rejects them as
   unknown keys. Switched to plain `@property` — values stay derivable,
   YAML stays clean. (Documented in decisions #1.)
2. **PyYAML date auto-parse.** `valuation_date: 2025-03-31` becomes a
   Python `date`; our field accepts a string. Added `_stringify_dates`
   recursive coercion in the parser.
3. **`modes or {...}` fall-through in the coordinator.** Empty dict is
   falsy, so `IngestionCoordinator(modes={})` silently used defaults.
   Dedicated test caught this; switched to explicit `None` check.
4. **mypy complained about reusing `e` as a loop var after `except`
   blocks.** Renamed the loop var to `warning`; small readability win
   anyway.

## Next step

**Sprint 2 — Section Extractor Pass 1 (TOC identification).** Build
`section_extractor/base.py` + tools + prompt for locating document
sections. Accepts a markdown, returns a `{section_type: (start_char,
end_char, page_range, fiscal_period)}` map via LLM tool use. Tests with
fixtures + mocked LLM; integration gated.
