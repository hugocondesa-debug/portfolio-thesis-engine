# Sprint 06 — LLM Orchestrator

**Date:** 2026-04-21
**Step (Parte K):** 6 — LLM orchestrator (Anthropic + OpenAI embeddings + cost tracking + retry + router + structured)
**Status:** ✅ Complete

---

## What was done

Built the full LLM orchestration layer that every future engine module
will route through:

- `llm/base.py` — `LLMRequest`/`LLMResponse` dataclasses, `LLMProvider` and `EmbeddingsProvider` abstract bases.
- `llm/cost_tracker.py` — thread-safe `CostTracker` with JSONL persistence, per-session totals, per-ticker cumulative reads, and a singleton lifecycle (`get_cost_tracker` / `reset_cost_tracker`).
- `llm/anthropic_provider.py` — `AnthropicProvider` wrapping the `anthropic` SDK (sync + async), pricing table (with `PTE_LLM_PRICING_JSON` override), cost computation, tool-use parsing. Dependency-injectable `sync_client` / `async_client` make tests hermetic.
- `llm/openai_provider.py` — `OpenAIEmbeddingsProvider` — embeddings only. This is what will plug into `RAGRepository` (Sprint 5 left the embedding_fn injectable).
- `llm/retry.py` — `with_retry` decorator via `tenacity`; `RETRYABLE_EXCEPTIONS` includes baseline `ConnectionError`/`TimeoutError` plus Anthropic and OpenAI SDK rate-limit / transient errors when those SDKs are importable.
- `llm/router.py` — `TaskType` StrEnum (CLASSIFICATION → haiku, ANALYSIS/EXTRACTION/NARRATIVE → sonnet, JUDGMENT → opus) + `model_for_task()`.
- `llm/structured.py` — `build_tool`, `force_tool_choice`, `structured_request`, `extract_structured` helpers for Anthropic tool-use as a JSON-schema output mechanism.
- 32 unit tests with mocked SDK clients (no network).
- 2 integration tests gated by `PTE_SMOKE_HIT_REAL_APIS=true` — one Anthropic haiku call, one OpenAI embeddings call — costing ~$0.001 in aggregate when enabled.

## Decisions taken

1. **Pricing table is overridable via `PTE_LLM_PRICING_JSON`.** Added `llm_pricing_json: str | None = None` to `Settings`. `anthropic_provider.load_pricing()` merges any override on top of hard-coded defaults. Malformed JSON silently falls back to defaults (logged separately would require the logger — deferred to avoid coupling). Partial entries (missing `input` or `output`) are ignored, not partially applied.
2. **Providers accept injected `sync_client`/`async_client`** — defaulting to real SDK clients when omitted. Tests pass `MagicMock` with `AsyncMock`-wrapped `messages.create` and `embeddings.create`; no network required, no monkeypatching of import-time state.
3. **`complete_sync` is re-entrant-safe.** When called from outside any event loop, it delegates to `asyncio.run(self.complete(...))`. When called from *inside* a running loop (e.g., a Streamlit handler, a CLI task group), it uses the **sync** SDK client directly — avoids `asyncio.run` deadlocks. Tested both paths.
4. **`LLMRequest.tool_choice`** is a separate field (not implicit in `tools`). Required for forcing a specific tool — the structured-output pattern wouldn't work otherwise because Anthropic defaults `tool_choice` to auto.
5. **`LLMResponse.stop_reason`** added beyond the spec. Knowing whether a response ended via `end_turn` vs `tool_use` vs `max_tokens` is essential for downstream retry/fallback logic.
6. **Cost tracker persists to JSONL, not SQLite.** Append-only with a single lock is simpler, more robust to process crashes (partial line is just ignored on read), and human-editable. `ticker_total()` rescans the file each call; sufficient for Phase 0 volumes.
7. **Singleton uses a lock-guarded `_tracker` module global** with a `reset_cost_tracker()` function for tests. Avoids the double-checked-locking footgun — both reads and writes go through the lock.
8. **Retry config is `max_attempts=3, wait_min=1s, wait_max=30s`** as the default. Tests drive the decorator with `wait_min=0, wait_max=0` to avoid sleeping during test runs. `reraise=True` means the original exception propagates after exhaustion, not `RetryError`.
9. **Retryable-exception collection is lazy + guarded.** Imports `anthropic` and `openai` SDK errors in `_collect_retryable_exceptions` inside `try/except ImportError`, so the module works even if one SDK is temporarily missing. Baseline `ConnectionError`/`TimeoutError` always present.
10. **Integration tests skip cleanly when the gate is off.** `pytest.mark.skipif(not settings.smoke_hit_real_apis, ...)` applied at module level via `pytestmark`. Default `PTE_SMOKE_HIT_REAL_APIS=false` (Sprint 1 decision 2) keeps CI and local runs free.

## Spec auto-corrections

1. **`LLMRequest.metadata`** — spec had `metadata: dict = None`, which is a mutable-default bug. Replaced with `field(default_factory=dict)`.
2. **`anthropic_provider` pricing** — spec wrote `Decimal(input_tokens) / Decimal("1_000_000")` with the underscore-separated literal inside a string; underscores work in int/float literals but `Decimal("1_000_000")` is valid and equals `Decimal(1000000)`. Rewrote as `Decimal("1000000")` for clarity.
3. **`anthropic_provider.complete_sync`** — spec version always delegated to `asyncio.run(self.complete(request))`. That deadlocks inside an already-running event loop (most realistic call sites). Added the loop-detection fallback to the sync client.
4. **`retry.RETRYABLE_EXCEPTIONS`** — spec left this as `(ConnectionError, TimeoutError, # add provider errors)`. Added the Anthropic and OpenAI SDK errors explicitly so retries actually fire on 429s.
5. **`cost_tracker.timestamp`** uses `datetime.now(UTC)` (Python 3.11+) — spec's `datetime.now(timezone.utc)` still works but the shorter form is what ruff prefers and what we use in the base schemas.
6. **`cost_tracker.session_total`** — spec used `sum((e.cost_usd for e in ...), Decimal("0"))` which mypy flagged with strict mode because `sum` is typed as `int`-producing. Rewrote as an explicit loop for clarity and typability.

## Files created / modified

```
A  src/portfolio_thesis_engine/llm/__init__.py
A  src/portfolio_thesis_engine/llm/base.py
A  src/portfolio_thesis_engine/llm/cost_tracker.py
A  src/portfolio_thesis_engine/llm/anthropic_provider.py
A  src/portfolio_thesis_engine/llm/openai_provider.py
A  src/portfolio_thesis_engine/llm/retry.py
A  src/portfolio_thesis_engine/llm/router.py
A  src/portfolio_thesis_engine/llm/structured.py
A  tests/unit/test_llm.py                               (32 tests, fully mocked)
A  tests/integration/test_llm_real.py                   (2 tests, gated)
M  src/portfolio_thesis_engine/shared/config.py         (+llm_pricing_json)
A  docs/sprint_reports/06_llm_orchestrator.md           (this file)
```

## Verification

```bash
$ uv run pytest
# 211 passed, 2 skipped in 6.86s
# (skipped = integration tests, gate off by default)

$ uv run ruff check src tests
# All checks passed!

$ uv run ruff format --check src tests
# all files formatted

$ uv run mypy src
# Success: no issues found in 31 source files
```

Integration-test behaviour:

```bash
# Gate off (default) — skipped:
$ uv run pytest tests/integration/
# 2 skipped

# Gate on — hits real APIs, ~$0.001 total. Requires ANTHROPIC_API_KEY +
# OPENAI_API_KEY in .env (already present per Sprint 1):
$ PTE_SMOKE_HIT_REAL_APIS=true uv run pytest tests/integration/
# (run manually; do NOT enable in CI)
```

## Tests passing / failing + coverage

All 211 unit tests pass; 2 integration tests skipped (gated).

| LLM module                   | Stmts | Miss | Cover |
| ---------------------------- | ----- | ---- | ----- |
| `llm/__init__.py`            |   0   |  0   | 100 % |
| `llm/base.py`                |  35   |  0   | 100 % |
| `llm/cost_tracker.py`        |  65   |  1   |  98 % |
| `llm/anthropic_provider.py`  |  79   |  1   |  99 % |
| `llm/openai_provider.py`     |  22   |  1   |  95 % |
| `llm/retry.py`               |  16   |  0   | 100 % |
| `llm/router.py`              |  12   |  0   | 100 % |
| `llm/structured.py`          |  12   |  0   | 100 % |
| **LLM total**                | 241   |  3   | **99 %** |
| **Project total**            | 1388  | 40   |  97 % |

Three uncovered lines are the small `# pragma: no cover` `ImportError` branches in `retry._collect_retryable_exceptions` (would only fire if SDKs were missing) and one defensive branch each in `cost_tracker` and `openai_provider`. Comfortably above the 85 % target.

## Problems encountered

1. **mypy `sum(... , Decimal("0"))` in `cost_tracker`** — stdlib's `sum` is typed to produce `int`. Pivoted to explicit loop, no `type: ignore` needed.
2. **`asyncio.run` inside a running loop deadlocks** — discovered when thinking about `complete_sync` being called from a Streamlit handler. Implemented the loop-detection fallback; added a dedicated test that runs `complete_sync` from within `asyncio.run(driver())` to prove it uses the sync client.
3. **Anthropic SDK's `RateLimitError` name clashes with `openai.RateLimitError`** — resolved by importing them under different aliases in `retry.py`.
4. **Ruff's import-sort rearranged `_DEFAULT_PRICING` imports in the test file** — autoformatter took care of it; no functional change.

## Next step

**Sprint 7 — Market Data Provider.** `market_data/base.py` with `MarketDataProvider` abstract + `MarketDataError` hierarchy (`TickerNotFoundError`, `RateLimitError`), and `market_data/fmp_provider.py` implementing `get_quote`, `get_price_history`, `get_fundamentals`, `get_key_metrics`, `search_tickers`, `validate_ticker` over `httpx.AsyncClient`. Mocked unit tests + 1 gated integration test against real FMP.
