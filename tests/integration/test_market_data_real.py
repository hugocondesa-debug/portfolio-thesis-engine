"""Real-API smoke tests for the market-data providers.

Gated by ``PTE_SMOKE_HIT_REAL_APIS=true``. Each provider issues one
minimal call to validate API-key / connectivity / endpoint-path
correctness. FMP is under paid subscription (stable endpoints) and
yfinance scrapes Yahoo (free but unofficial); both calls are cheap and
don't exercise anything beyond single-quote retrieval.

Run manually:

::

    PTE_SMOKE_HIT_REAL_APIS=true uv run pytest tests/integration/test_market_data_real.py -v
"""

from __future__ import annotations

import pytest

from portfolio_thesis_engine.market_data.fmp_provider import FMPProvider
from portfolio_thesis_engine.market_data.yfinance_provider import YFinanceProvider
from portfolio_thesis_engine.shared.config import settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not settings.smoke_hit_real_apis,
        reason="PTE_SMOKE_HIT_REAL_APIS must be true to hit real market-data APIs",
    ),
]


@pytest.mark.asyncio
async def test_fmp_stable_quote_apple() -> None:
    """Hits the real FMP ``/stable/quote`` endpoint. Confirms the new
    endpoint path + query-param symbol works against production."""
    async with FMPProvider() as p:
        quote = await p.get_quote("AAPL")
    assert quote.get("symbol") == "AAPL"
    assert "price" in quote
    assert isinstance(quote["price"], (int, float))


@pytest.mark.asyncio
async def test_yfinance_quote_apple() -> None:
    """Hits Yahoo Finance via yfinance. Free — no API key, no direct cost."""
    p = YFinanceProvider()
    quote = await p.get_quote("AAPL")
    assert quote.get("symbol") == "AAPL"
    assert quote.get("price") is not None
    assert quote.get("currency") == "USD"
