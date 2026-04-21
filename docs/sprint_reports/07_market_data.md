# Sprint 07 — Market Data Provider (FMP)

**Date:** 2026-04-21
**Step (Parte K):** 7 — Market data provider
**Status:** ✅ Complete

---

## What was done

Built `market_data/` package with the abstract interface and the FMP
(Financial Modeling Prep) concrete implementation:

- `market_data/base.py` — `MarketDataProvider` ABC with six abstract methods (`get_quote`, `get_price_history`, `get_fundamentals`, `get_key_metrics`, `search_tickers`, `validate_ticker`). `MarketDataError` / `TickerNotFoundError` / `RateLimitError` typed exceptions, re-exported from and rooted in `shared/exceptions.MarketDataError` so catching the shared root still catches provider-raised errors.
- `market_data/fmp_provider.py` — `FMPProvider` over `httpx.AsyncClient`. Injectable client (for tests), owned-vs-external client ref-counted for cleanup, async context manager, 429/404/5xx/timeout/malformed-JSON mapped to typed exceptions.
- 18 unit tests using `httpx.MockTransport` — no network.
- 1 integration test gated by `PTE_SMOKE_HIT_REAL_APIS=true` that issues exactly one `get_quote("AAPL")` call.

## Decisions taken

1. **Typed exceptions root at `shared/exceptions.MarketDataError`** (added in Sprint 2). `market_data.base.MarketDataError` subclasses the shared root, and `TickerNotFoundError` / `RateLimitError` subclass the provider-local one. This gives callers three equivalent catch points (shared root, provider root, specific error) with one inheritance chain.
2. **Injectable `httpx.AsyncClient`** — caller can pass a preconfigured client (proxies, timeouts, retries); if omitted, the provider creates one bound to `BASE_URL`. The provider tracks `_owns_client` so `aclose()` only closes what it created.
3. **Async context manager (`__aenter__` / `__aexit__`)** — callers can do `async with FMPProvider() as fmp: ...` and get clean shutdown even on exception.
4. **Single private `_get()` method** centralises error mapping. Every endpoint routes through it, so adding a new call site doesn't forget 429/404/timeout handling.
5. **`get_fundamentals` bundles three FMP endpoints** (IS + BS + CF) into one call. Downstream code never needs to know they're three requests upstream; if all three return empty, it raises `TickerNotFoundError` (a strong signal the ticker isn't covered).
6. **`get_price_history` raises `TickerNotFoundError` if the response has neither `historical` entries nor a `symbol` field** — FMP returns `{}` for unknown tickers on this endpoint.
7. **`validate_ticker` is pure regex**, doesn't hit the network. Accepts `A-Z`, `0-9`, `.`, `_`, `-`, up to 20 chars. Covers the known ticker forms the engine will see (`AAPL`, `BRK.B`, `ASML.AS`, `9988.HK`, `TEST-A`).
8. **Integration test gated identically to Sprint 6** — `settings.smoke_hit_real_apis` drives `pytest.mark.skipif`. One call, `get_quote("AAPL")`, costs effectively nothing on FMP's starter tier.
9. **No retry integration this sprint.** Retrying provider calls is the caller's concern (they know the call's idempotency / cost). The `llm/retry.with_retry` decorator from Sprint 6 works here too; can be layered explicitly at call sites that want it.

## Spec auto-corrections

1. **Spec F.2 skeleton only implemented `get_quote` + `get_price_history`.** Extended to all six methods of the abstract base as required — otherwise `FMPProvider()` would fail to instantiate due to unimplemented abstractmethods.
2. **Spec's `api_key = settings.fmp_api_key`** would store a `SecretStr` instance and then pass it as-is to HTTP queries. Corrected to `settings.secret("fmp_api_key")` to unwrap.
3. **Spec's `response.raise_for_status()`** wraps every non-2xx uniformly as `HTTPStatusError`. Replaced with explicit 429/404/other branching so callers get typed exceptions.
4. **Spec used `httpx.AsyncClient(timeout=30.0)` without `base_url`** — every call path then concatenated `BASE_URL + "/quote/..."`. Moved `base_url` into the client; paths stay relative which simplifies the mock transport setup in tests.

## Files created / modified

```
A  src/portfolio_thesis_engine/market_data/__init__.py
A  src/portfolio_thesis_engine/market_data/base.py
A  src/portfolio_thesis_engine/market_data/fmp_provider.py
A  tests/unit/test_market_data.py                       (18 tests, httpx.MockTransport)
A  tests/integration/test_market_data_real.py           (1 test, gated)
A  docs/sprint_reports/07_market_data.md                (this file)
```

## Verification

```bash
$ uv run pytest
# 229 passed, 3 skipped in 7.23s
# (skipped = integration tests across llm + market_data, gate off)

$ uv run ruff check src tests && uv run ruff format --check src tests
# All checks passed! / 53 files already formatted

$ uv run mypy src
# Success: no issues found in 34 source files
```

Integration-test behaviour:

```bash
# Gate off (default):
$ uv run pytest tests/integration/test_market_data_real.py
# 1 skipped

# Gate on — real FMP call:
$ PTE_SMOKE_HIT_REAL_APIS=true uv run pytest tests/integration/test_market_data_real.py
# Hits financialmodelingprep.com; free tier call, rate-limited to 250/day
```

## Tests passing / failing + coverage

All 229 unit tests pass; 3 integration tests skipped (gated).

| market_data module              | Stmts | Miss | Cover |
| ------------------------------- | ----- | ---- | ----- |
| `market_data/__init__.py`       |   0   |  0   | 100 % |
| `market_data/base.py`           |  24   |  0   | 100 % |
| `market_data/fmp_provider.py`   |  70   |  2   |  97 % |
| **market_data total**           |  94   |  2   | **98 %** |
| **Project total**               | 1482  | 46   |  97 % |

Two uncovered lines are the `__aenter__`/`__aexit__` fallbacks when the
provider creates its own client (tests always inject one). Comfortably
above the 85 % target.

## Problems encountered

1. **mypy `no-any-return` on `get_quote` returning `data[0]`** — `_get` is typed as `-> Any`, so `data[0]` propagates Any into a function declared as returning `dict[str, Any]`. Resolved by assigning to a typed local (`first: dict[str, Any] = data[0]`) before returning; avoids a `cast` call.
2. **`httpx.MockTransport` with `base_url`** — need to set `base_url` on the `AsyncClient`, not the transport. Fixtures build the client correctly; tests call with relative paths.
3. **Edge: `search_tickers` with an unexpected response shape** — returns `[]` rather than raising. Spec said "search"; failing hard on a formatted dict would be overly strict for a search endpoint. Documented in test (`test_unexpected_shape_returns_empty_list`).

## Next step

**Sprint 8 — Guardrails framework.** `guardrails/base.py` with `Guardrail` ABC and `GuardrailResult` dataclass; `guardrails/runner.py` with `GuardrailRunner` (respects `stop_on_blocking_fail`, exceptions in `check()` become `FAIL` not process kills, overall status uses FAIL > REVIEW > WARN > NOTA > PASS > SKIP precedence); `guardrails/results.py` with `ResultAggregator` / `ReportWriter` for text/JSON output. Tests include trivial pass/fail/warn/blocking-fail fixtures.
