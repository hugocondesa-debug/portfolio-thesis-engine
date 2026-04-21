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

# Launch UI (placeholder until Phase 1)
uv run streamlit run src/portfolio_thesis_engine/ui/app.py
```

## Structure

5 storage layers, all accessed via Repository classes (no direct file/DB access from modules):

| Layer | Backend | Purpose |
|---|---|---|
| YAMLs (git-versioned) | filesystem | Source of truth for human-edited entities (Ficha, Position, Peer, MarketContext) |
| DuckDB | `data/timeseries.duckdb` | Analytical time series (prices, factors, peer metrics) |
| ChromaDB | `data/chromadb/` | RAG / vector search over documents |
| Filesystem blobs | `data/documents/` | PDFs, source filings |
| SQLite metadata | `data/metadata.sqlite` | Relational metadata (companies, archetypes, clusters, joins) |

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

**Phase 0** — Foundations (in progress)
- Repo structure, schemas, storage layer, LLM orchestrator, guardrails framework, CLI, DevOps

**Phase 1** — Portfolio System MVP (next)
- Parser of forecast outputs, Dashboard, Scenario tuner, Ficha viewer

## License

MIT
