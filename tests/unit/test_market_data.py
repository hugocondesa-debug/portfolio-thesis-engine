"""Unit tests for the FMP market data provider (stable API).

HTTP is mocked via :class:`httpx.MockTransport` — no network access and no
real API key required. Response fixtures match the shapes verified live
against ``https://financialmodelingprep.com/stable`` endpoints.
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
# BASE_URL
# ======================================================================


class TestBaseURL:
    def test_base_url_is_stable(self) -> None:
        assert FMPProvider.BASE_URL == "https://financialmodelingprep.com/stable"


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
# get_quote — /quote?symbol=...
# ======================================================================


class TestGetQuote:
    @pytest.mark.asyncio
    async def test_returns_first_row_of_list(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith("/quote")
            assert request.url.params["symbol"] == "AAPL"
            assert request.url.params["apikey"] == "test-key"
            return httpx.Response(
                200,
                json=[
                    {
                        "symbol": "AAPL",
                        "name": "Apple Inc.",
                        "price": 273.05,
                        "changePercentage": 0.12,
                        "volume": 40000000,
                    }
                ],
            )

        p = _make_provider(handler)
        quote = await p.get_quote("AAPL")
        assert quote["symbol"] == "AAPL"
        assert quote["price"] == 273.05
        await p.aclose()

    @pytest.mark.asyncio
    async def test_empty_list_raises_ticker_not_found(self) -> None:
        """Stable API returns 200 + [] for unknown tickers."""
        p = _make_provider(lambda req: httpx.Response(200, json=[]))
        with pytest.raises(TickerNotFoundError):
            await p.get_quote("NOPE")
        await p.aclose()

    @pytest.mark.asyncio
    async def test_401_maps_to_market_data_error(self) -> None:
        p = _make_provider(
            lambda req: httpx.Response(
                401,
                json={"Error Message": "Invalid API KEY."},
            )
        )
        with pytest.raises(MarketDataError, match="Invalid API KEY"):
            await p.get_quote("AAPL")
        await p.aclose()

    @pytest.mark.asyncio
    async def test_403_maps_to_market_data_error(self) -> None:
        """Legacy endpoint sends 403 — proves we're not hitting those any more."""
        p = _make_provider(
            lambda req: httpx.Response(403, json={"Error Message": "Legacy Endpoint"})
        )
        with pytest.raises(MarketDataError, match="Legacy Endpoint"):
            await p.get_quote("AAPL")
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
# get_price_history — /historical-price-eod/full?symbol=&from=&to=
# ======================================================================


class TestGetPriceHistory:
    @pytest.mark.asyncio
    async def test_returns_flat_list_of_rows(self) -> None:
        rows = [
            {"symbol": "AAPL", "date": "2025-01-10", "close": 229.5},
            {"symbol": "AAPL", "date": "2025-01-09", "close": 228.0},
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith("/historical-price-eod/full")
            assert request.url.params["symbol"] == "AAPL"
            assert request.url.params["from"] == "2025-01-01"
            assert request.url.params["to"] == "2025-01-31"
            return httpx.Response(200, json=rows)

        p = _make_provider(handler)
        out = await p.get_price_history("AAPL", "2025-01-01", "2025-01-31")
        assert out == rows
        await p.aclose()

    @pytest.mark.asyncio
    async def test_empty_response_raises_not_found(self) -> None:
        p = _make_provider(lambda req: httpx.Response(200, json=[]))
        with pytest.raises(TickerNotFoundError):
            await p.get_price_history("NOPE", "2025-01-01", "2025-01-31")
        await p.aclose()

    @pytest.mark.asyncio
    async def test_unexpected_shape_raises_market_data_error(self) -> None:
        p = _make_provider(lambda req: httpx.Response(200, json={"unexpected": "shape"}))
        with pytest.raises(MarketDataError):
            await p.get_price_history("AAPL", "2025-01-01", "2025-01-31")
        await p.aclose()


# ======================================================================
# get_profile — /profile?symbol=...
# ======================================================================


class TestGetProfile:
    @pytest.mark.asyncio
    async def test_returns_first_row(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith("/profile")
            return httpx.Response(
                200,
                json=[{"symbol": "AAPL", "currency": "USD", "marketCap": 3.4e12}],
            )

        p = _make_provider(handler)
        profile = await p.get_profile("AAPL")
        assert profile["symbol"] == "AAPL"
        assert profile["currency"] == "USD"
        await p.aclose()

    @pytest.mark.asyncio
    async def test_empty_raises_not_found(self) -> None:
        p = _make_provider(lambda req: httpx.Response(200, json=[]))
        with pytest.raises(TickerNotFoundError):
            await p.get_profile("NOPE")
        await p.aclose()


# ======================================================================
# get_fundamentals — 3x endpoint bundle
# ======================================================================


class TestGetFundamentals:
    @pytest.mark.asyncio
    async def test_bundles_three_statements(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            assert request.url.params["symbol"] == "AAPL"
            if path.endswith("/income-statement"):
                return httpx.Response(200, json=[{"date": "2024", "revenue": 1000}])
            if path.endswith("/balance-sheet-statement"):
                return httpx.Response(200, json=[{"date": "2024", "total_assets": 5000}])
            if path.endswith("/cash-flow-statement"):
                return httpx.Response(200, json=[{"date": "2024", "cfo": 300}])
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
# get_key_metrics — /key-metrics?symbol=&limit=5
# ======================================================================


class TestGetKeyMetrics:
    @pytest.mark.asyncio
    async def test_returns_records(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path.endswith("/key-metrics")
            assert request.url.params["symbol"] == "AAPL"
            assert request.url.params["limit"] == "5"
            return httpx.Response(200, json=[{"fiscalYear": 2024, "marketCap": 3.4e12}])

        p = _make_provider(handler)
        data = await p.get_key_metrics("AAPL")
        assert data["records"][0]["fiscalYear"] == 2024
        await p.aclose()

    @pytest.mark.asyncio
    async def test_empty_raises_not_found(self) -> None:
        p = _make_provider(lambda req: httpx.Response(200, json=[]))
        with pytest.raises(TickerNotFoundError):
            await p.get_key_metrics("NOPE")
        await p.aclose()


# ======================================================================
# search_tickers — /search-name?query=&limit=20
# ======================================================================


class TestSearchTickers:
    @pytest.mark.asyncio
    async def test_returns_matches_via_search_name(self) -> None:
        results = [
            {"symbol": "AAPL", "name": "Apple Inc."},
            {"symbol": "APC.DE", "name": "Apple Inc."},
        ]

        def handler(request: httpx.Request) -> httpx.Response:
            # We route name searches to /search-name (not /search-symbol).
            assert request.url.path.endswith("/search-name")
            assert request.url.params["query"] == "apple"
            assert request.url.params["limit"] == "20"
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
# Shared error paths
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
                200,
                content=b"not-valid-json{{",
                headers={"content-type": "application/json"},
            )

        p = _make_provider(handler)
        with pytest.raises(MarketDataError):
            await p.get_quote("AAPL")
        await p.aclose()


# ======================================================================
# Error-body parser
# ======================================================================


class TestErrorMessageExtraction:
    def test_extracts_error_message_key(self) -> None:
        assert (
            FMPProvider._extract_error_message('{"Error Message": "Invalid API KEY."}')
            == "Invalid API KEY."
        )

    def test_extracts_lowercase_message_key(self) -> None:
        assert FMPProvider._extract_error_message('{"message": "throttled"}') == "throttled"

    def test_falls_back_to_truncated_body(self) -> None:
        body = "not json at all " * 50
        result = FMPProvider._extract_error_message(body)
        assert len(result) <= 200
        assert result.startswith("not json")


# ======================================================================
# Context manager
# ======================================================================


class TestContextManager:
    @pytest.mark.asyncio
    async def test_async_context_closes_owned_client(self) -> None:
        transport = httpx.MockTransport(lambda r: httpx.Response(200, json=[{"symbol": "AAPL"}]))
        client = httpx.AsyncClient(transport=transport, base_url=FMPProvider.BASE_URL)
        async with FMPProvider(api_key="x", client=client) as p:
            await p.get_quote("AAPL")


# ======================================================================
# Sprint 4A-alpha.7 — get_fundamentals_for_period
# ======================================================================


def _period_handler(
    rows_by_path: dict[str, list[dict[str, Any]]],
) -> Any:
    """Build an httpx handler serving ``rows_by_path[path_suffix]``."""

    def handler(request: httpx.Request) -> httpx.Response:
        for suffix, rows in rows_by_path.items():
            if request.url.path.endswith(suffix):
                return httpx.Response(200, json=rows)
        return httpx.Response(404)

    return handler


class TestFMPPeriodAwareFundamentals:
    """FMP :meth:`get_fundamentals_for_period` — Sprint 4A-alpha.7."""

    @pytest.mark.asyncio
    async def test_P2_S4A_ALPHA_7_FMP_01_returns_matching_year(self) -> None:
        handler = _period_handler(
            {
                "/income-statement": [
                    {"calendarYear": "2024", "revenue": 715682000, "date": "2024-12-31"},
                    {"calendarYear": "2023", "revenue": 714289000, "date": "2023-12-31"},
                    {"calendarYear": "2022", "revenue": 610291000, "date": "2022-12-31"},
                ],
                "/balance-sheet-statement": [
                    {"calendarYear": "2023", "totalAssets": 1000}
                ],
                "/cash-flow-statement": [
                    {"calendarYear": "2023", "operatingCashFlow": 200}
                ],
            }
        )
        p = _make_provider(handler)
        result = await p.get_fundamentals_for_period("1846.HK", 2023)
        assert result is not None
        assert result["income_statement"][0]["revenue"] == 714289000
        assert result["balance_sheet"][0]["totalAssets"] == 1000
        assert result["cash_flow"][0]["operatingCashFlow"] == 200
        await p.aclose()

    @pytest.mark.asyncio
    async def test_P2_S4A_ALPHA_7_FMP_02_returns_none_when_year_unavailable(
        self,
    ) -> None:
        handler = _period_handler(
            {
                "/income-statement": [
                    {"calendarYear": "2024", "revenue": 715682000},
                ],
                "/balance-sheet-statement": [{"calendarYear": "2024"}],
                "/cash-flow-statement": [{"calendarYear": "2024"}],
            }
        )
        p = _make_provider(handler)
        result = await p.get_fundamentals_for_period("1846.HK", 2015)
        assert result is None
        await p.aclose()

    @pytest.mark.asyncio
    async def test_P2_S4A_ALPHA_7_FMP_03_handles_empty_response(self) -> None:
        """Empty list across all three endpoints → None."""
        handler = _period_handler(
            {
                "/income-statement": [],
                "/balance-sheet-statement": [],
                "/cash-flow-statement": [],
            }
        )
        p = _make_provider(handler)
        result = await p.get_fundamentals_for_period("UNKNOWN", 2024)
        assert result is None
        await p.aclose()

    @pytest.mark.asyncio
    async def test_P2_S4A_ALPHA_7_FMP_04_handles_string_calendar_year(
        self,
    ) -> None:
        """``calendarYear`` arrives as string; filter converts to int."""
        # Dedicated assertion: same year, string vs int both match.
        handler = _period_handler(
            {
                "/income-statement": [
                    {"calendarYear": "2024", "revenue": 100},
                ],
                "/balance-sheet-statement": [],
                "/cash-flow-statement": [],
            }
        )
        p = _make_provider(handler)
        result = await p.get_fundamentals_for_period("T", 2024)
        assert result is not None
        assert result["income_statement"][0]["revenue"] == 100
        assert result["balance_sheet"] == []
        await p.aclose()

    @pytest.mark.asyncio
    async def test_P2_S4A_ALPHA_7_FMP_05_skips_malformed_items(self) -> None:
        """Items lacking ``calendarYear`` skipped; other items still matched."""
        handler = _period_handler(
            {
                "/income-statement": [
                    {"date": "2024-12-31", "revenue": 999},  # no calendarYear
                    {"calendarYear": "2023", "revenue": 500},
                ],
                "/balance-sheet-statement": [],
                "/cash-flow-statement": [],
            }
        )
        p = _make_provider(handler)
        # Request 2024 — malformed 2024 is skipped, only 2023 has cal_year
        result_2024 = await p.get_fundamentals_for_period("T", 2024)
        assert result_2024 is None
        # Request 2023 — returns the well-formed item.
        result_2023 = await p.get_fundamentals_for_period("T", 2023)
        assert result_2023 is not None
        assert result_2023["income_statement"][0]["revenue"] == 500
        await p.aclose()


# ======================================================================
# Sprint 4A-alpha.7 — backward compatibility
# ======================================================================


class TestBackwardCompatibility:
    """Existing :meth:`get_fundamentals` path unchanged post-sprint."""

    @pytest.mark.asyncio
    async def test_P2_S4A_ALPHA_7_BC_01_get_fundamentals_unchanged(self) -> None:
        """Existing latest-annual path still returns list-of-periods bundle."""
        def handler(request: httpx.Request) -> httpx.Response:
            path = request.url.path
            assert request.url.params["limit"] == "5"
            if path.endswith("/income-statement"):
                return httpx.Response(
                    200,
                    json=[
                        {"calendarYear": "2024", "revenue": 100},
                        {"calendarYear": "2023", "revenue": 90},
                    ],
                )
            if path.endswith("/balance-sheet-statement"):
                return httpx.Response(200, json=[{"calendarYear": "2024"}])
            if path.endswith("/cash-flow-statement"):
                return httpx.Response(200, json=[{"calendarYear": "2024"}])
            return httpx.Response(404)

        p = _make_provider(handler)
        data = await p.get_fundamentals("1846.HK")
        # Still returns multi-year lists (unchanged from pre-sprint).
        assert len(data["income_statement"]) == 2
        assert data["income_statement"][0]["revenue"] == 100
        await p.aclose()
