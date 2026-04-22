# Portfolio Thesis Engine

Semi-automated portfolio management with rigorous valuation.

Replaces a workflow of 40+ manual conversations per session with a unified Python application running on a VPS. Three goals:

1. **Valuation engine** — extraction + forecast + valuation multi-method, producing immutable versioned snapshots per company.
2. **Active portfolio management** — cross-portfolio dashboard, thesis tracking, scenario tuner, post-earnings update review.
3. **Unified knowledge base** — all documents indexed and queryable, with factor exposures and correlations.

## Quick Start

```bash
# Clone
git clone git@github.com:hugocondesa-debug/portfolio-thesis-engine.git
cd portfolio-thesis-engine

# Install dependencies
uv sync

# Configure
cp .env.example .env
# Edit .env with your API keys

# Bootstrap data directories
uv run pte setup

# Verify installation
uv run pte health-check
uv run pytest

# Smoke test (uses mocks by default)
uv run pte smoke-test

# Smoke test against real APIs (incurs ~$0.01 cost)
PTE_SMOKE_HIT_REAL_APIS=true uv run pte smoke-test

# Launch Streamlit Ficha UI
uv run streamlit run src/portfolio_thesis_engine/ui/app.py
```

## Phase 1.5 — End-to-end pipeline (current)

Phase 1.5 split extraction out of the app. You produce the boundary
YAML in a Claude.ai Project (see
[`docs/claude_ai_extraction_guide.md`](docs/claude_ai_extraction_guide.md)),
then the app consumes it deterministically — **zero LLM calls inside
the pipeline**.

```bash
# 1. Extract in Claude.ai Project (one per profile: P1, P2, ...)
#    Output: raw_extraction.yaml matching the RawExtraction schema.
#    See docs/claude_ai_extraction_guide.md for the 7-pass workflow.

# 2. Validate locally before shipping
uv run pte validate-extraction path/to/raw_extraction.yaml --profile P1

# 3. Ingest the YAML + manual WACC inputs
uv run pte ingest --ticker 1846.HK \
  --files raw_extraction.yaml,wacc_inputs.md

# 4. Run the 11-stage pipeline (no LLM cost; FMP / yfinance only)
uv run pte process 1846.HK

# 5. Render the aggregate Ficha view
uv run pte show 1846.HK            # Rich tables
uv run pte show 1846.HK --json     # machine-readable output

# Or open the Streamlit UI
uv run streamlit run src/portfolio_thesis_engine/ui/app.py
```

See [`docs/phase1_architecture.md`](docs/phase1_architecture.md) for the
pipeline diagram and [`docs/raw_extraction_schema.md`](docs/raw_extraction_schema.md)
for the boundary schema contract.

## Structure

5 storage layers, all accessed via Repository classes (no direct file/DB access from modules):

| Layer | Backend | Purpose |
|---|---|---|
| YAMLs (git-versioned) | filesystem | Source of truth for human-edited entities (Ficha, Position, Peer, MarketContext) |
| DuckDB | `data/timeseries.duckdb` | Analytical time series (prices, factors, peer metrics) |
| ChromaDB | `data/chromadb/` | RAG / vector search over documents |
| Filesystem blobs | `data/documents/` | PDFs, source filings |
| SQLite metadata | `data/metadata.sqlite` | Relational metadata (companies, archetypes, clusters, joins) |

Market-data providers (both implement `MarketDataProvider` — polymorphic):

| Provider | Source | Auth | Cost | Role |
|---|---|---|---|---|
| `FMPProvider` | Financial Modeling Prep `/stable/` | `FMP_API_KEY` | paid | primary |
| `YFinanceProvider` | Yahoo Finance via yfinance | none | free | alternative / cross-check |

See `docs/architecture.md` and `docs/schemas.md` for details.

## VPS Deployment

The systemd unit file `systemd/pte-streamlit.service` is hardcoded for user `portfolio`. If deploying under a different user, replace `portfolio` with your username before installing the unit.

```bash
# Provision Ubuntu 24.04 VPS
./scripts/provision_vps.sh

# Install systemd unit
sudo cp systemd/pte-streamlit.service /etc/systemd/system/
sudo systemctl enable --now pte-streamlit
```

## Status

**Phase 0 — Foundations** ✅ complete (2026-04-21)
- Repo scaffolding, 8 Pydantic schemas with YAML roundtrip, 5-layer storage (YAML + DuckDB + SQLite + Chroma + filesystem + in-memory doubles) with atomic writes and ticker normalisation, LLM orchestrator (Anthropic + OpenAI embeddings + cost tracking + retry + router + structured outputs), FMP market-data provider, guardrails framework, `pte` CLI (setup / health-check / smoke-test), Streamlit UI stub, DevOps (idempotent provisioning, backup, systemd units), 324 tests at 93 % coverage, ruff + mypy strict clean.

**Phase 1 — EuroEyes end-to-end MVP** ✅ complete (2026-04-21)
- 10-stage `PipelineCoordinator` orchestrating: bulk-markdown ingestion → 3-pass LLM section extraction → FMP + yfinance cross-check gate → Modules A (taxes), B (provisions), C (leases) + AnalysisDeriver → guardrails A/V core (arithmetic + validation) → 3-scenario FCFF DCF + equity bridge + IRR decomposition → aggregate Ficha composer. `pte ingest / process / show / cross-check` CLI. Streamlit Ficha UI. 712 tests at 95 % coverage.

**Phase 1.5 — Extraction pivot to Claude.ai Projects** ✅ complete (2026-04-22)
- Moved all LLM-driven extraction OUT of the app. Human + Claude.ai produce `raw_extraction.yaml` matching the 376-line `RawExtraction` schema (42 DocumentType values, 17 note types, ExtractionValidator 3-tier). Pipeline grew to 11 stages (added LOAD_EXTRACTION + VALIDATE_EXTRACTION). Modules A/B/C + AnalysisDeriver rewritten to consume typed schema directly — no adapter shim. Zero LLM calls in pipeline. 832 tests at 94 % coverage. Four docs for Claude.ai Projects: `claude_ai_extraction_guide.md` (10 pages), `raw_extraction_schema.md`, `document_types.md`, `required_notes_by_profile.md`.

**Phase 1.5.3 — Schema migration to as-reported structured** ✅ complete (2026-04-22)
- Rewrote `RawExtraction` to capture company lines verbatim as `list[LineItem]` with `is_subtotal` + `section` grouping; notes are a flat `list[Note]` with `NoteTable` children. Killed the 17 typed note classes and all closed classification enums. Motivation: observed EuroEyes extraction double-counted D&A because the fixed-field schema forced the extractor to map reported lines onto predefined slots. The new schema lets modules A/B/C classify downstream by label keyword. Walking-subtotals validator + nine knowledge docs. 771 tests at 93 % coverage, ruff + mypy --strict clean.

**Phase 2 — Portfolio system + advanced extraction** (next)
- Multi-document merge (annual + interim + earnings call into one canonical state); narrative processing (earnings calls, MD&A); Profiles P2 (banks), P3a (insurance), P3b (REITs), P4 (resources), P5 (pre-revenue), P6 (holdings); Modules D (Pensions), E (SBC), F (Capitalize Expenses); Patches 1-7; Reverse DCF / Monte Carlo / EPS bridge; portfolio dashboard cross-empresa; scenario tuner; post-earnings update workflow.

## License

MIT
