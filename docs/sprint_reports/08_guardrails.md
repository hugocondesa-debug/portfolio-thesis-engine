# Sprint 08 — Guardrails Framework

**Date:** 2026-04-21
**Step (Parte K):** 8 — Guardrails framework
**Status:** ✅ Complete

---

## What was done

Built a minimal but complete guardrails framework that every downstream
module (extraction, valuation, portfolio) will plug checks into:

- `guardrails/base.py` — `Guardrail` abstract base + `GuardrailResult` dataclass. Every result carries ``check_id``, ``name``, ``status`` (uses the `GuardrailStatus` StrEnum from `schemas/common`), ``message``, ``blocking`` flag, and a free-form ``data`` dict.
- `guardrails/runner.py` — `GuardrailRunner` runs checks in order, catches exceptions inside `check()` and converts them to synthetic `FAIL` results (runner never crashes due to a bad guardrail), respects `stop_on_blocking_fail`, and computes `overall_status` via the documented FAIL > REVIEW > WARN > NOTA > PASS > SKIP precedence.
- `guardrails/results.py` — `AggregatedResults` dataclass + `ResultAggregator` + `ReportWriter` (text + JSON). Keeps the counting/rendering logic out of the runner.
- 25 unit tests covering all documented behaviours including exception-becomes-FAIL, blocking-stops-run, precedence matrix, aggregation, and report rendering.

## Decisions taken

1. **`GuardrailStatus` reused from `schemas/common`** — no new enum. Keeps the guardrail status vocabulary aligned with what `ValidationResults` / `GuardrailsStatus` schemas already use.
2. **Exceptions in `check()` become synthetic FAILs** with `message=f"Guardrail raised {type(e).__name__}: {e}"`. The runner must never die because a specific guardrail throws — the pipeline needs to report *all* failures, not just the first one that's an exception. When the offending guardrail is blocking, the synthetic FAIL respects `blocking=True` and short-circuits as expected.
3. **`stop_on_blocking_fail=True` is the default.** Matches the spec. Callers who want the full picture (e.g., the CLI's `--all` mode or diagnostic reports) pass `False`.
4. **`overall_status` precedence is `FAIL > REVIEW > WARN > NOTA > PASS > SKIP`.** Encoded as a priority dict; the worst result wins. Empty list returns PASS (nothing to complain about is a healthy state). Tested across every adjacent pair in a parametrized matrix.
5. **`ResultAggregator` is separate from `GuardrailRunner`.** Runner's job is to execute; aggregator's job is to count/categorise. Keeps each class small and independently testable.
6. **`AggregatedResults.blocking_failures`** contains only results with both `status == FAIL` and `blocking == True`. A non-blocking FAIL doesn't get elevated; that would lose the semantic distinction. Test `test_captures_blocking_failures_only` pins this.
7. **`ReportWriter` renders sorted status counts in descending order of count** so the reader sees the most common outcome first. Blocking failures are printed as a named section when present; details follow for the full audit trail.
8. **JSON report uses `indent=2`** and mirrors the text layout structurally. Same keys, same semantics, machine-consumable — suitable for the CLI's `--json` mode and for the Streamlit UI to render in Phase 1.

## Spec auto-corrections

1. **`overall_status` priority dict key order** — spec had `FAIL=5, REVIEW=4, WARN=3, NOTA=2, PASS=1, SKIP=0`; matched exactly. No change needed.
2. **`GuardrailRunner.__init__` signature** — spec takes `guardrails: list[Guardrail]`. Kept identical.
3. **Missing parametrized precedence test** — spec showed one test (`test_runner_executes_guardrails`). Expanded to a full parametrized matrix so regressions in priority ordering get caught automatically.
4. **No `results.py` in spec outline** — Hugo's Batch 3 prompt asked for `ResultAggregator` + `ReportWriter`. Added under `guardrails/results.py` to keep the runner focused.

## Files created / modified

```
A  src/portfolio_thesis_engine/guardrails/__init__.py
A  src/portfolio_thesis_engine/guardrails/base.py
A  src/portfolio_thesis_engine/guardrails/runner.py
A  src/portfolio_thesis_engine/guardrails/results.py
A  tests/unit/test_guardrails.py                  (25 tests)
A  docs/sprint_reports/08_guardrails.md           (this file)
```

## Verification

```bash
$ uv run pytest
# 254 passed, 3 skipped in 7.21s

$ uv run ruff check src tests && uv run ruff format --check src tests
# All checks passed! / all files formatted

$ uv run mypy src
# Success: no issues found in 38 source files
```

## Tests passing / failing + coverage

All 254 unit tests pass; 3 integration tests skipped (gated).

| guardrails module             | Stmts | Miss | Cover |
| ----------------------------- | ----- | ---- | ----- |
| `guardrails/__init__.py`      |   0   |  0   | 100 % |
| `guardrails/base.py`          |  18   |  0   | 100 % |
| `guardrails/runner.py`        |  18   |  0   | 100 % |
| `guardrails/results.py`       |  38   |  0   | 100 % |
| **guardrails total**          |  74   |  0   | **100 %** |
| **Project total**             | 1577  | 46   |  97 % |

Guardrails is the first fully-covered module of the engine. Well above the
85% target.

## Problems encountered

None. Ruff flagged one import-sort warning in the test file that `ruff --fix`
resolved. No design decisions blocked in-batch.

## Next step

**Batch 3 complete.** All of Sprint 6 (LLM orchestrator), Sprint 7 (market
data), and Sprint 8 (guardrails) landed green. Total project state:

- 254 unit tests, 3 integration tests (gated), 97% overall coverage
- 13 concrete modules across `shared/`, `schemas/`, `storage/`, `llm/`, `market_data/`, `guardrails/`
- 14 commits on `main`, all pushed to origin
- ruff + mypy strict clean throughout

Sprint 9 — CLI (`cli/app.py`, `setup_cmd.py`, `health_cmd.py`, `smoke_cmd.py`) is
next, pending Hugo's validation.
