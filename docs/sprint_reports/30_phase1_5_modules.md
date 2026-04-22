# Phase 1.5 — Sprint 3: Extraction modules consume `RawExtraction` directly

**Date:** 2026-04-21
**Branch:** `main`
**Scope:** Rewrite extraction modules A / B / C + AnalysisDeriver to consume
`RawExtraction` directly, delete the Sprint-2 `raw_extraction_adapter.py`
shim, propagate the change through the extraction + pipeline coordinators
and their tests.

## Goal

Kill the last transitional piece of infrastructure from the Phase-1 →
Phase-1.5 pivot. Sprint 2 moved extraction outside the app (Claude.ai
produces a typed YAML) but the existing Module A / B / C + AnalysisDeriver
still consumed the Phase-1 `SectionExtractionResult` shape via a 515-line
adapter shim. Sprint 3 rewrites them to consume `RawExtraction` directly.

## Changes

### Deleted

- **`src/portfolio_thesis_engine/extraction/raw_extraction_adapter.py`**
  (−515 LOC) — the Sprint-2 bridge between `RawExtraction` and the Phase-1
  module surface, including `StructuredSection`, `SectionExtractionResult`,
  the classification-mapping table and the three field-to-category tables.
- **`tests/unit/test_raw_extraction_adapter.py`** (−367 LOC).

### Rewritten

- **`extraction/base.py`** — `ExtractionContext` holds `raw_extraction:
  RawExtraction` instead of `sections: list[StructuredSection]`. Dropped
  the `find_section` helper.
- **`extraction/module_a_taxes.py`** — reads
  `raw.notes.taxes.reconciling_items` directly. Uses the
  `TaxItemClassification` vocabulary (`operational` / `non_operational` /
  `one_time` / `unknown`) straight — no intermediate mapping. PBT /
  reported_tax / statutory_tax now derived from the typed IS fields.
  A.4 cash-taxes check reads from `cf.extensions`.
- **`extraction/module_b_provisions.py`** — reads
  `raw.notes.provisions[classification]`, `raw.notes.goodwill.impairment`,
  `raw.notes.discontinued_ops`, and IS non-op fields
  (`non_operating_income`, `share_of_associates`,
  `net_income_from_discontinued`). `ProvisionClassification` routes
  straight into `B.2.*` adjustment subtypes.
- **`extraction/module_c_leases.py`** — reads `raw.notes.leases` directly
  via typed `Decimal | None` fields on `LeaseNote`. The
  `closing − opening + principal_payments` fallback identity stays.
- **`extraction/analysis.py`** — `AnalysisDeriver` consumes
  `raw.primary_is / primary_bs / primary_cf` directly. IC computed by
  named-field summation; NOPAT bridge anchored on IS fields; non-op items
  reconciling NOPAT → NI come straight off the IS (Module B adjustments
  continue to travel on the adjustments list for downstream consumers).
- **`extraction/coordinator.py`** — `extract()` / `extract_canonical()`
  take `raw_extraction: RawExtraction` instead of
  `section_result: SectionExtractionResult`. Reclassified statements are
  built line-for-line via two rendering tables
  (`_IS_LINES` / `_BS_LINES` / `_CF_LINES`). Extraction-system version
  bumped to `phase1.5-sprint3`.
- **`pipeline/coordinator.py`** — removed `adapt_raw_extraction` call and
  the adapter import; `_extract_cross_check_values()` + `_identity_from()`
  + `_stage_cross_check()` + `_stage_extract_canonical()` now consume
  `RawExtraction` directly.

### Tests

- `test_module_a_taxes.py`, `test_module_b_provisions.py`,
  `test_module_c_leases.py`, `test_analysis_deriver.py`,
  `test_extraction_coordinator.py`, `test_extraction_end_to_end.py`
  rewritten against `RawExtraction`. Each test builds a minimal
  `RawExtraction.model_validate(...)` payload and constructs the
  context directly — no more synthetic `StructuredSection` wrappers.
- `test_pipeline_coordinator.py` unchanged — its mocks don't care about
  coordinator kwargs, so the signature swap is transparent.
- `test_raw_extraction_adapter.py` deleted.

## Validation

- **Test suite**: `832 passed, 6 skipped` (full suite, same skip count as
  Sprint 2).
- **Coverage** (per rewritten module):
  - `extraction/module_a_taxes.py` — **100 %**
  - `extraction/module_b_provisions.py` — **100 %**
  - `extraction/module_c_leases.py` — **100 %**
  - `extraction/base.py` — **100 %**
  - `extraction/analysis.py` — **97 %**
  - `extraction/coordinator.py` — **94 %**
  - **Global**: **94 %**
- **Ruff**: clean.
- **mypy**: no issues in 91 source files.

## Net size

Diffstat across the 16 touched files: **+1536 / −2336 = −800 LOC net**.
The adapter alone accounts for −515 source LOC; the rest is the three
modules shrinking (A/C) + tests becoming more literal (no more
`dict[str, Any]` ceremony).

## What's next — Sprint 4 (final Phase 1.5 polish)

- 4 Claude.ai Project markdown docs (extraction guide, schema cheat sheet,
  document-type reference, profile completeness checklists).
- Integration smoke: `pte process 1846.HK --verbose` end-to-end against the
  real EuroEyes fixture.
- Phase 1.5 final check doc.
