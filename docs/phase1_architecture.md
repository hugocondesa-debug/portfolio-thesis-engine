# Phase 1 — Pipeline Architecture

## Summary

The Phase 1 pipeline takes prepared markdown documents for a company
and produces three persisted artefacts: a
:class:`CanonicalCompanyState`, a :class:`ValuationSnapshot`, and a
:class:`Ficha`. It is invoked end-to-end via:

```bash
uv run pte ingest --ticker 1846.HK --files <md-files...>
uv run pte process 1846.HK
uv run pte show 1846.HK    # or: uv run streamlit run src/portfolio_thesis_engine/ui/app.py
```

## Pipeline diagram

```
  ┌───────────────────────┐     Prepared outside the app:
  │  Markdown documents   │     Hugo converts PDFs → .md,
  │  + wacc_inputs.md     │     fills the WACC manual.
  └───────────┬───────────┘
              │
              ▼
  ┌───────────────────────────────────────────┐
  │  1. ingestion   (Modo B — bulk_markdown)  │  pte ingest
  │     DocumentRepository + MetadataRepository│
  └───────────┬───────────────────────────────┘
              │
  ┌───────────▼─────────────────────────────────────────────────┐
  │  pte process  (PipelineCoordinator — 10 stages)             │
  │                                                             │
  │   2. section_extract     P1IndustrialExtractor (LLM Pass 1+2+3)
  │   3. cross_check         CrossCheckGate (FMP + yfinance)    │
  │   4. extract_canonical   Modules A, B, C + AnalysisDeriver  │
  │   5. persist             CompanyStateRepository             │
  │   6. guardrails          A.* + V.* (8 checks)               │
  │   7. valuate             3-scenario DCF + equity + IRR      │
  │   8. persist_valuation   ValuationRepository                │
  │   9. compose_ficha       FichaComposer → CompanyRepository  │
  │  10. run log             logs/runs/{ticker}_{ts}.jsonl      │
  └───────────┬─────────────────────────────────────────────────┘
              │
              ▼
  ┌───────────────────────┐
  │   pte show  /  UI     │  FichaLoader + Rich / Streamlit
  └───────────────────────┘
```

Stages 7–9 are Sprint 9 + 10 additions; they SKIP cleanly when their
wiring isn't injected, so Sprint 8 callers that only want canonical
state + guardrails still get a correct outcome.

## Module map

```
src/portfolio_thesis_engine/
├── ingestion/          Sprint 1  — BulkMarkdownMode, WACCParser
├── section_extractor/  Sprints 2-4 — P1IndustrialExtractor (3-pass LLM)
├── cross_check/        Sprint 5  — CrossCheckGate (FMP + yfinance)
├── extraction/         Sprints 6-7 — Modules A, B, C + AnalysisDeriver
├── guardrails/         Sprint 8  — A.* arithmetic + V.* validation
├── valuation/          Sprint 9  — FCFF DCF + EquityBridge + IRR + Composer
├── ficha/              Sprint 10 — FichaComposer + FichaLoader
├── pipeline/           Sprint 8+ — PipelineCoordinator (10-stage orchestrator)
├── cli/                Sprints 1-10 — typer app (ingest, process, show, cross-check)
├── ui/                 Sprint 10 — Streamlit Ficha viewer
├── storage/            Fase 0    — filesystem + sqlite + yaml + chroma + duckdb repos
├── schemas/            Fase 0    — Pydantic v2 schemas (canonical state, valuation, ficha)
├── market_data/        Fase 0    — FMPProvider, YFinanceProvider
├── llm/                Fase 0    — AnthropicProvider, CostTracker, router
└── shared/             Fase 0    — config, exceptions, logging_, types
```

## Data flow

```
markdown ──► IngestedDocument ──► StructuredSection[] ──► ExtractionResult
                                                               │
            ┌─ CrossCheckReport ◄── extracted top-level values
            │
            ▼
CanonicalCompanyState ──► GuardrailResult[] (A.* + V.*)
     │                         │
     │                         └─► blocking flag feeds CLI exit code
     ▼
ValuationSnapshot ──► Ficha (aggregate view)
     │                 │
     ▼                 ▼
  versioned        single YAML
   YAML               on disk
```

## Key decisions (Phase 1)

- **LLM-returns-markers-Python-finds-offsets.** Pass 1 of the section
  extractor has the LLM emit literal heading strings; Python's
  `str.find` resolves char offsets. Avoids having the LLM guess
  character positions it can't count reliably.
- **Cost cap is coarse-grained (per stage, not per call).** Simpler
  than threading a budget through every LLM call; acceptable because
  Phase 1's total LLM spend per company is bounded (<$10).
- **Modules mutate a shared ExtractionContext.** Module A appends
  adjustments + decision-log entries; Module B sees Module A's output.
  Ordering is declarative in the coordinator's profile loader.
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
  service graph. Unit tests that only exercise Sprint 8 still pass.

## Where each artefact lives on disk

```
{data_dir}/documents/{ticker}/{doc_type}/{filename}.md
{data_dir}/metadata.sqlite                              companies, clusters, peers
{data_dir}/llm_costs.jsonl                              per-call cost log
{data_dir}/logs/cross_check/{ticker}_{ts}.json         per-gate report
{data_dir}/logs/runs/{ticker}_{ts}.jsonl               per-run pipeline log
{data_dir}/yamls/companies/{ticker}/ficha.yaml         aggregate view
{data_dir}/yamls/companies/{ticker}/extraction/        versioned canonical state
{data_dir}/yamls/companies/{ticker}/valuation/         versioned valuation snapshot
```

## Test topology

- **Unit tests** (`tests/unit/`, 710+) — fast, deterministic, mocked
  external deps. Cover every module in isolation plus
  `PipelineCoordinator` end-to-end with injected mocks.
- **Integration smoke** (`tests/integration/test_phase1_pipeline_e2e.py`)
  — in-suite, no external calls, exercises real ingestion + real
  coordinator with mocked LLM + market data. Asserts all 10 stages
  + ficha + YAML round-trip.
- **Real-API smoke** (`tests/integration/test_euroeyes_real_smoke.py`)
  — gated by `PTE_SMOKE_HIT_REAL_APIS=true`, reads the actual
  EuroEyes markdown from `~/data_inputs/euroeyes/`, hits live
  Anthropic + FMP + yfinance. ~$5–$10 per run. Structural
  assertions only (numeric values drift over time).
