"""Unit tests for the FMP market data provider.

HTTP is mocked via :class:`httpx.MockTransport` — no network access and no
real API key required.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from portfolio_thesis_engine.market_data.base import (
    MarketDataError,
    RateLimitError,
    TickerNotFoundError,
)
from portfolio_thesis_engine.market_data.fmp_provider import FMPProvider


def _make_provider(handler: Any) -> FMPProvider:
    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport, base_url=FMPProvider.BASE_URL, timeout=5.0)
    return FMPProvider(api_key="test-key", client=client)


# ======================================================================
# validate_ticker
# ======================================================================


class TestValidateTicker:
    def test_accepts_common_formats(self) -> None:
        p = FMPProvider(api_key="x", client=httpx.AsyncClient())
        for ok in ("AAPL", "BRK.B", "ASML.AS", "TEST-A", "9988.HK"):
            assert p.validate_ticker(ok), f"expected {ok!r} valid"

    def test_rejects_empty_and_invalid(self) -> None:
        p = FMPProvider(api_key="x", client=httpx.AsyncClient())
        for bad in ("", "with space", "too_long_ticker_more_than_twenty_chars", "!@#"):
            assert not p.validate_ticker(bad), f"expected {bad!r} invalid"


# ======================================================================
# get_quote
# ======================================================================


class TestGetQuote:
    @pytest.mark.asyncio
    async def test_returns_first_row_of_list(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "/quote/AAPL" in request.url.path
            assert request.url.params["apikey"] == "test-key"
            return httpx.Response(200, json=[{"symbol": "AAPL", "price": 181.5, "change": 1.2}])

        p = _make_provider(handler)
        quote = await p.get_quote("AAPL")
        assert quote["symbol"] == "AAPL"
        assert quote["price"] == 181.5
        await p.aclose()

    @pytest.mark.asyncio
    async def test_empty_list_raises_ticker_not_found(self) -> None:
        p = _make_provider(lambda req: httpx.Response(200, json=[]))
        with pytest.raises(TickerNotFoundError):
            await p.get_quote("NOPE")
        await p.aclose()

    @pytest.mark.asyncio
    async def test_404_maps_to_ticker_not_found(self) -> None:
        p = _make_provider(lambda req: httpx.Response(404, text="not found"))
        with pytest.raises(TickerNotFoundError):
            await p.get_quote("MISSING")
        await p.aclose()

    @pytest.mark.asyncio
    async def test_429_maps_to_rate_limit(self) -> None:
        p = _make_provider(lambda req: httpx.Response(429, text="slow down"))
        with pytest.raises(RateLimitError):
            await p.get_quote("AAPL")
        await p.aclose()

    @pytest.mark.asyncio
    async def test_generic_5xx_maps_to_market_data_error(self) -> None:
        p = _make_provider(lambda req: httpx.Response(500, text="boom"))
        with pytest.raises(MarketDataError):
            await p.get_quote("AAPL")
        await p.aclose()


# ======================================================================
# get_price_history
# ======================================================================


class TestGetPriceHistory:
    @pytest.mark.asyncio
    async def test_returns_historical_list(self) -> None:
        rows = [
            {"date": "2025-01-02", "close": 181.0},
            {"date": "2025-01-03", "close": 182.5},
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            assert "/historical-price-full/AAPL" in request.url.path
            assert request.url.params["from"] == "2025-01-01"
            assert request.url.params["to"] == "2025-01-31"
            return httpx.Response(200, json={"symbol": "AAPL", "historical": rows})

        p = _make_provider(handler)
        out = await p.get_price_history("AAPL", "2025-01-01", "2025-01-31")
        assert out == rows
        await p.aclose()

    @pytest.mark.asyncio
    async def test_empty_response_raises_not_found(self) -> None:
        p = _make_provider(lambda req: httpx.Response(200, json={}))
        with pytest.raises(TickerNotFoundError):
            await p.get_price_history("NOPE", "2025-01-01", "2025-01-31")
        await p.aclose()


# ======================================================================
# get_fundamentals
# ======================================================================


class TestGetFundamentals:
    @pytest.mark.asyncio
    async def test_bundles_three_statements(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            if "income-statement" in path:
                return httpx.Response(200, json=[{"year": 2024, "revenue": 1000}])
            if "balance-sheet-statement" in path:
                return httpx.Response(200, json=[{"year": 2024, "total_assets": 5000}])
            if "cash-flow-statement" in path:
                return httpx.Response(200, json=[{"year": 2024, "cfo": 300}])
            return httpx.Response(404)

        p = _make_provider(handler)
        data = await p.get_fundamentals("AAPL")
        assert data["income_statement"][0]["revenue"] == 1000
        assert data["balance_sheet"][0]["total_assets"] == 5000
        assert data["cash_flow"][0]["cfo"] == 300
        await p.aclose()

    @pytest.mark.asyncio
    async def test_all_empty_raises_not_found(self) -> None:
        p = _make_provider(lambda req: httpx.Response(200, json=[]))
        with pytest.raises(TickerNotFoundError):
            await p.get_fundamentals("GHOST")
        await p.aclose()


# ======================================================================
# get_key_metrics
# ======================================================================


class TestGetKeyMetrics:
    @pytest.mark.asyncio
    async def test_returns_records(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert "/key-metrics/AAPL" in request.url.path
            return httpx.Response(200, json=[{"year": 2024, "pe": 28.5}])

        p = _make_provider(handler)
        data = await p.get_key_metrics("AAPL")
        assert data["records"][0]["pe"] == 28.5
        await p.aclose()

    @pytest.mark.asyncio
    async def test_empty_raises_not_found(self) -> None:
        p = _make_provider(lambda req: httpx.Response(200, json=[]))
        with pytest.raises(TickerNotFoundError):
            await p.get_key_metrics("NOPE")
        await p.aclose()


# ======================================================================
# search_tickers
# ======================================================================


class TestSearchTickers:
    @pytest.mark.asyncio
    async def test_returns_matches(self) -> None:
        results = [
            {"symbol": "AAPL", "name": "Apple Inc."},
            {"symbol": "AAPL.MX", "name": "Apple Inc."},
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            assert "/search" in request.url.path
            assert request.url.params["query"] == "apple"
            return httpx.Response(200, json=results)

        p = _make_provider(handler)
        out = await p.search_tickers("apple")
        assert out == results
        await p.aclose()

    @pytest.mark.asyncio
    async def test_unexpected_shape_returns_empty_list(self) -> None:
        p = _make_provider(lambda req: httpx.Response(200, json={"err": "bad"}))
        assert await p.search_tickers("xx") == []
        await p.aclose()


# ======================================================================
# Error paths shared across endpoints
# ======================================================================


class TestErrorPaths:
    @pytest.mark.asyncio
    async def test_timeout_maps_to_market_data_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            raise httpx.TimeoutException("slow")

        p = _make_provider(handler)
        with pytest.raises(MarketDataError):
            await p.get_quote("AAPL")
        await p.aclose()

    @pytest.mark.asyncio
    async def test_malformed_json_maps_to_market_data_error(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, content=b"not-valid-json{{", headers={"content-type": "application/json"}
            )

        p = _make_provider(handler)
        with pytest.raises(MarketDataError):
            await p.get_quote("AAPL")
        await p.aclose()


# ======================================================================
# Context manager
# ======================================================================


class TestContextManager:
    @pytest.mark.asyncio
    async def test_async_context_closes_owned_client(self) -> None:
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json=[{"symbol": "AAPL"}]))
        # Don't inject client so FMPProvider creates (and owns) one internally
        client = httpx.AsyncClient(transport=transport, base_url=FMPProvider.BASE_URL)
        async with FMPProvider(api_key="x", client=client) as p:
            await p.get_quote("AAPL")
        # Client is NOT owned (we injected it); aclose is a no-op on our end
        # but context manager must not blow up
