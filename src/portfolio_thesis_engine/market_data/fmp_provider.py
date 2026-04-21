"""Financial Modeling Prep (FMP) implementation of :class:`MarketDataProvider`.

Async HTTP via :mod:`httpx`. The async client is injectable so unit tests
can drop in an :class:`httpx.MockTransport` without network access.

Endpoints used (all under ``/api/v3/``):

- ``quote/{ticker}``                     → latest quote
- ``historical-price-full/{ticker}``     → EOD series
- ``income-statement/{ticker}``          → IS (bundled into fundamentals)
- ``balance-sheet-statement/{ticker}``   → BS
- ``cash-flow-statement/{ticker}``       → CF
- ``key-metrics/{ticker}``               → multiples/ratios
- ``search``                             → ticker search
"""

from __future__ import annotations

import re
from typing import Any

import httpx

from portfolio_thesis_engine.market_data.base import (
    MarketDataError,
    MarketDataProvider,
    RateLimitError,
    TickerNotFoundError,
)
from portfolio_thesis_engine.shared.config import settings

_TICKER_RE = re.compile(r"^[A-Z0-9._\-]{1,20}$")


class FMPProvider(MarketDataProvider):
    """Financial Modeling Prep provider."""

    BASE_URL = "https://financialmodelingprep.com/api/v3"

    def __init__(
        self,
        api_key: str | None = None,
        client: httpx.AsyncClient | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.api_key = api_key or settings.secret("fmp_api_key")
        if client is not None:
            self.client = client
            self._owns_client = False
        else:
            self.client = httpx.AsyncClient(base_url=self.BASE_URL, timeout=timeout)
            self._owns_client = True

    # ------------------------------------------------------------------
    async def aclose(self) -> None:
        """Close the underlying httpx client if we created it."""
        if self._owns_client:
            await self.client.aclose()

    async def __aenter__(self) -> FMPProvider:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.aclose()

    # ------------------------------------------------------------------
    def validate_ticker(self, ticker: str) -> bool:
        """Cheap shape check. Does not hit the network."""
        return bool(ticker) and bool(_TICKER_RE.match(ticker))

    # ------------------------------------------------------------------
    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Issue a GET, map provider-level failures to typed exceptions."""
        full_params = {"apikey": self.api_key, **(params or {})}
        try:
            response = await self.client.get(path, params=full_params)
        except httpx.TimeoutException as e:
            raise MarketDataError(f"Timeout calling FMP {path}: {e}") from e
        except httpx.HTTPError as e:
            raise MarketDataError(f"Network error calling FMP {path}: {e}") from e

        if response.status_code == 429:
            raise RateLimitError(f"FMP rate limit hit on {path}")
        if response.status_code == 404:
            raise TickerNotFoundError(f"FMP returned 404 for {path}")
        if response.status_code >= 400:
            raise MarketDataError(
                f"FMP error {response.status_code} on {path}: {response.text[:200]}"
            )

        try:
            return response.json()
        except ValueError as e:
            raise MarketDataError(f"Invalid JSON from FMP {path}: {e}") from e

    # ------------------------------------------------------------------
    async def get_quote(self, ticker: str) -> dict[str, Any]:
        data = await self._get(f"/quote/{ticker}")
        if not isinstance(data, list) or not data:
            raise TickerNotFoundError(f"Ticker {ticker!r} not found")
        first: dict[str, Any] = data[0]
        return first

    async def get_price_history(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        data = await self._get(
            f"/historical-price-full/{ticker}",
            params={"from": start_date, "to": end_date},
        )
        if not isinstance(data, dict):
            raise MarketDataError(
                f"Unexpected response shape from historical-price-full: {type(data).__name__}"
            )
        historical = data.get("historical", [])
        if not historical and not data.get("symbol"):
            raise TickerNotFoundError(f"No history for ticker {ticker!r}")
        return list(historical)

    async def get_fundamentals(self, ticker: str) -> dict[str, Any]:
        """Bundle IS + BS + CF into a single dict."""
        income = await self._get(f"/income-statement/{ticker}", {"limit": 5})
        balance = await self._get(f"/balance-sheet-statement/{ticker}", {"limit": 5})
        cashflow = await self._get(f"/cash-flow-statement/{ticker}", {"limit": 5})
        # Any endpoint returning an empty list is a strong signal the ticker
        # isn't covered by FMP.
        if not (income or balance or cashflow):
            raise TickerNotFoundError(f"No fundamentals for ticker {ticker!r}")
        return {
            "income_statement": income or [],
            "balance_sheet": balance or [],
            "cash_flow": cashflow or [],
        }

    async def get_key_metrics(self, ticker: str) -> dict[str, Any]:
        data = await self._get(f"/key-metrics/{ticker}", {"limit": 5})
        if not isinstance(data, list) or not data:
            raise TickerNotFoundError(f"No key metrics for ticker {ticker!r}")
        return {"records": data}

    async def search_tickers(self, query: str) -> list[dict[str, Any]]:
        data = await self._get("/search", {"query": query, "limit": 20, "exchange": ""})
        if not isinstance(data, list):
            return []
        return data
