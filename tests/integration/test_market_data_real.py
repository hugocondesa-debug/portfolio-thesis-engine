"""Real-API smoke test for FMP.

Gated by ``PTE_SMOKE_HIT_REAL_APIS=true``. Issues exactly one
:meth:`FMPProvider.get_quote` call to ``AAPL`` to validate API key +
connectivity. Run manually:

::

    PTE_SMOKE_HIT_REAL_APIS=true uv run pytest tests/integration/test_market_data_real.py -v
"""

from __future__ import annotations

import pytest

from portfolio_thesis_engine.market_data.fmp_provider import FMPProvider
from portfolio_thesis_engine.shared.config import settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not settings.smoke_hit_real_apis,
        reason="PTE_SMOKE_HIT_REAL_APIS must be true to hit real market-data APIs",
    ),
]


@pytest.mark.asyncio
async def test_fmp_quote_apple() -> None:
    async with FMPProvider() as p:
        quote = await p.get_quote("AAPL")
    assert quote.get("symbol") == "AAPL"
    assert "price" in quote
    assert isinstance(quote["price"], (int, float))
