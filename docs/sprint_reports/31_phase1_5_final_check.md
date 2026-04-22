# Phase 1.5 — Final check

**Date:** 2026-04-22
**Scope:** close out Phase 1.5 — the extraction pivot to Claude.ai
Projects. Ship the four boundary docs, the realistic fixtures, the
integration tests, and the architecture / README refresh.

## Acceptance checklist

| # | Criterion                                                                                             | Status |
| - | ----------------------------------------------------------------------------------------------------- | ------ |
| 1 | Zero LLM calls in the pipeline.                                                                       | ✅     |
| 2 | `RawExtraction` schema validates every boundary YAML (42 DocumentType + 17 note types).                | ✅     |
| 3 | 3-tier validator (strict / warn / completeness) wired into pipeline, strict FAIL blocks.              | ✅     |
| 4 | Modules A / B / C + AnalysisDeriver consume `RawExtraction` directly — no adapter shim.                | ✅     |
| 5 | `pte process` runs 11 stages end-to-end on the EuroEyes fixture.                                       | ✅     |
| 6 | `pte validate-extraction` + `pte audit-extraction` CLIs shipped.                                       | ✅     |
| 7 | Four markdown docs for Claude.ai Projects shipped.                                                     | ✅     |
| 8 | Realistic few-shot fixtures under `tests/fixtures/euroeyes/`.                                          | ✅     |
| 9 | Integration smoke (mocked market data) + real-API smoke (gated) present.                              | ✅     |
| 10 | Global coverage ≥ 90 %, ruff + mypy clean.                                                            | ✅     |

## Sprint-by-sprint summary

### Sprint 27 — RawExtraction schema + parser
Introduced `schemas/raw_extraction.py` (initial draft) + an ingestion
parser. Focused on the top-level skeleton: metadata, IS / BS / CF
dicts, notes container stub. First fixture.

### Sprint 28 — Schema FULL SCOPE + 3-tier validator
Expanded to the full 376-line schema: 42 DocumentType enum values, 17
typed note types, `ExtractionType` / `PeriodType` / classification
literals, extensions dicts on statements / notes / historical.
Introduced `ExtractionValidator` with strict / warn / completeness
tiers and the `REQUIRED_NOTES_BY_PROFILE` checklist.

### Sprint 29 — Pipeline + CLI refactor
Deleted the Phase-1 `section_extractor/` package (−4069 LOC net).
Replaced the old `SECTION_EXTRACT` pipeline stage with two new
stages: `LOAD_EXTRACTION` and `VALIDATE_EXTRACTION`. Added
`ExtractionValidationBlocked` pipeline error. Added CLI commands
`pte validate-extraction` and `pte audit-extraction`. Introduced a
Sprint-2 `raw_extraction_adapter.py` shim to keep the Phase-1 module
surface alive during the transition.

### Sprint 30 — Modules consume RawExtraction directly
Killed the Sprint-29 adapter shim (−515 LOC). Rewrote Module A /
Module B / Module C / AnalysisDeriver + the extraction coordinator +
the pipeline coordinator to consume `RawExtraction` directly. Module
A uses `TaxItemClassification` without any intermediate mapping;
Module B routes on `ProvisionClassification` and pulls from
`notes.goodwill` / `notes.discontinued_ops`; Module C reads
`LeaseNote` typed fields. Net −800 LOC. All 832 tests passing, 94 %
global coverage.

### Sprint 31 (this sprint) — Final check
- Four markdown docs for Claude.ai Projects knowledge bases:
  `claude_ai_extraction_guide.md` (~10 pages), `raw_extraction_schema.md`,
  `document_types.md`, `required_notes_by_profile.md`.
- Two realistic fixtures: `raw_extraction_ar_2024.yaml` (full P1 AR)
  + `raw_extraction_interim_h1_2025.yaml` (H1 interim).
- Renamed integration test to `test_phase1_5_pipeline_e2e.py` + added
  deeper analysis-value assertions (IC, NOPAT, ratios, scenarios).
- Updated `docs/phase1_architecture.md` for Phase 1.5 (11 stages, no
  `section_extractor/` refs) and `README.md` (Phase 1.5 workflow +
  status).

## Final metrics

| Metric                                              | Value          |
| --------------------------------------------------- | -------------- |
| Unit tests                                          | 832 passing    |
| Integration tests (in-suite)                        | 2 (E2E + smoke) |
| Skipped tests (gated by `PTE_SMOKE_HIT_REAL_APIS`)  | 6              |
| Global coverage                                     | **94 %**       |
| `extraction/*` module coverage                      | **97 % – 100 %** |
| `pipeline/coordinator.py` coverage                  | 96 %           |
| `schemas/raw_extraction.py` coverage                | 99 %           |
| ruff                                                | clean          |
| mypy                                                | clean (91 src files) |
| Net LOC Phase 1.5 (across 48 touched files)         | +6760 / −5493 = +1267 |
| Adapter shim deletion                               | −515 LOC       |
| `section_extractor/` deletion (Phase-1 removal)     | −4069 LOC      |

## What works end-to-end (now)

- Producing a `raw_extraction.yaml` in a Claude.ai Project using the
  7-pass workflow documented in
  [`claude_ai_extraction_guide.md`](../claude_ai_extraction_guide.md).
- Local validation: `pte validate-extraction path/to/yaml --profile P1`
  runs all three validator tiers and reports per-check status.
- Ingesting the YAML + `wacc_inputs.md`:
  `pte ingest --ticker X --files yaml,wacc_md`.
- Running the 11-stage pipeline: `pte process X` →
  `CanonicalCompanyState` + `ValuationSnapshot` + `Ficha` persisted
  under `{data_dir}/yamls/companies/X/`.
- Viewing the aggregate: `pte show X` (Rich) or the Streamlit UI.
- Auditing a shipped extraction: `pte audit-extraction X`.

## What was tested

- **Unit (832 tests):** every module in isolation; the pipeline
  coordinator with mocks; the 3-tier validator against every
  classification bucket; the CLI commands against temp workspaces.
- **Integration (1 test):** `test_phase1_5_pipeline_e2e.py` runs the
  real pipeline on the EuroEyes fixture with mocked market data —
  11 stages, specific IC / NOPAT / ratio assertions, 3-scenario
  valuation, ficha round-trip.
- **Real-API smoke (1 test, gated):** `test_euroeyes_real_smoke.py`
  under `PTE_SMOKE_HIT_REAL_APIS=true` hits live FMP + yfinance against
  Hugo's real `~/data_inputs/euroeyes/raw_extraction.yaml`.
- **Fixtures validated:** both new fixtures pass strict; AR 2024
  passes completeness (all 15 P1 required + recommended notes
  present); H1 2025 trips completeness FAIL by design (interim
  reports disclose a subset — documented).

## What is deferred to Phase 2

- **Multi-document merge.** Phase 1.5 processes one YAML per run. Phase 2
  will merge annual + interim + earnings-call YAMLs into one canonical
  state with a full audit trail of what came from which document.
- **Narrative processing.** The `NarrativeContent` schema is defined
  but the pipeline doesn't yet do anything with `key_themes` /
  `guidance_changes` / `q_and_a_highlights`. Phase 2 adds the narrative
  stages.
- **Profiles P2–P6.** Only P1 Industrial is shipped. P2 (Banks),
  P3a (Insurance), P3b (REITs), P4 (Resources), P5 (Pre-revenue),
  P6 (Holdings) need: profile-specific methodology docs, Claude.ai
  Project templates, schema additions for sector-specific notes
  (Pillar 3 tables, Solvency II SCR/MCR, FFO/AFFO, NI 43-101
  reserves), and module adaptations.
- **Modules D / E / F + Patches 1–7.** Phase 1 shipped A / B / C;
  Phase 2 lands Pensions (D), SBC (E), Capitalize-Expenses (F), NCI
  (Patch 1), Associates (Patch 2), Discontinued Ops (Patch 3),
  Business Combinations (Patch 4), Hyperinflation (Patch 5), CTA
  (Patch 6), SOTP (Patch 7).
- **Capital allocation + DuPont + CAGRs.** The `analysis.py`
  `AnalysisDerived` schema has placeholders (`capital_allocation`,
  `dupont_decomposition`) that Phase 2 populates once multi-period
  processing lands.
- **Portfolio cross-company dashboard.** Phase 1.5 ships per-company
  artefacts; Phase 2 adds the cross-portfolio view (factor exposures,
  correlations, thesis tracking).

## Phase 2 roadmap (proposed order)

1. **Multi-period AnalysisDeriver** — unblock CAGRs, DuPont, capital
   allocation history. Requires iterating over all periods in
   `income_statement` / `balance_sheet` / `cash_flow` dicts (the
   deriver currently uses only `primary_period`).
2. **Multi-document merge** — combine annual + interim, provenance
   tags per field.
3. **Module D (Pensions) + Module E (SBC)** — both have fully
   populated schema note types already (`PensionNote`, `SBCNote`).
4. **Narrative stages** — ingest earnings-call transcripts via
   Claude.ai Projects (same boundary pattern); pipeline grows
   narrative-aware stages.
5. **Profile P2 (Banks)** — as the next most common profile after
   P1. Triggers schema additions for banking-specific notes.

## Known limitations

- `pte show` does not yet render the Narrative section — the schema
  has the shape, the composer doesn't use it yet.
- The W.CAPEX warn in the EuroEyes AR 2024 fixture trips at 6.25 %
  vs. the 5 % tolerance; this is realistic (PP&E movement with
  disposals + FX translation routinely trips close calls) and serves
  as a teaching example for extractors.
- Real-API smoke requires `~/data_inputs/euroeyes/raw_extraction.yaml`
  + `wacc_inputs.md` present; skipped otherwise.

## Closing

Phase 1.5 delivered what matters most: **the extraction boundary moved
out of the app, and the pipeline is now deterministic end-to-end.**
Every numeric value in a canonical state is traceable through a
validated YAML to a specific document and page. No LLM opacity inside
the app.

The four docs in `docs/` are the operator's manual for producing the
boundary YAML; with them uploaded to a Claude.ai Project, Hugo can
onboard a new issuer in ~45–60 min and update an existing one in
~20 min.

Phase 2 starts from a clean base: zero shims, zero deprecated code,
every module consuming typed schemas directly.
