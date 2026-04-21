"""Abstract market data provider interface and domain exceptions."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from portfolio_thesis_engine.shared.exceptions import MarketDataError as _BaseMarketDataError


class MarketDataError(_BaseMarketDataError):
    """Base exception for market-data failures.

    Subclasses :class:`portfolio_thesis_engine.shared.exceptions.MarketDataError`
    so catching the shared root still catches provider-raised errors.
    """


class TickerNotFoundError(MarketDataError):
    """Raised when the upstream provider reports no data for a ticker."""


class RateLimitError(MarketDataError):
    """Raised when the provider signals throttling (HTTP 429 or equivalent)."""


class MarketDataProvider(ABC):
    """Abstract async provider for market data."""

    @abstractmethod
    async def get_quote(self, ticker: str) -> dict[str, Any]:
        """Return the latest quote for ``ticker``."""

    @abstractmethod
    async def get_price_history(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        """Return EOD price history for ``ticker`` between ISO dates."""

    @abstractmethod
    async def get_fundamentals(self, ticker: str) -> dict[str, Any]:
        """Return bundled fundamentals (IS, BS, CF) used for peer Level C."""

    @abstractmethod
    async def get_key_metrics(self, ticker: str) -> dict[str, Any]:
        """Return key metrics (multiples, ratios) for ``ticker``."""

    @abstractmethod
    async def search_tickers(self, query: str) -> list[dict[str, Any]]:
        """Search for tickers matching ``query``."""

    @abstractmethod
    def validate_ticker(self, ticker: str) -> bool:
        """Return True if ``ticker`` is plausibly valid for this provider."""
