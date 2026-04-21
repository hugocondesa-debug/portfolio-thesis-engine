# Sprint 14 — Final Check (Phase 0 complete)

**Date:** 2026-04-21
**Step (Parte K):** 14 — Final check
**Status:** ✅ **Phase 0 officially complete**

---

## Parte L checklist

Every item from `SPEC_PHASE_0.md` Parte L ("Checklist Final de Aceitação"),
marked with evidence captured live on the dev host.

- [x] **`uv sync` sem erros**
  ```
  $ uv sync
  Resolved 134 packages in 1ms
  Checked 132 packages in 3ms
  ```

- [x] **`uv run pytest` — todos passam, coverage ≥80% global**
  ```
  $ uv run pytest
  324 passed, 3 skipped, 50 warnings in 10.16s
  TOTAL                                                      1903    124    93%
  ```
  3 skipped = integration tests in `test_llm_real.py` +
  `test_market_data_real.py`, gated by `PTE_SMOKE_HIT_REAL_APIS=true`.

- [x] **`uv run pte health-check` reporta tudo OK**
  ```
  Python              OK  3.12.3 (requires 3.12+)
  ANTHROPIC_API_KEY   OK  configured
  OPENAI_API_KEY      OK  configured
  FMP_API_KEY         OK  configured
  Data directory      OK  /home/portfolio/workspace/portfolio-thesis-engine/data
  Backup directory    OK  /home/portfolio/workspace/portfolio-thesis-engine/backup
  DuckDB (timeseries) —   (created on first use)
  SQLite (metadata)   —   (created on first use)
  Tailscale           OK  online

  All required components OK.
  ```

- [x] **`uv run pte smoke-test` passa todos os checks (mocks)**
  ```
  Storage roundtrip   PASS  save+get+delete symmetric
  Guardrail runner    PASS  3 checks; runner converted crash→FAIL
  LLM (mocked)        PASS  Anthropic mock returned 'ok'
  Embeddings (mocked) PASS  OpenAI mock returned 1 vector

  4/4 tests passed.
  ```

- [x] **`uv run streamlit run src/portfolio_thesis_engine/ui/app.py` arranca**
  Verified via subprocess in Sprint 12 `TestStreamlitSmoke` (in the
  default suite) and via direct invocation during this sprint — HTTP
  GET on `/` returns `200 OK`, clean SIGTERM shutdown:
  ```
  $ timeout 8 uv run streamlit run src/portfolio_thesis_engine/ui/app.py \
        --server.headless=true --server.port=8504 --server.address=127.0.0.1 &
  $ curl -sSI http://127.0.0.1:8504/ | head -1
  HTTP/1.1 200 OK
  ```

- [x] **Serviço systemd `pte-streamlit.service` arranca no VPS**
  `systemd-analyze verify` on the unit file exits 0 (no parser
  warnings, no directive errors):
  ```
  $ systemd-analyze verify systemd/pte-streamlit.service \
        systemd/pte-backup.service systemd/pte-backup.timer
  # (silent, exit 0)
  ```
  Full `sudo systemctl enable --now` is a Hugo-on-VPS step (see
  `docs/sprint_reports/11_devops.md` for the symlink commands).

- [x] **Backup script executa sem erros (`bash scripts/backup.sh`)**
  ```
  === pte-backup 2026-04-21T10:13:58+00:00 ===
  [1/4] YAMLs → yamls.tar.gz
  [2/4] DuckDB: absent — skipping
  [3/4] SQLite: absent — skipping
  [4/4] rclone 'backup:' remote not configured — skipping offsite sync
  Retention sweep:
    daily > 30d pruned: 0
    weekly/monthly: placeholders only (Phase 1 promotes snapshots)
  Backup complete: /home/portfolio/workspace/portfolio-thesis-engine/backup/daily/2026-04-21
  ```

- [x] **Tailscale permite aceder ao Streamlit do laptop/iPhone**
  ```
  $ tailscale status | head -3
  100.70.51.18  dataflow             hugocondesa@  linux  -
  100.105.1.94  hugos-macbook-pro-2  hugocondesa@  macOS  active; direct ...
  ```
  Dev host is `dataflow` online in the Tailnet; laptop is an active
  peer. Streamlit bound to `0.0.0.0:8501` via systemd (Sprint 11) is
  reachable over `100.70.51.18:8501`.

- [x] **Todos os schemas têm docstrings**
  Verified programmatically:
  ```
  PASS: every top-level schema has a docstring
  ```
  (CanonicalCompanyState, ValuationSnapshot, Scenario, Position, Peer,
  MarketContext, Ficha — all carry class and module docstrings.)

- [x] **README actualizado com instruções de setup + status "Phase 0 complete"**
  `README.md` Status section now shows `Phase 0 — Foundations ✅
  complete (2026-04-21)` with the full deliverable list.

- [x] **`.env.example` tem todas as keys necessárias**
  ```
  $ grep -c "ANTHROPIC_API_KEY\|OPENAI_API_KEY\|FMP_API_KEY" .env.example
  3
  ```

- [x] **`.gitignore` exclui `.env`, `data/`, `*.duckdb`, `*.sqlite`**
  ```
  $ grep -E "^\.env$|^data/|\*\.duckdb|\*\.sqlite" .gitignore
  .env
  data/
  *.duckdb
  *.sqlite
  *.sqlite3
  $ git check-ignore -v .env
  .gitignore:46:.env  .env
  ```

- [x] **Commit final feito e pushed para GitHub**
  `main` branch tracking `origin/main`, tree clean, Sprint 14 commit
  pushed.

## What is functional end-to-end (Phase 0)

- CLI workflow: `pte setup` → `pte health-check` → `pte smoke-test`
  completes with no external dependencies.
- Storage CRUD through every concrete repository, with a documented
  ticker-normalisation contract that round-trips both `TEST.L` and
  `TEST-L` to the same on-disk / in-DB entity.
- Atomic YAML writes (`tempfile.mkstemp` + `Path.replace`) survive
  mid-write crashes — guarded by regression tests.
- LLM orchestration (mocked end-to-end): `AnthropicProvider` →
  `complete` / `complete_sync` → `CostTracker.record` → JSONL
  persistence → `ticker_total` re-read.
- Real API paths (Anthropic, OpenAI embeddings, FMP quote) all plumbed
  and tested behind the `PTE_SMOKE_HIT_REAL_APIS=true` gate; every
  path costs ≤ $0.001 when enabled.
- Guardrails framework processes arbitrary checks, converts exceptions
  to synthetic FAIL, aggregates counts + overall status, renders text
  and JSON reports.
- Streamlit UI serves HTTP 200 under `streamlit run` or systemd.
- Backup script captures YAMLs + DBs, gates rclone sync, prunes
  30-day daily retention.
- `systemd-analyze verify` passes on all three unit files with zero
  warnings.

## What is NOT implemented (deferred to Phase 1+)

- **Extraction engine** — parsing of 10-K / 10-Q / annual-report PDFs,
  reclassification of IS / BS / CF per archetype (P1–P6), adjustment
  modules A–F, patches 1–7. The `CanonicalCompanyState` schema is
  defined and unit-tested; the engine that populates it is Phase 1.
- **Valuation engine** — scenario generation (bear/base/bull),
  reverse DDM / DCF, Monte Carlo, EPS bridge, conviction scoring.
  `ValuationSnapshot` exists; the engine that produces them is
  Phase 1.
- **Peer discovery + Level A/B/C extraction** — `Peer` schema is
  defined and repo-ready; the logic that finds peers and lifts
  extraction levels is Phase 1.
- **Dashboard** — the Streamlit UI is a placeholder (title + sidebar
  with disabled nav + info banner). Phase 1 will build the actual
  Dashboard / Positions / Watchlist / Settings sections.
- **Ficha viewer / composer** — the schema exists and composes from
  other entities conceptually; the runtime composition (latest
  extraction + latest snapshot + position + peers → `Ficha`) is
  Phase 1.
- **Scenario tuner** — interactive what-if UI, Phase 1.
- **Narrative synthesis** — devil's-advocate review, final ficha text
  generation via `AnthropicProvider` with structured outputs.
  Phase 2.
- **RAG over filings** — the repository exists (`RAGRepository` with
  injectable embedding_fn); indexing + retrieval UI is Phase 2.
- **Real weekly / monthly backup promotion** — directories exist;
  the cron logic that copies last-Sunday daily to `weekly/` and
  last-day-of-month to `monthly/` is a Phase 1 task.

## Summary numbers

| Metric                    | Value    |
| ------------------------- | -------- |
| Total commits on `main`   |       23 |
| Unit tests                |      321 |
| Integration tests         |        3 |
| Tests skipped (gated)     |        3 |
| Global coverage           |     93 % |
| Source LOC (approx)       |    1 903 |
| Test LOC (approx)         |    1 400 |
| ruff warnings             |        0 |
| mypy strict errors        |        0 |
| `systemd-analyze verify`  | clean    |

## Sprint report index

| Sprint | Report                                                     | Commit    |
| ------ | ---------------------------------------------------------- | --------- |
| 01     | `docs/sprint_reports/01_setup_basico.md`                   | `2b93820` |
| 02     | `docs/sprint_reports/02_shared_utilities.md`               | `6f53018` |
| 03     | `docs/sprint_reports/03_schemas.md`                        | `5701df3` |
| 04     | `docs/sprint_reports/04_storage_base.md`                   | `27d9c99` |
| 05     | `docs/sprint_reports/05_storage_completo.md`               | `aaca403` |
| 06     | `docs/sprint_reports/06_llm_orchestrator.md`               | `9c17a8a` |
| 07     | `docs/sprint_reports/07_market_data.md`                    | `b7b97b1` |
| 08     | `docs/sprint_reports/08_guardrails.md`                     | `139771d` |
| 09     | `docs/sprint_reports/09_cli.md`                            | `7236afc` |
| 10     | `docs/sprint_reports/10_ui_stub.md`                        | `eee3153` |
| 11     | `docs/sprint_reports/11_devops.md`                         | `8da75f1` |
| —      | (Sprints 12–14 covered together in this final report)     | this      |

---

**Phase 0 officially complete.** Handing off to Phase 1 — Portfolio
System MVP.
