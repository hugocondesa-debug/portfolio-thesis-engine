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

## Phase 1 — End-to-end pipeline

Process a company from markdown to Ficha with a single CLI chain:

```bash
# 1. Ingest prepared markdown (annual report, interim, wacc_inputs.md)
uv run pte ingest --ticker 1846.HK \
  --files annual_report_2024.md,interim_h1_2025.md,wacc_inputs.md

# 2. Run the 10-stage pipeline (≈ $5–$10 API cost for a real company)
uv run pte process 1846.HK

# 3. Render the aggregate Ficha view
uv run pte show 1846.HK            # Rich tables
uv run pte show 1846.HK --json     # machine-readable output

# Or open the Streamlit UI
uv run streamlit run src/portfolio_thesis_engine/ui/app.py
```

See `docs/phase1_architecture.md` for the pipeline diagram and
`docs/phase1_schemas.md` for the top-level schemas.

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
- 10-stage `PipelineCoordinator` orchestrating: bulk-markdown ingestion → 3-pass LLM section extraction → FMP + yfinance cross-check gate → Modules A (taxes), B (provisions), C (leases) + AnalysisDeriver → guardrails A/V core (arithmetic + validation) → 3-scenario FCFF DCF + equity bridge + IRR decomposition → aggregate Ficha composer. `pte ingest / process / show / cross-check` CLI. Streamlit Ficha UI. 712 tests at 95 % coverage. Integration smoke over EuroEyes synthetic fixture + gated real-API smoke against `~/data_inputs/euroeyes/`.

**Phase 2 — Portfolio system + advanced extraction** (next)
- Multi-period extraction + DSO/DPO/DIO + ΔWC in DCF; Modules D (Pensions), E (SBC), F (Capitalize Expenses); Patches 1-7 (NCI, Associates, Discontinued Ops, Business Combinations, Hyperinflation, CTA, SOTP); Reverse DCF / Monte Carlo / EPS bridge; Research/RAG over earnings calls + MD&A; portfolio dashboard cross-empresa; scenario tuner interactivo; post-earnings update workflow; peer discovery runtime; archetypes P2-P6.

## License

MIT
