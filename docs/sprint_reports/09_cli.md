# Sprint 09 — CLI (`pte setup` / `health-check` / `smoke-test`)

**Date:** 2026-04-21
**Step (Parte K):** 9 — CLI
**Status:** ✅ Complete

---

## What was done

Wired up the Typer-based ``pte`` command line installed by the
``[project.scripts]`` entry in ``pyproject.toml`` (Sprint 1):

- `cli/app.py` — top-level Typer app, registers the three sub-commands.
- `cli/setup_cmd.py` — `pte setup` creates the data tree idempotently, writes `.gitkeep` in empty directories, validates Python 3.12, and warns (non-fatally) when `.env` is absent.
- `cli/health_cmd.py` — `pte health-check` renders a Rich status table across Python, API keys, data/backup directories, DuckDB/SQLite files, and Tailscale. Best-effort Tailscale probe — absent CLI is reported as optional, not a failure.
- `cli/smoke_cmd.py` — `pte smoke-test` runs four mocked checks by default (storage round-trip including dotted-ticker edge case, guardrail runner including a crashing check, Anthropic mock, OpenAI embeddings mock). With ``PTE_SMOKE_HIT_REAL_APIS=true`` it additionally issues one minimal real-API call per provider (Anthropic classification model, OpenAI embeddings, FMP quote for ``AAPL``) and reports total real-API cost.
- 9 unit tests via ``typer.testing.CliRunner`` — filesystem effects isolated via `monkeypatch` on `settings.data_dir` / `settings.backup_dir`.

## Decisions taken

1. **`pte setup` uses `settings.data_dir` as the root** rather than `cwd / "data"`. `.env` already points the default at `~/workspace/portfolio-thesis-engine/data`; keeping the single source of truth means running `pte setup` from any cwd (including systemd-managed contexts) lands in the same place.
2. **`_ensure_dir` returns True on creation, False on existence** so the report accurately distinguishes first-run from re-run. Same for `_touch_gitkeep`. Clean, verifiable idempotency.
3. **`.gitkeep` is only created for directories currently empty.** A populated directory doesn't need one, and dropping one into an in-use folder is noise. The helper skips hidden-prefixed entries so an existing `.gitkeep` doesn't itself count as "non-empty".
4. **Setup warns but doesn't fail on missing `.env`.** The data-tree scaffolding is useful even before keys are wired; failing would force users to fill in dummy keys just to run `setup`. Required keys are surfaced loudly in `health-check` instead (as `MISSING`), not in `setup`.
5. **Health-check uses three distinct statuses:** `OK` (green), `WARN` (yellow, for directories that will be created by `pte setup`), and `OPTIONAL` (dim dash, for DB files created on first use). Missing API keys show `MISSING` (red) — but since the config layer guarantees they're loaded (Sprint 2 makes them required), this branch fires only when someone overrides the secret with an empty string at run-time.
6. **Tailscale status is best-effort.** No CLI → `OPTIONAL`. Non-zero exit → `WARN` with the stderr tail. Timeout (5s) → `WARN`. Never crashes the health check.
7. **Smoke-test runs all four mocked checks unconditionally** even in real-API mode; real-API checks run in addition, not instead. Makes the cost-vs-no-cost difference explicit in the output table.
8. **Real-API cost attribution is provider-specific.** Anthropic cost comes from `LLMResponse.cost_usd` (Sprint 6 pricing table). OpenAI and FMP cost is reported as `—` because the former is negligible for one embed call and the latter is a flat-fee subscription, not per-call.
9. **Smoke checks catch all exceptions per check and render as FAIL.** A bad provider doesn't mask the other three. Exit code reflects whether *any* check failed.
10. **Typer `CliRunner` test isolation via `monkeypatch`** — patching `settings.data_dir` means tests never touch the real data directory even when they call `pte setup` under `runner.invoke`. Each test is a function-scoped `tmp_path`.

## Spec auto-corrections

1. **Spec H.3 health-check** checked `settings.data_dir.exists() or settings.data_dir.parent.exists()` (OK only if the directory or its parent exists). Simplified to "exists → OK, absent → WARN (nudge to run setup)" — the parent-check was an artifact of the spec's path-defaults wording.
2. **Spec H.3 smoke-test** had stubs that raised `NotImplementedError`. Replaced with the real mocked-provider flow (Anthropic/OpenAI/FMP smoke checks). Hugo's prompt was explicit: mocked by default, real-API calls gated.
3. **`spec.setup_cmd`** not present — spec had `pte setup` mentioned but no code. Implemented per Hugo's prompt specifics (data tree layout, idempotency, warnings).

## Files created / modified

```
A  src/portfolio_thesis_engine/cli/__init__.py
A  src/portfolio_thesis_engine/cli/app.py                (Typer app + registrations)
A  src/portfolio_thesis_engine/cli/setup_cmd.py          (data tree scaffolding)
A  src/portfolio_thesis_engine/cli/health_cmd.py         (Rich table status)
A  src/portfolio_thesis_engine/cli/smoke_cmd.py          (4 mocked + 3 gated real-API checks)
A  tests/unit/test_cli.py                                (9 tests via CliRunner)
A  docs/sprint_reports/09_cli.md                         (this file)
```

## Verification

```bash
$ uv run pte --help
# Usage: pte [OPTIONS] COMMAND [ARGS]...
# Portfolio Thesis Engine CLI
# Commands: setup, health-check, smoke-test

$ uv run pte setup                        # first run
✓ Python 3.12.3 OK
✓ .env present
Directories created: 7 (data + backup + 5 subdirs)
.gitkeep files created: 6
Setup complete.

$ uv run pte setup                        # re-run → idempotent
✓ Python 3.12.3 OK
✓ .env present
All directories already present.
Setup complete.

$ uv run pte health-check
# Rich table: Python OK, API keys OK, dirs OK, DBs OPTIONAL,
#             Tailscale OK (online)
All required components OK.

$ uv run pte smoke-test
# Rich table:
#   Storage roundtrip  PASS  save+get+delete symmetric
#   Guardrail runner   PASS  3 checks; runner converted crash→FAIL
#   LLM (mocked)       PASS  Anthropic mock returned 'ok'
#   Embeddings (mocked) PASS OpenAI mock returned 1 vector
# 4/4 tests passed.

$ uv run pytest
# 288 passed, 3 skipped in 8.15s

$ uv run ruff check src tests
# All checks passed!

$ uv run mypy src
# Success: no issues found in 43 source files
```

Real-API smoke mode (run manually with API keys + ``PTE_SMOKE_HIT_REAL_APIS=true``):

```bash
$ PTE_SMOKE_HIT_REAL_APIS=true uv run pte smoke-test
# Adds 3 more rows (Anthropic / OpenAI / FMP), reports total cost.
```

## Tests passing / failing + coverage

All 288 unit tests pass; 3 integration tests skipped (gate off).

| CLI module                | Stmts | Miss | Cover |
| ------------------------- | ----- | ---- | ----- |
| `cli/__init__.py`         |   0   |  0   | 100 % |
| `cli/app.py`              |   8   |  0   | 100 % |
| `cli/setup_cmd.py`        |  49   |  3   |  94 % |
| `cli/health_cmd.py`       |  66   |  5   |  92 % |
| `cli/smoke_cmd.py`        | 154   |  9   |  94 % |
| **CLI total**             | 277   | 17   | **94 %** |
| **Project total**         | 1880  | 101  |  95 % |

Uncovered lines are all defensive branches: the Python-version-too-old
`SystemExit(1)` path in `setup`, the Tailscale timeout/OSError handlers,
and the real-API checks in `smoke_cmd` (covered by the gated integration
suite, not unit tests). Above the 85 % target.

## Problems encountered

1. **Typer `CliRunner` swallows stdout colour codes by default.** Not a real problem — tests assert on substrings that are present regardless of colour. Noted for future reference.
2. **`settings.data_dir` is an absolute `Path` populated at import time** — so cwd-based "isolation" via `tempfile.TemporaryDirectory()` doesn't help. Tests must monkey-patch the attribute directly (autouse fixture does exactly that).
3. **Initial `pte setup` ran against the real `~/workspace/.../data` directory** because I forgot to isolate it before running manually. Not destructive (the command is idempotent and only creates directories) but noted as a workflow detail.
4. **No design blockers encountered.** All decisions were mechanical translations of Hugo's prompt.

## Next step

**Sprint 10 — UI stub.** A minimal Streamlit placeholder (`ui/app.py`) with sidebar navigation (disabled), a main panel announcing "Phase 1 — UI coming soon", and a footer. Start-up verification: `streamlit run --server.headless true src/portfolio_thesis_engine/ui/app.py` must return exit code 0 (binding to a port, then shut down cleanly).
