# Sprint 15 — FMP `/stable/` refactor + yfinance alternative provider

**Date:** 2026-04-21
**Step (Parte K):** post-Fase 0 patch
**Status:** ✅ Complete

---

## What was done

Two overlapping changes delivered in one sprint:

1. **Refactored `FMPProvider`** from the deprecated `/api/v3/` endpoints to
   FMP's `/stable/` API. Legacy paths return `403 "Legacy Endpoint"` to
   new subscribers since Aug 2025; the stable API uses query-parameter
   symbols (`?symbol=AAPL`) and — in the case of historical prices —
   returns a flat list instead of the legacy wrapped shape.
2. **Added `YFinanceProvider`** as a free, polymorphic alternative
   implementation of `MarketDataProvider`. Wraps the synchronous
   `yfinance` library with `asyncio.to_thread` so it fits the existing
   async contract. Useful for cross-checks and for tickers that FMP
   doesn't cover.

## Decisions taken

### FMP `/stable/` refactor

1. **Endpoint probing before coding.** Before touching `fmp_provider.py`
   I hit every intended endpoint live against the real API with the
   configured key, capturing the exact response shape per endpoint. Two
   shape changes surfaced:
   - `/historical-price-eod/full` returns a flat list of rows directly
     (legacy returned `{"symbol": ..., "historical": [...]}`). The
     provider's `get_price_history` now returns `list(data)` directly.
   - Unknown tickers return `200 + []` (not 404). The provider detects
     empty-list responses and raises `TickerNotFoundError`.
2. **`/search-name` chosen over `/search-symbol`.** The stable API splits
   the old combined `/search` into two endpoints. `/search-name` matches
   company names (what human searches use); `/search-symbol` matches
   ticker prefixes. Route to `/search-name` — callers who already have a
   ticker should call `get_quote` directly.
3. **`401/403` mapped to `MarketDataError`** (not `TickerNotFoundError`).
   Both indicate auth failure. The error body is parsed via
   `_extract_error_message()` which understands FMP's
   `{"Error Message": "..."}` shape and surfaces the upstream message
   verbatim — makes diagnosing "Invalid API key" vs "Legacy endpoint"
   trivial without needing to look at network tracing.
4. **Added `get_profile(ticker)`.** Not part of the abstract base, but
   extraction pipelines benefit from company profile metadata (industry,
   sector, currency, country). Spec Parte F suggested "company-outlook or
   /profile"; I used `/profile` after confirming it returns the shape we
   want.
5. **Same injectable-client pattern as before.** Tests continue to use
   `httpx.MockTransport`. No change to the public constructor signature —
   this refactor is backwards-compatible for callers.

### yfinance provider

6. **Sync library + `asyncio.to_thread` wrapper.** `yfinance` is
   synchronous and does network I/O under the hood. Each method wraps
   the blocking call in `asyncio.to_thread` so the provider composes with
   the rest of our async pipeline without spawning threads per request
   (the thread-pool is reused). No threading in unit tests — `pytest-asyncio`
   drives them.
7. **`validate_ticker` regex is slightly wider than FMP's** to accept
   Yahoo-style index tickers (`^GSPC`) and FX pairs (`EURUSD=X`). Real
   tickers from both providers still pass both regexes.
8. **`get_key_metrics` derives a single record from `Ticker.info`**.
   yfinance exposes a ~200-key `info` dict; the provider projects the
   usual valuation multiples (trailingPE, forwardPE, priceToBook,
   enterpriseToEbitda, dividendYield, beta). Returns `{"records": [record]}`
   to match FMP's shape so call sites can treat the two providers
   uniformly.
9. **`get_fundamentals` transposes the DataFrame.** yfinance returns
   periods as columns and line items as rows. `_df_to_records()`
   transposes into `[{"period": ISO, item1: v1, item2: v2, ...}, ...]`,
   skipping NaN cells. Shape matches FMP's `list[period_dict]` so the
   contract stays polymorphic.
10. **Limitations documented in module docstring.** Scraping-based, no
    official API support, implicit rate limits, use at own risk. Not a
    replacement for FMP — an alternative for cross-checks and niche
    coverage.
11. **Unit tests patch `yf` module-level** rather than individual calls.
    `with patch("...yfinance_provider.yf") as yf:` gives each test full
    control of `Ticker`, `Search`, etc. No network access from the unit
    suite.
12. **mypy override for `yfinance`.** The library ships no stubs or
    `py.typed` marker. Added `ignore_missing_imports = true` for just
    that module via `[[tool.mypy.overrides]]` in `pyproject.toml`;
    strict mode everywhere else is preserved.

## Spec auto-corrections

1. **Spec Parte F examples used `/api/v3/`** — inherited from legacy
   FMP docs; replaced throughout with `/stable/`.
2. **Spec's `search_tickers` invoked `/search?query=...&exchange=`** —
   the `exchange` param doesn't exist on the stable `/search-name`
   endpoint. Dropped it.
3. **Spec had no yfinance reference**; it's an additive capability per
   Hugo's patch request.

## Files created / modified

```
M  src/portfolio_thesis_engine/market_data/fmp_provider.py  (stable API)
A  src/portfolio_thesis_engine/market_data/yfinance_provider.py
M  src/portfolio_thesis_engine/cli/smoke_cmd.py             (+yfinance check)
M  tests/unit/test_market_data.py                           (new shapes + errors)
A  tests/unit/test_yfinance_provider.py                     (20 tests)
M  tests/integration/test_market_data_real.py               (+yfinance gated test)
M  docs/architecture.md                                     (+providers table)
M  docs/schemas.md                                          (unchanged)
M  README.md                                                (+providers table)
M  pyproject.toml                                           (+yfinance dep, +mypy override)
A  docs/sprint_reports/15_fmp_fix_plus_yfinance.md          (this file)
```

## Verification

### Live-API probe before refactor

Probed every planned `/stable/` endpoint against the real API first;
only then wrote code against the confirmed shapes:

```
200 /quote                         list[1] keys=['symbol', 'name', 'price', 'changePercentage', ...]
200 /historical-price-eod/full     list[1254] keys=['symbol', 'date', 'open', 'high', 'low', 'close']
200 /profile                       list[1] keys=['symbol', 'price', 'marketCap', 'beta', ...]
200 /key-metrics                   list[2] keys=['symbol', 'date', 'fiscalYear', 'period', ...]
200 /income-statement              list[2] keys=['date', 'symbol', 'reportedCurrency', 'cik', ...]
200 /balance-sheet-statement       list[2]
200 /cash-flow-statement           list[2]
200 /search-name                   list[36] keys=['symbol', 'name', 'currency', 'exchangeFullName', ...]
```

Unknown ticker → `200 []`; bad API key → `401 {"Error Message": "Invalid API KEY."}`.

### Live end-to-end of both providers

```
FMPProvider (stable):
  get_quote         OK  symbol=AAPL price=273.05
  get_price_history OK  rows=6 first_date=2025-01-10
  get_profile       OK  symbol=AAPL currency=USD
  get_fundamentals  OK  IS=5 BS=5 CF=5
  get_key_metrics   OK  records=5
  search_tickers    OK  hits=20 top3=['APC.DE', 'AAPL.NE', 'AAPL.DE']
  unknown ticker    OK  raises TickerNotFoundError

YFinanceProvider:
  get_quote         OK  symbol=AAPL price=273.05 currency=USD
  get_price_history OK  rows=5 first='2025-01-02' close=243.85
  get_key_metrics   OK  trailingPE=34.607098
  search_tickers    OK  hits=5 top3=[('AAPL','Apple Inc.'), ('APLE','Apple Hospitality REIT'), ...]
  get_fundamentals  OK  IS=5 BS=5 CF=5
```

### Full-suite green bar

```
$ uv run pytest
# 352 passed, 4 skipped in 11.35s

$ uv run ruff check src tests
# All checks passed!

$ uv run mypy src
# Success: no issues found in 46 source files
```

### `pte smoke-test` with real APIs

```
$ PTE_SMOKE_HIT_REAL_APIS=true uv run pte smoke-test
Storage roundtrip           PASS  save+get+delete symmetric
Guardrail runner            PASS  3 checks; runner converted crash→FAIL
LLM (mocked)                PASS  Anthropic mock returned 'ok'
Embeddings (mocked)         PASS  OpenAI mock returned 1 vector
Anthropic (real API)        PASS  20+4 tokens                     0.000032
OpenAI embeddings (real API) PASS dim=1536                        —
FMP stable (real API)       PASS  AAPL price=273.05               —
yfinance (real API)         PASS  AAPL price=273.05 currency=USD  —

8/8 tests passed.
Total real-API cost: $0.000032
```

Hugo's target was 7/7 (mocked+real); this delivers 8/8 because
`yfinance` is now a first-class real-API check too.

## Tests passing / failing + coverage

All 352 unit tests pass; 4 integration tests skipped (gated).

| market_data module                   | Stmts | Miss | Cover |
| ------------------------------------ | ----- | ---- | ----- |
| `market_data/__init__.py`            |   0   |  0   | 100 % |
| `market_data/base.py`                |  20   |  0   | 100 % |
| `market_data/fmp_provider.py`        |  83   |  4   |  95 % |
| `market_data/yfinance_provider.py`   |  92   |  7   |  92 % |
| **market_data total**                | 195   | 11   | **94 %** |
| **Project total**                    | 2026  | 142  |  93 % |

Uncovered lines are `__aenter__` / `__aexit__` context-manager branches
when tests inject pre-built clients and a few defensive `except Exception`
arms for yfinance edge cases that only a real Yahoo outage would trigger.
Above the 85 % sprint target.

## Problems encountered

1. **yfinance `info` returns a `symbol` key but no `price` for some
   halted tickers** — covered by an explicit `price is None` check in
   `get_quote` that raises `TickerNotFoundError`. Test pins this
   branch.
2. **FMP's `/search-name` rankings are fuzzy** (searching "apple" puts
   APC.DE and AAPL.NE ahead of AAPL itself). Not a defect — the endpoint
   is name-match ordered by some internal signal. Kept the response
   as-is; callers can filter by exchange / currency if they need
   stricter ordering.
3. **mypy strict + yfinance (no stubs)** needed an override in
   `pyproject.toml`. Scoped to just the `yfinance` module so strict
   typing applies everywhere else in our code.

## Next step

Phase 1 — Portfolio System MVP. Build the parser of forecast outputs,
dashboard, scenario tuner, ficha viewer. Market-data layer is now
swappable between FMP (paid, primary) and yfinance (free, alternative)
so the UI layer can offer per-ticker source selection or auto-fallback.
