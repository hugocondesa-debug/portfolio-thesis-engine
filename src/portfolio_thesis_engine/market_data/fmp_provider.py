"""Financial Modeling Prep (FMP) implementation of :class:`MarketDataProvider`.

Uses FMP's **stable** API (``https://financialmodelingprep.com/stable``).
Legacy ``/api/v3/`` paths were deprecated for new subscribers in
August 2025 and now return 403 "Legacy Endpoint".

Differences vs. legacy worth noting:

- Symbols are passed as a query parameter (``?symbol=AAPL``), not embedded
  in the path.
- ``/historical-price-eod/full`` returns a **flat list** of rows (one per
  trading day) instead of ``{"symbol": ..., "historical": [...]}``.
- An unknown ticker returns ``200`` with an empty list ``[]``, not 404.
- An invalid API key returns ``401`` with ``{"Error Message": "..."}``.

Async HTTP via :mod:`httpx`; the client is injectable so unit tests can
drop in an :class:`httpx.MockTransport` without network access.
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
    """Financial Modeling Prep provider (stable API)."""

    BASE_URL = "https://financialmodelingprep.com/stable"

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
    @staticmethod
    def _extract_error_message(body: str) -> str:
        """FMP typically surfaces errors as ``{"Error Message": "..."}``.

        Return the message if present, else the truncated body.
        """
        import json

        try:
            payload = json.loads(body)
        except ValueError:
            return body[:200]
        if isinstance(payload, dict):
            msg = payload.get("Error Message") or payload.get("message")
            if isinstance(msg, str):
                return msg
        return body[:200]

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        """Issue a GET with the API key injected, map errors to typed exceptions."""
        full_params: dict[str, Any] = {"apikey": self.api_key, **(params or {})}
        try:
            response = await self.client.get(path, params=full_params)
        except httpx.TimeoutException as e:
            raise MarketDataError(f"Timeout calling FMP {path}: {e}") from e
        except httpx.HTTPError as e:
            raise MarketDataError(f"Network error calling FMP {path}: {e}") from e

        if response.status_code == 429:
            raise RateLimitError(f"FMP rate limit hit on {path}")
        if response.status_code == 401 or response.status_code == 403:
            raise MarketDataError(
                f"FMP auth error on {path}: {self._extract_error_message(response.text)}"
            )
        if response.status_code == 404:
            raise TickerNotFoundError(f"FMP returned 404 for {path}")
        if response.status_code >= 400:
            raise MarketDataError(
                f"FMP error {response.status_code} on {path}: "
                f"{self._extract_error_message(response.text)}"
            )

        try:
            return response.json()
        except ValueError as e:
            raise MarketDataError(f"Invalid JSON from FMP {path}: {e}") from e

    # ------------------------------------------------------------------
    async def get_quote(self, ticker: str) -> dict[str, Any]:
        data = await self._get("/quote", {"symbol": ticker})
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
            "/historical-price-eod/full",
            {"symbol": ticker, "from": start_date, "to": end_date},
        )
        # Stable API returns a flat list of rows directly.
        if not isinstance(data, list):
            raise MarketDataError(
                f"Unexpected response shape from /historical-price-eod/full: {type(data).__name__}"
            )
        if not data:
            raise TickerNotFoundError(f"No history for ticker {ticker!r}")
        return list(data)

    async def get_profile(self, ticker: str) -> dict[str, Any]:
        """Return company profile — not part of the abstract interface but
        useful for downstream pipelines that need industry/sector metadata."""
        data = await self._get("/profile", {"symbol": ticker})
        if not isinstance(data, list) or not data:
            raise TickerNotFoundError(f"No profile for ticker {ticker!r}")
        first: dict[str, Any] = data[0]
        return first

    async def get_fundamentals(self, ticker: str) -> dict[str, Any]:
        """Bundle IS + BS + CF into a single dict. Each sub-endpoint returns
        a list of period snapshots (most recent first)."""
        income = await self._get("/income-statement", {"symbol": ticker, "limit": 5})
        balance = await self._get("/balance-sheet-statement", {"symbol": ticker, "limit": 5})
        cashflow = await self._get("/cash-flow-statement", {"symbol": ticker, "limit": 5})
        if not (income or balance or cashflow):
            raise TickerNotFoundError(f"No fundamentals for ticker {ticker!r}")
        return {
            "income_statement": income if isinstance(income, list) else [],
            "balance_sheet": balance if isinstance(balance, list) else [],
            "cash_flow": cashflow if isinstance(cashflow, list) else [],
        }

    async def get_fundamentals_for_period(
        self,
        ticker: str,
        fiscal_year: int,
    ) -> dict[str, Any] | None:
        """Sprint 4A-alpha.7 — filter ``/income-statement`` /
        ``/balance-sheet-statement`` / ``/cash-flow-statement`` responses
        down to the requested fiscal year via the ``calendarYear`` field.

        Returns a bundle shaped like :meth:`get_fundamentals` but with
        single-element lists so the :mod:`cross_check.gate` metric
        extractors work unchanged. ``None`` when none of the three
        endpoints have data for the year (provider lacks historical
        depth). Network / auth errors propagate.
        """
        income_list = await self._get(
            "/income-statement", {"symbol": ticker, "limit": 10}
        )
        balance_list = await self._get(
            "/balance-sheet-statement", {"symbol": ticker, "limit": 10}
        )
        cashflow_list = await self._get(
            "/cash-flow-statement", {"symbol": ticker, "limit": 10}
        )

        income = self._filter_by_year(income_list, fiscal_year)
        balance = self._filter_by_year(balance_list, fiscal_year)
        cashflow = self._filter_by_year(cashflow_list, fiscal_year)

        if income is None and balance is None and cashflow is None:
            return None

        # Return single-element lists — preserves the shape the cross-
        # check extractors already expect (records[0] via _first()).
        return {
            "income_statement": [income] if income is not None else [],
            "balance_sheet": [balance] if balance is not None else [],
            "cash_flow": [cashflow] if cashflow is not None else [],
        }

    @staticmethod
    def _filter_by_year(
        items: Any,
        fiscal_year: int,
    ) -> dict[str, Any] | None:
        """Return the FMP statement item whose ``calendarYear`` matches
        ``fiscal_year``. Tolerates string / int representations and
        skips malformed items silently."""
        if not isinstance(items, list) or not items:
            return None
        for item in items:
            if not isinstance(item, dict):
                continue
            cal_year_raw = item.get("calendarYear")
            if cal_year_raw is None:
                continue
            try:
                cal_year = int(str(cal_year_raw))
            except (ValueError, TypeError):
                continue
            if cal_year == fiscal_year:
                return item
        return None

    async def get_key_metrics(self, ticker: str) -> dict[str, Any]:
        data = await self._get("/key-metrics", {"symbol": ticker, "limit": 5})
        if not isinstance(data, list) or not data:
            raise TickerNotFoundError(f"No key metrics for ticker {ticker!r}")
        return {"records": data}

    async def search_tickers(self, query: str) -> list[dict[str, Any]]:
        """Search FMP's company-name index.

        The stable API splits search into ``/search-symbol`` (ticker prefix
        match) and ``/search-name`` (company-name match). We route to
        ``/search-name`` because user-facing searches are typed by name;
        callers who know they have a ticker should just call
        :meth:`get_quote` directly.
        """
        data = await self._get("/search-name", {"query": query, "limit": 20})
        if not isinstance(data, list):
            return []
        return data
