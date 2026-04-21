# Sprint 02 — Shared utilities

**Date:** 2026-04-21
**Step (Parte K):** 2 — Shared utilities
**Status:** ✅ Complete

---

## What was done

Implemented the four modules under `src/portfolio_thesis_engine/shared/` that the rest of Phase 0 depends on: settings loading, structured logging, custom exception hierarchy, and generic type aliases. Added the first unit tests of the project and scaffolded `tests/unit/` and `tests/integration/` per Parte B.1.

Also landed a fix to Sprint 1 (issue surfaced by Hugo mid-sprint): dev dependencies were disappearing on plain `uv sync` because they lived under `[project.optional-dependencies]`. Converted to PEP 735 `[dependency-groups]` so the default behaviour is "install dev tooling".

## Decisions taken

1. **PEP 735 `[dependency-groups]` instead of `[project.optional-dependencies]`** (Sprint 1 fix). `uv sync` without flags now installs `pytest`, `ruff`, `mypy`, `ipython`, etc.; `uv sync --no-dev` excludes them for production. Deviates from spec B.2 but strictly better dev ergonomics — spec wrote the older idiom.
2. **PEP 695 `type` statements** in `shared/types.py` rather than `TypeAlias` annotations. Required to satisfy `ruff UP040` on Python 3.12. Tests use `Alias.__value__ is <underlying>` to assert runtime shape since `type X = Y` creates a `TypeAliasType` instance (not `Y` itself).
3. **Generic-only aliases in `shared/types.py`**. The spec tree line "Type aliases, enums" is ambiguous — enums like `Currency`, `Profile`, `ConvictionLevel`, `GuardrailStatus`, `ConfidenceTag` belong to `schemas/common.py` per Parte C.1, and moving them to `shared/` would create a schemas→shared→schemas import cycle. So `shared/types.py` only holds truly cross-cutting aliases: `Ticker`, `ISODate`, `UnixTimestamp`, and `Json{Value,Dict,List}` for generic payload passing.
4. **Exception hierarchy shape.** The spec only says "custom exception hierarchy" without naming subclasses. Chose a domain-aligned tree rooted at `PTEError`: `ConfigError`, `SchemaValidationError`, `StorageError` (+ `NotFoundError`, `VersionConflictError`), `LLMError` (+ `RateLimitError`, `CostLimitExceededError`, `ModelNotFoundError`), `MarketDataError`, `GuardrailError`. `GuardrailError` is reserved for infra failures; regular FAIL/WARN verdicts remain carried by `GuardrailResult` objects, not by raises.
5. **Config singleton kept as module-level `settings = Settings()`** per spec H.1. Means `.env` (or required env vars) must exist at import time. Tests use `Settings(_env_file=None)` + `monkeypatch.setenv(...)` for isolation and never go through the singleton. Added a `# type: ignore[call-arg]` on the singleton line with an inline comment — mypy strict can't see that env vars satisfy the required fields.
6. **Added `smoke_hit_real_apis: bool = False` to `Settings`** matching the `PTE_SMOKE_HIT_REAL_APIS` env var already in `.env.example` from Sprint 1 decision 2. Keeps config contract and env template in sync ahead of Sprint 9 needing it.
7. **`setup_logging()` is idempotent.** Added `force=True` to `logging.basicConfig` so repeated calls reconfigure cleanly (structlog already caches). Unit-tested this.
8. **`get_logger()` return annotated as `Any`.** structlog's lazy proxy is not `stdlib.BoundLogger` until first bind; annotating the proxy precisely would require an untrue cast. Pragmatism wins, documented in the docstring.

## Spec auto-corrections

1. **`pyproject.toml` dev dependency group.** Spec B.2 used `[project.optional-dependencies].dev`; this caused `uv sync` (no flags) to uninstall dev tools. Converted to `[dependency-groups].dev` (PEP 735) — see commit `3278b10` (`fix(sprint1): ensure dev deps installed by default via uv sync`).
2. **Type-alias syntax in `shared/types.py`.** Spec-style `X: TypeAlias = ...` trips `ruff UP040` on 3.12. Using PEP 695 `type X = ...` instead.
3. **Typo tolerance check on spec H.1/H.2 code.** Spec samples compiled as-is; no typos fixed this sprint.

## Files created / modified

```
M  pyproject.toml                                   (Sprint 1 fix: PEP 735 groups)
M  uv.lock                                          (regenerated)
A  src/portfolio_thesis_engine/shared/__init__.py
A  src/portfolio_thesis_engine/shared/config.py     (Settings + singleton)
A  src/portfolio_thesis_engine/shared/logging_.py   (structlog setup + get_logger)
A  src/portfolio_thesis_engine/shared/exceptions.py (PTEError hierarchy)
A  src/portfolio_thesis_engine/shared/types.py      (generic PEP 695 aliases)
A  tests/unit/__init__.py
A  tests/integration/__init__.py
A  tests/unit/test_config.py
A  tests/unit/test_logging.py
A  tests/unit/test_exceptions.py
A  tests/unit/test_types.py
A  docs/sprint_reports/02_shared_utilities.md       (this file)
```

## Verification

```bash
$ uv sync
# pytest, ruff, mypy, etc. reinstated from dependency-groups.dev

$ uv sync --no-dev
# dev tooling correctly uninstalled — production-mode path validated

$ uv run pytest
# 28 passed in 0.34s

$ uv run ruff check src tests
# All checks passed!

$ uv run ruff format --check src tests
# 13 files already formatted

$ uv run mypy src
# Success: no issues found in 6 source files
```

## Tests passing / failing + coverage

All 28 unit tests pass. Coverage for Sprint 2 modules:

| Module                  | Stmts | Miss | Cover |
| ----------------------- | ----- | ---- | ----- |
| `shared/__init__.py`    | 0     | 0    | 100 % |
| `shared/config.py`      | 27    | 0    | 100 % |
| `shared/exceptions.py`  | 12    | 0    | 100 % |
| `shared/logging_.py`    | 14    | 1    |  93 % |
| `shared/types.py`       | 9     | 0    | 100 % |
| **Total (Sprint 2)**    | 62    | 1    |  98 % |

The one uncovered line in `logging_.py` is the `ConsoleRenderer` branch when `settings.log_format == "console"` — default path is "console" at import time, but the test that explicitly validates the `"json"` branch cannot easily cover both without full structlog reconfiguration gymnastics. Accepted at 98%, well above the 80% target.

## Problems encountered

1. **mypy strict rejected `Settings()` call** — all aliased fields are `Field(...)` required, mypy treats them as kwargs missing at the call site. Resolved with a targeted `# type: ignore[call-arg]` on the singleton line with an explanatory comment. Did not loosen strict mode.
2. **`ruff UP040` fired** on `TypeAlias`-annotated aliases in `shared/types.py`. Switched to PEP 695 `type` syntax (see decision 2). Required adjusting the `test_types.py` identity assertions to inspect `.__value__`.
3. **No bash-level blockers** — `uv sync` was fast and deterministic after the pyproject change.

## Next step

**Sprint 3 — Pydantic schemas (batch).** Implement `schemas/common.py`, `schemas/base.py`, `schemas/company.py`, `schemas/valuation.py`, `schemas/position.py`, `schemas/peer.py`, `schemas/market_context.py`, `schemas/ficha.py` per Parte C of the spec, plus exhaustive unit tests (instantiation, validation, YAML roundtrip) with fixtures in `tests/conftest.py`. Coverage target ≥90 % on schemas.
