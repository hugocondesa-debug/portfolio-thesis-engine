# Architecture (Phase 0)

Portfolio Thesis Engine is a semi-automated investment workflow that
extracts reclassified financials from filings, produces probability-weighted
valuations, and tracks active positions against stated theses. This
document is the high-level map; per-module detail lives in each package's
docstring and in the Phase 0 spec (`SPEC_PHASE_0.md`).

## High-level layout

```
┌─────────────────────────────────────────────────────────────────────────┐
│ Entry points        pte (CLI · Typer)                                   │
│                     streamlit run ui/app.py  (Phase 0: placeholder)     │
└───────────┬─────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Application modules                                                     │
│                                                                         │
│   schemas/      Pydantic v2 contracts (immutable snapshots, value       │
│                 objects, mixins). YAML roundtrip helpers on BaseSchema. │
│                                                                         │
│   llm/          Anthropic provider (completion + tool use), OpenAI      │
│                 embeddings-only, CostTracker (JSONL), retry (tenacity), │
│                 router (TaskType → model), structured-output helpers.   │
│                                                                         │
│   market_data/  FMP provider over httpx (quotes, history, fundamentals, │
│                 key metrics, search, ticker validation). Typed errors.  │
│                                                                         │
│   guardrails/   Guardrail ABC + runner (exception → FAIL), aggregator,  │
│                 ReportWriter (text + JSON).                             │
│                                                                         │
│   cli/          `pte setup` · `pte health-check` · `pte smoke-test`     │
│                                                                         │
│   ui/           Streamlit placeholder (Phase 1 fills it).               │
└───────────┬─────────────────────────────────────────────────────────────┘
            │
            ▼
┌─────────────────────────────────────────────────────────────────────────┐
│ Storage layer (Repository pattern)                                      │
│                                                                         │
│   YAML         human-edited source of truth (ficha, positions, peers,   │
│                market contexts, valuation snapshots — versioned).       │
│                                                                         │
│   DuckDB       analytical time series (prices_eod, factor_series,       │
│                peer_metrics_history, computed_betas).                   │
│                                                                         │
│   SQLite       relational metadata (companies, archetypes, clusters,    │
│                company_clusters, company_peers) via SQLAlchemy 2.0.     │
│                                                                         │
│   ChromaDB     vector store for RAG. Injectable embedding_fn so tests   │
│                run offline and Phase 1 can wire OpenAI embeddings in.   │
│                                                                         │
│   Filesystem   blob storage for PDFs / transcripts, keyed by            │
│                (ticker, doc_type, filename).                            │
│                                                                         │
│   In-memory    drop-in Repository / VersionedRepository doubles for     │
│                unit tests in downstream modules.                        │
│                                                                         │
│   shared/      config (pydantic-settings), logging (structlog),         │
│                exceptions (PTEError hierarchy), type aliases.           │
└─────────────────────────────────────────────────────────────────────────┘
```

Every module accesses storage only through `Repository` / `VersionedRepository`.
Ticker strings are normalised at repository boundaries (`.` → `-`) so
callers pass `TEST.L` or `TEST-L` interchangeably — contract documented
in `storage/base.py`.

## Bounded contexts (Phase 1+ scope)

Phase 0 ships the plumbing; the contexts below will plug into it.

- **Extraction** (Phase 1) — parse filings, reclassify statements per
  profile (P1…P6), emit `CanonicalCompanyState`. Downstream read-only.
- **Valuation** (Phase 1) — consume `CanonicalCompanyState`, build
  scenarios (bear/base/bull), produce weighted `ValuationSnapshot`.
  Snapshots are immutable and versioned.
- **Portfolio** (Phase 1) — track `Position` entities, compute weights /
  PnL, compose `Ficha` aggregates from the latest snapshot + position +
  peer data.
- **Research** (Phase 2) — peer discovery, cross-checks, consensus
  comparison.
- **Synthesis** (Phase 2) — narrative generation, devil's-advocate
  review, final ficha text.

## Data flow (target, Phase 1+)

```
  Filings PDF  ──►  Extraction  ──►  CanonicalCompanyState (immutable, YAML)
                                           │
                                           ▼
                                    Valuation engine
                                           │
                                           ▼
                              ValuationSnapshot (versioned, YAML)
                                           │
                                           ▼
                 Position ◄──── Ficha (composed on demand)
```

Phase 0 provides every schema and repository in this diagram. The
engines themselves are deferred.

## Cross-cutting concerns

- **Cost tracking.** Every Anthropic call records a `CostEntry` in
  `llm_costs.jsonl` (JSONL for crash safety and human-editability).
  `CostTracker.ticker_total` lets any module cap per-company spend
  against `PTE_LLM_MAX_COST_PER_COMPANY_USD`.
- **Retry.** `llm.retry.with_retry` wraps provider calls with
  tenacity-driven exponential backoff. Retryable exception set includes
  baseline `ConnectionError`/`TimeoutError` plus Anthropic + OpenAI SDK
  rate-limit/transient errors.
- **Guardrails.** Every engine that produces output runs its results
  through a `GuardrailRunner`. Overall status uses a documented
  precedence (`FAIL > REVIEW > WARN > NOTA > PASS > SKIP`). Guardrails
  that raise become synthetic FAIL results — the runner never crashes.
- **Atomic writes.** YAML repositories write via
  `tempfile.mkstemp` + `Path.replace` so a mid-write crash leaves the
  live file intact. Versioned repos do the same for the `current`
  symlink.
- **Idempotency.** `pte setup` and `scripts/provision_vps.sh` both
  detect prior state and skip applied steps, so re-running is safe.

## DevOps

- `scripts/provision_vps.sh` — idempotent Ubuntu 24.04 bootstrap.
- `scripts/backup.sh` — daily tar of YAMLs + DuckDB copy + SQLite
  `.backup` + optional rclone sync.
- `systemd/pte-streamlit.service` — runs the UI under `portfolio` user,
  hardened with `ProtectSystem=strict` and explicit `ReadWritePaths`.
- `systemd/pte-backup.service` + `pte-backup.timer` — daily 03:30 with
  `Persistent=true` catch-up.

## Further reading

- `SPEC_PHASE_0.md` — full spec, including profile archetypes, module
  boundaries, and validation rules.
- `docs/schemas.md` — schema reference.
- `docs/sprint_reports/01_setup_basico.md` through `14_final_check.md`
  — decision log and spec auto-corrections per sprint.
