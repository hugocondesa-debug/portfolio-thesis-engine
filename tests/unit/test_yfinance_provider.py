"""Unit tests for YFinanceProvider.

Patches the ``yf`` name imported by the provider module — tests never
touch Yahoo Finance. Response fixtures mirror the shapes observed live
against real tickers.
"""

from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from portfolio_thesis_engine.market_data.base import (
    MarketDataError,
    TickerNotFoundError,
)
from portfolio_thesis_engine.market_data.yfinance_provider import (
    YFinanceProvider,
    _df_to_records,
)

_YF_MODULE = "portfolio_thesis_engine.market_data.yfinance_provider.yf"


def _mock_ticker(**attrs: object) -> MagicMock:
    """Build a MagicMock that mimics ``yf.Ticker(symbol)``."""
    t = MagicMock()
    for k, v in attrs.items():
        setattr(t, k, v)
    return t


# ======================================================================
# validate_ticker
# ======================================================================


class TestValidateTicker:
    def test_accepts_common_forms_including_indices(self) -> None:
        p = YFinanceProvider()
        for ok in ("AAPL", "BRK.B", "^GSPC", "9988.HK", "EURUSD=X"):
            assert p.validate_ticker(ok), f"expected {ok!r} valid"

    def test_rejects_empty_and_garbage(self) -> None:
        p = YFinanceProvider()
        for bad in ("", "has space", "a" * 25, "!!!"):
            assert not p.validate_ticker(bad), f"expected {bad!r} invalid"


# ======================================================================
# get_quote
# ======================================================================


class TestGetQuote:
    @pytest.mark.asyncio
    async def test_happy_path(self) -> None:
        info = {
            "symbol": "AAPL",
            "shortName": "Apple Inc.",
            "currentPrice": 273.05,
            "currency": "USD",
            "marketCap": 4_000_000_000_000,
            "regularMarketVolume": 40_000_000,
            "previousClose": 272.0,
            "dayHigh": 274.0,
            "dayLow": 271.5,
        }
        with patch(_YF_MODULE) as yf:
            yf.Ticker.return_value = _mock_ticker(info=info)
            p = YFinanceProvider()
            quote = await p.get_quote("AAPL")
        assert quote["symbol"] == "AAPL"
        assert quote["price"] == 273.05
        assert quote["currency"] == "USD"

    @pytest.mark.asyncio
    async def test_falls_back_to_regular_market_price(self) -> None:
        info = {
            "symbol": "AAPL",
            "regularMarketPrice": 270.0,  # currentPrice absent
            "currency": "USD",
        }
        with patch(_YF_MODULE) as yf:
            yf.Ticker.return_value = _mock_ticker(info=info)
            p = YFinanceProvider()
            quote = await p.get_quote("AAPL")
        assert quote["price"] == 270.0

    @pytest.mark.asyncio
    async def test_empty_info_raises_not_found(self) -> None:
        with patch(_YF_MODULE) as yf:
            yf.Ticker.return_value = _mock_ticker(info={})
            p = YFinanceProvider()
            with pytest.raises(TickerNotFoundError):
                await p.get_quote("NOPE")

    @pytest.mark.asyncio
    async def test_missing_price_raises_not_found(self) -> None:
        with patch(_YF_MODULE) as yf:
            yf.Ticker.return_value = _mock_ticker(
                info={"symbol": "NOPE"}  # no price field
            )
            p = YFinanceProvider()
            with pytest.raises(TickerNotFoundError):
                await p.get_quote("NOPE")

    @pytest.mark.asyncio
    async def test_yfinance_exception_maps_to_market_data_error(self) -> None:
        with patch(_YF_MODULE) as yf:
            yf.Ticker.side_effect = RuntimeError("scrape blew up")
            p = YFinanceProvider()
            with pytest.raises(MarketDataError, match="scrape blew up"):
                await p.get_quote("AAPL")


# ======================================================================
# get_price_history
# ======================================================================


class TestGetPriceHistory:
    @pytest.mark.asyncio
    async def test_converts_dataframe_to_list_of_dicts(self) -> None:
        idx = pd.DatetimeIndex([datetime(2025, 1, 2), datetime(2025, 1, 3)], name="Date")
        df = pd.DataFrame(
            {
                "Open": [248.93, 243.0],
                "High": [249.10, 245.0],
                "Low": [241.82, 241.0],
                "Close": [243.85, 243.36],
                "Volume": [55740700, 40000000],
                "Dividends": [0.0, 0.0],
                "Stock Splits": [0.0, 0.0],
            },
            index=idx,
        )
        with patch(_YF_MODULE) as yf:
            yf.Ticker.return_value = _mock_ticker(history=MagicMock(return_value=df))
            p = YFinanceProvider()
            rows = await p.get_price_history("AAPL", "2025-01-02", "2025-01-10")
        assert rows[0]["date"] == "2025-01-02"
        assert rows[0]["close"] == pytest.approx(243.85)
        assert rows[0]["volume"] == 55740700
        assert len(rows) == 2

    @pytest.mark.asyncio
    async def test_empty_dataframe_raises_not_found(self) -> None:
        empty = pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
        with patch(_YF_MODULE) as yf:
            yf.Ticker.return_value = _mock_ticker(history=MagicMock(return_value=empty))
            p = YFinanceProvider()
            with pytest.raises(TickerNotFoundError):
                await p.get_price_history("NOPE", "2025-01-01", "2025-01-31")

    @pytest.mark.asyncio
    async def test_none_dataframe_raises_not_found(self) -> None:
        with patch(_YF_MODULE) as yf:
            yf.Ticker.return_value = _mock_ticker(history=MagicMock(return_value=None))
            p = YFinanceProvider()
            with pytest.raises(TickerNotFoundError):
                await p.get_price_history("NOPE", "2025-01-01", "2025-01-31")


# ======================================================================
# get_fundamentals
# ======================================================================


class TestGetFundamentals:
    @pytest.mark.asyncio
    async def test_transposes_dataframes_to_period_records(self) -> None:
        col = pd.Timestamp("2024-09-30")
        income = pd.DataFrame({col: {"Total Revenue": 385_000_000_000.0}})
        balance = pd.DataFrame({col: {"Total Assets": 360_000_000_000.0}})
        cashflow = pd.DataFrame({col: {"Operating Cash Flow": 108_000_000_000.0}})

        with patch(_YF_MODULE) as yf:
            yf.Ticker.return_value = _mock_ticker(
                financials=income,
                balance_sheet=balance,
                cashflow=cashflow,
            )
            p = YFinanceProvider()
            data = await p.get_fundamentals("AAPL")
        assert data["income_statement"][0]["period"] == "2024-09-30"
        assert data["income_statement"][0]["Total Revenue"] == 385_000_000_000.0
        assert data["balance_sheet"][0]["Total Assets"] == 360_000_000_000.0
        assert data["cash_flow"][0]["Operating Cash Flow"] == 108_000_000_000.0

    @pytest.mark.asyncio
    async def test_all_empty_raises_not_found(self) -> None:
        empty = pd.DataFrame()
        with patch(_YF_MODULE) as yf:
            yf.Ticker.return_value = _mock_ticker(
                financials=empty, balance_sheet=empty, cashflow=empty
            )
            p = YFinanceProvider()
            with pytest.raises(TickerNotFoundError):
                await p.get_fundamentals("GHOST")


class TestDfToRecordsHelper:
    def test_none_returns_empty(self) -> None:
        assert _df_to_records(None) == []

    def test_empty_dataframe_returns_empty(self) -> None:
        assert _df_to_records(pd.DataFrame()) == []

    def test_skips_nan_values(self) -> None:
        col = pd.Timestamp("2024-01-01")
        df = pd.DataFrame({col: {"A": 1.0, "B": float("nan")}})
        records = _df_to_records(df)
        assert records[0]["A"] == 1.0
        assert "B" not in records[0]


# ======================================================================
# get_key_metrics
# ======================================================================


class TestGetKeyMetrics:
    @pytest.mark.asyncio
    async def test_extracts_info_fields(self) -> None:
        info = {
            "symbol": "AAPL",
            "trailingPE": 35.2,
            "forwardPE": 28.1,
            "priceToBook": 55.3,
            "beta": 1.28,
        }
        with patch(_YF_MODULE) as yf:
            yf.Ticker.return_value = _mock_ticker(info=info)
            p = YFinanceProvider()
            data = await p.get_key_metrics("AAPL")
        rec = data["records"][0]
        assert rec["trailingPE"] == 35.2
        assert rec["beta"] == 1.28

    @pytest.mark.asyncio
    async def test_no_symbol_raises_not_found(self) -> None:
        with patch(_YF_MODULE) as yf:
            yf.Ticker.return_value = _mock_ticker(info={})
            p = YFinanceProvider()
            with pytest.raises(TickerNotFoundError):
                await p.get_key_metrics("NOPE")

    @pytest.mark.asyncio
    async def test_exposes_shares_outstanding_and_market_cap(self) -> None:
        """Cross-check gate (Phase 1 Sprint 5) relies on these being in
        the key-metrics record."""
        info = {
            "symbol": "AAPL",
            "sharesOutstanding": 15_000_000_000,
            "marketCap": 4_000_000_000_000,
        }
        with patch(_YF_MODULE) as yf:
            yf.Ticker.return_value = _mock_ticker(info=info)
            p = YFinanceProvider()
            data = await p.get_key_metrics("AAPL")
        rec = data["records"][0]
        assert rec["sharesOutstanding"] == 15_000_000_000
        assert rec["marketCap"] == 4_000_000_000_000


# ======================================================================
# search_tickers
# ======================================================================


class TestSearchTickers:
    @pytest.mark.asyncio
    async def test_maps_search_results(self) -> None:
        fake_quotes = [
            {
                "symbol": "AAPL",
                "shortname": "Apple Inc.",
                "exchange": "NMS",
                "quoteType": "EQUITY",
            },
            {
                "symbol": "APLE",
                "shortname": "Apple Hospitality REIT",
                "exchange": "NYQ",
                "quoteType": "EQUITY",
            },
        ]
        fake_search = SimpleNamespace(quotes=fake_quotes)
        with patch(_YF_MODULE) as yf:
            yf.Search.return_value = fake_search
            p = YFinanceProvider()
            results = await p.search_tickers("apple")
        assert [r["symbol"] for r in results] == ["AAPL", "APLE"]
        assert results[0]["name"] == "Apple Inc."

    @pytest.mark.asyncio
    async def test_search_failure_maps_to_market_data_error(self) -> None:
        with patch(_YF_MODULE) as yf:
            yf.Search.side_effect = ConnectionError("network down")
            p = YFinanceProvider()
            with pytest.raises(MarketDataError, match="network down"):
                await p.search_tickers("apple")

    @pytest.mark.asyncio
    async def test_unexpected_shape_returns_empty(self) -> None:
        fake_search = SimpleNamespace(quotes="unexpected string")
        with patch(_YF_MODULE) as yf:
            yf.Search.return_value = fake_search
            p = YFinanceProvider()
            assert await p.search_tickers("x") == []
