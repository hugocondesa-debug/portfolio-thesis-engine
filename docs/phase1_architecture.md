# Phase 1.5 — Pipeline Architecture

## Summary

The Phase 1.5 pipeline takes a human-produced `raw_extraction.yaml`
(built in a Claude.ai Project — see
[`claude_ai_extraction_guide.md`](claude_ai_extraction_guide.md))
plus a `wacc_inputs.md` file and produces three persisted artefacts:
a `CanonicalCompanyState`, a `ValuationSnapshot`, and a `Ficha`.
Invoked end-to-end via:

```bash
uv run pte ingest --ticker 1846.HK \
  --files raw_extraction.yaml,wacc_inputs.md
uv run pte process 1846.HK
uv run pte show 1846.HK    # or the Streamlit UI
```

The Phase 1.5 pivot (Sprints 27–30) moved all LLM-driven extraction
**outside** the app into Claude.ai Projects. The app now consumes the
typed YAML deterministically — **zero LLM calls inside the pipeline**.

## Pipeline diagram

```
  ┌──────────────────────────────┐
  │  Claude.ai Project (per      │   Upstream, outside the app.
  │  profile) — Hugo drives the  │   Produces raw_extraction.yaml
  │  7-pass extraction workflow  │   matching the RawExtraction schema.
  └──────────────┬───────────────┘
                 │
                 ▼
  ┌──────────────────────────────┐
  │  raw_extraction.yaml         │
  │  + wacc_inputs.md            │
  └──────────────┬───────────────┘
                 │
                 ▼
  ┌──────────────────────────────────────────┐
  │  1. pte ingest   (BulkMarkdownMode)      │
  │     DocumentRepository + MetadataRepo    │
  └──────────────┬───────────────────────────┘
                 │
  ┌──────────────▼─────────────────────────────────────────────────────┐
  │  pte process — PipelineCoordinator — 11 stages (no LLM)            │
  │                                                                    │
  │   1. check_ingestion         documents present under ticker         │
  │   2. load_wacc               parse wacc_inputs.md → WACCInputs     │
  │   3. load_extraction         parse raw_extraction.yaml → RawExtraction
  │                              + unit-scale normalisation            │
  │   4. validate_extraction     3-tier validator (strict / warn /     │
  │                              completeness); strict FAIL blocks      │
  │   5. cross_check             CrossCheckGate (FMP + yfinance)       │
  │   6. extract_canonical       Modules A, B, C + AnalysisDeriver     │
  │                              (consume RawExtraction directly)      │
  │   7. persist                 CompanyStateRepository                │
  │   8. guardrails              A.* arithmetic + V.* validation       │
  │   9. valuate                 3-scenario FCFF DCF + equity + IRR    │
  │  10. persist_valuation       ValuationRepository                   │
  │  11. compose_ficha           FichaComposer → CompanyRepository     │
  └──────────────┬─────────────────────────────────────────────────────┘
                 │
                 ▼
  ┌──────────────────────────────┐
  │   pte show  /  Streamlit UI  │  FichaLoader + Rich / Streamlit
  └──────────────────────────────┘
```

Run log persisted at `logs/runs/{ticker}_{ts}.jsonl` per run.

## Module map

```
src/portfolio_thesis_engine/
├── ingestion/          Sprints 1, 27-28 — BulkMarkdownMode, WACCParser,
│                       RawExtractionParser, ExtractionValidator (3-tier)
├── cross_check/        Sprint 5  — CrossCheckGate (FMP + yfinance)
├── extraction/         Sprints 6-7 + 30 — Modules A, B, C +
│                       AnalysisDeriver (consume RawExtraction directly)
├── guardrails/         Sprint 8  — A.* arithmetic + V.* validation
├── valuation/          Sprint 9  — FCFF DCF + EquityBridge + IRR + Composer
├── ficha/              Sprint 10 — FichaComposer + FichaLoader
├── pipeline/           Sprint 8+ — PipelineCoordinator (11-stage orchestrator)
├── cli/                — typer app (ingest, process, show, cross-check,
│                         validate-extraction, audit-extraction)
├── ui/                 Sprint 10 — Streamlit Ficha viewer
├── storage/            Fase 0    — filesystem + sqlite + yaml + chroma + duckdb
├── schemas/            Fase 0 + 28 — Pydantic v2 schemas (RawExtraction,
│                       canonical state, valuation, ficha, wacc)
├── market_data/        Fase 0    — FMPProvider, YFinanceProvider
├── llm/                Fase 0    — AnthropicProvider, CostTracker, router
│                       (kept for Phase 2 narrative processing; not used
│                        in the Phase 1.5 pipeline)
└── shared/             Fase 0    — config, exceptions, logging_, types
```

**Phase 1.5 deleted** the `section_extractor/` package and the Phase-1
LLM-driven 3-pass extractor. Extraction now happens in Claude.ai
Projects upstream — the app's boundary is `raw_extraction.yaml`.

## Data flow

```
raw_extraction.yaml
     │ (parse + unit-normalise)
     ▼
RawExtraction (typed schema — 376 lines, 17 note types)
     │
     │ (3-tier validator — strict / warn / completeness)
     ▼
 Validated RawExtraction
     │
     │ (cross-check vs FMP + yfinance — blocks on FAIL)
     ▼
 Modules A/B/C consume typed fields directly
     │
     ▼
AnalysisDeriver → CanonicalCompanyState (reclassified IS/BS/CF +
                                         adjustments + analysis)
     │
     ├─► GuardrailResult[] (A.* + V.*)
     │
     ▼
ValuationSnapshot (3 scenarios × DCF + equity bridge + IRR)
     │
     ▼
Ficha (aggregate view)
     │
     ▼
YAML on disk at {data_dir}/yamls/companies/{ticker}/
```

## Key decisions (Phase 1.5)

- **Boundary is the YAML, not the PDF.** Claude.ai Projects produce
  a schema-validated YAML; the app consumes it deterministically.
  Zero LLM calls inside the pipeline.
- **Classification vocabularies are closed literals.** Module A reads
  `TaxItemClassification` (`operational` / `non_operational` /
  `one_time` / `unknown`); Module B reads `ProvisionClassification`
  (`operating` / `non_operating` / `restructuring` / `impairment` /
  `other`). No intermediate mapping tables.
- **Unit scale normalised in the parser, not the modules.** The parser
  multiplies monetary Decimals by the scale factor on load; modules
  + analysis see base-unit values without caring about the source unit.
- **3-tier validator separates concerns.** Strict layer catches
  identity violations (total_assets ≠ total_liabilities + equity) and
  blocks. Warn layer surfaces anomalies (CapEx vs ΔPP&E + D&A) without
  blocking. Completeness layer checks profile-driven required notes.
- **Modules mutate a shared ExtractionContext.** Module A appends
  adjustments + decision-log entries; Module B sees Module A's output.
  Ordering declarative in the coordinator's profile loader.
- **Guardrail A.1.IS_CHECKSUM filters subtotal labels.** The IS line
  schema doesn't carry categories; the keyword filter prevents
  double-counting Operating Income / Gross Profit / PBT.
- **Leases stay in EV (don't subtract from equity bridge).** The
  Module C.3 lease-additions adjustment already counts leases as
  investment in the FCFF economic view.
- **IRR decomposition: re-rating is the residual.** Fundamental
  component = scenario revenue CAGR, dividend = 0 (Phase 1),
  re-rating solves the sum-to-total identity.
- **Valuation stages SKIP rather than fail when wiring is absent.**
  The pipeline's defaults do the minimum; the CLI wires the full
  service graph. Tests exercising subsets still pass.

## Where each artefact lives on disk

```
{data_dir}/documents/{ticker}/{doc_type}/{filename}         raw/ingested docs
{data_dir}/metadata.sqlite                                 companies, clusters, peers
{data_dir}/llm_costs.jsonl                                 per-call cost log (unused in 1.5)
{data_dir}/logs/cross_check/{ticker}_{ts}.json             per-gate report
{data_dir}/logs/runs/{ticker}_{ts}.jsonl                   per-run pipeline log
{data_dir}/yamls/companies/{ticker}/ficha.yaml             aggregate view
{data_dir}/yamls/companies/{ticker}/extraction/            versioned canonical state
{data_dir}/yamls/companies/{ticker}/valuation/             versioned valuation snapshot
```

## Test topology

- **Unit tests** (`tests/unit/`, 830+) — fast, deterministic, mocked
  external deps. Cover every module in isolation plus
  `PipelineCoordinator` end-to-end with injected mocks.
- **Integration smoke** (`tests/integration/test_phase1_5_pipeline_e2e.py`)
  — in-suite, no external calls, exercises real ingestion + parser +
  validator + pipeline coordinator with mocked market data. Asserts
  all 11 stages + specific analysis values + ficha + YAML round-trip.
- **Real-API smoke** (`tests/integration/test_euroeyes_real_smoke.py`)
  — gated by `PTE_SMOKE_HIT_REAL_APIS=true`, reads the actual
  EuroEyes `raw_extraction.yaml` from `~/data_inputs/euroeyes/`, hits
  live FMP + yfinance (no LLM). Structural assertions only.
- **Fixtures** — two few-shot examples under
  `tests/fixtures/euroeyes/`:
  - `raw_extraction_ar_2024.yaml` — full AR with all P1 required +
    recommended notes + segments + historical + KPIs.
  - `raw_extraction_interim_h1_2025.yaml` — H1 interim showing the
    schema's interim-period support + reduced note coverage.
