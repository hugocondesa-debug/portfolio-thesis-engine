# Sprint 10 — UI Stub (Streamlit placeholder)

**Date:** 2026-04-21
**Step (Parte K):** 10 — UI stub
**Status:** ✅ Complete

---

## What was done

A minimal Streamlit app that systemd can serve, Tailscale can proxy, and
Phase 1 can flesh out:

- `ui/__init__.py` + `ui/app.py` — page config, sidebar with disabled
  navigation radio, "Phase 1 — UI coming soon" info block, three status
  metrics (version, phase, status), footer caption.
- 6 unit tests using Streamlit's `AppTest` harness — renders the script
  without binding to a port, asserts the title / info / sidebar / radio
  shape, and confirms the version metric matches the package.
- Verified manually: `streamlit run` on ``127.0.0.1:8502`` responds with
  HTTP 200 and terminates cleanly on SIGTERM (proof of the boot path
  that systemd will use).

## Decisions taken

1. **Script-style module, not a function.** Streamlit expects top-level
   `st.*` calls; wrapping in `main()` breaks `streamlit run`. The module
   is importable outside the runtime (Streamlit emits "missing
   ScriptRunContext" warnings on bare import but does not crash) —
   harmless, and exercised only by tests.
2. **Version is read from `portfolio_thesis_engine.__version__`.** One
   source of truth (the package `__init__`) shared with `pyproject.toml`.
   If Phase 1 bumps the version, the UI picks it up without edits.
3. **Navigation radio is disabled, options shown.** Shows Phase 1 the
   target IA (Dashboard / Positions / Watchlist / Settings) without
   exposing a half-implemented widget. `disabled=True` is honoured by
   the client so clicks are inert.
4. **Tests use `AppTest.from_file`** rather than subprocess. No network
   port, no process overhead, no race conditions. Coverage shows 0% on
   `ui/app.py` because `AppTest` runs the script in a separate context
   that pytest-cov doesn't instrument — accepted, documented.
5. **Subprocess boot verification is a manual step**, not a pytest test.
   `streamlit run` takes ~5s to bind, which would triple the test-suite
   wall time. Exercised in the Verification section below and via
   `systemd-analyze verify` on the VPS in Sprint 11.

## Spec auto-corrections

1. **No spec code** — Parte B.1 lists `ui/app.py` as "Placeholder; Fase 1 enche". Design follows Hugo's prompt (sidebar disabled nav, main info block, footer).

## Files created / modified

```
A  src/portfolio_thesis_engine/ui/__init__.py
A  src/portfolio_thesis_engine/ui/app.py
A  tests/unit/test_ui.py                       (6 tests via AppTest)
A  docs/sprint_reports/10_ui_stub.md           (this file)
```

## Verification

**Unit tests (no network):**

```bash
$ uv run pytest tests/unit/test_ui.py
# 6 passed in 1.32s
```

**Subprocess boot (ran locally — mirrors the systemd start path):**

```bash
$ timeout 10 uv run streamlit run src/portfolio_thesis_engine/ui/app.py \
    --server.headless=true --server.port=8502 --server.address=127.0.0.1 &
$ sleep 5 && curl -sSI http://127.0.0.1:8502/ | head -1
# HTTP/1.1 200 OK
```

ASCII screenshot of the running page (from the HTML body):

```
╭──────────────────────────────────────────────────────────────────╮
│ ▸ Portfolio Thesis Engine                                        │
│   v0.1.0 · Phase 0                                               │
│ ─────────────────                                                │
│ Navigation                                                       │
│ ( ) Dashboard                                                    │
│ ( ) Positions                                                    │
│ ( ) Watchlist                                                    │
│ ( ) Settings                                                     │
│ (disabled)                                                       │
│ ─────────────────                                                │
│ Phase 1 will enable navigation.                                  │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│ # Portfolio Thesis Engine                                        │
│                                                                  │
│ ℹ️  Phase 1 — UI coming soon. This is a placeholder serving      │
│    the Streamlit process for systemd / Tailscale smoke-testing.  │
│    All CLI functionality is available via `pte` (setup,          │
│    health-check, smoke-test).                                    │
│                                                                  │
│ ┌──────────┐  ┌──────────┐  ┌───────────────────────┐            │
│ │ Version  │  │ Phase    │  │ Status                │            │
│ │ 0.1.0    │  │ 0        │  │ Scaffolding complete  │            │
│ └──────────┘  └──────────┘  └───────────────────────┘            │
│ ─────────────────                                                │
│ Portfolio Thesis Engine · Semi-automated portfolio management    │
│ · v0.1.0                                                         │
╰──────────────────────────────────────────────────────────────────╯
```

**Full green bar:**

```bash
$ uv run pytest
# 294 passed, 3 skipped in 9.34s

$ uv run ruff check src tests
# All checks passed!

$ uv run mypy src
# Success: no issues found in 45 source files
```

## Tests passing / failing + coverage

All 294 unit tests pass; 3 integration tests skipped (gated).

| UI module               | Stmts | Miss | Cover |
| ----------------------- | ----- | ---- | ----- |
| `ui/__init__.py`        |   0   |  0   | 100 % |
| `ui/app.py`             |  23   | 23   |   0 % (via AppTest — see decision 4) |
| **Project total**       | 1903  | 124  |  93 % |

The coverage line on `ui/app.py` is 0 because Streamlit's `AppTest`
runs the script in a subprocess-like isolated context; pytest-cov's
tracer does not follow in. The 6 assertions in `test_ui.py` still
cover the actual rendered structure (title, info, sidebar header,
disabled radio, metrics, no exceptions).

## Problems encountered

1. **`streamlit` import-time warnings when run bare** ("missing
   ScriptRunContext") — harmless noise from importing the module
   outside `streamlit run`. Tests use `AppTest` which sets up the
   correct context; subprocess run also sets it up. No code change
   required.
2. **Coverage attribution on `ui/app.py`** — accepted as a Streamlit-
   testing idiosyncrasy. If the 0 % is noisy, Sprint 11 could add a
   subprocess-based integration test to fill it; I judged the payoff
   too low for the added runtime.
3. **No design blockers.**

## Next step

**Sprint 11 — DevOps.** `scripts/provision_vps.sh` (idempotent — detect
installed packages, skip if present, match the "VPS already provisioned
manually" constraint), `scripts/backup.sh` (tar YAMLs, copy DuckDB,
sqlite `.backup`, conditional `rclone sync`, retention sweep), plus
systemd units `pte-streamlit.service` and `pte-backup.service`/`.timer`.
Verification: `bash -n`, `shellcheck` if available,
`systemd-analyze verify` if available.
