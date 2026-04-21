"""Real-API smoke for the cross-check gate.

Gated by ``PTE_SMOKE_HIT_REAL_APIS=true``. Hits FMP /stable/ (paid) and
yfinance (free) for 1846.HK (EuroEyes) to validate that the gate's
provider-call layout + response parsing survive real shapes.

Run manually::

    PTE_SMOKE_HIT_REAL_APIS=true \\
      uv run pytest tests/integration/test_cross_check_real.py -v

Expected cost: $0 (FMP is flat-fee subscription; yfinance is free).
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_thesis_engine.cross_check import CrossCheckGate, CrossCheckStatus
from portfolio_thesis_engine.market_data.fmp_provider import FMPProvider
from portfolio_thesis_engine.market_data.yfinance_provider import YFinanceProvider
from portfolio_thesis_engine.shared.config import settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not settings.smoke_hit_real_apis,
        reason="PTE_SMOKE_HIT_REAL_APIS must be true to hit real APIs",
    ),
]


@pytest.mark.asyncio
async def test_1846_hk_cross_check_runs_end_to_end(tmp_path: Path) -> None:
    """Synthesises conservative extracted values (match yfinance roughly),
    then confirms the gate returns a well-formed report without crashing
    on real provider response shapes. Extracted numbers are placeholders
    — the test's job is to validate plumbing, not business accuracy."""
    async with FMPProvider() as fmp:
        yfinance = YFinanceProvider()
        # Sighting a value from either source first lets us provide a
        # reasonable extracted figure so the test isn't trivially FAIL.
        fmp_fund = await fmp.get_fundamentals("1846.HK")
        is_row = (fmp_fund.get("income_statement") or [{}])[0]
        reference_revenue = is_row.get("revenue")

        extracted = {
            "revenue": Decimal(str(reference_revenue))
            if reference_revenue is not None
            else Decimal("1"),
            # Other metrics left out; the gate marks them UNAVAILABLE
            # since extraction didn't supply them.
        }
        gate = CrossCheckGate(fmp, yfinance, log_dir=tmp_path)
        report = await gate.check(
            ticker="1846.HK",
            extracted_values=extracted,
            period="FY2024",
        )

    # Basic invariants — don't over-constrain this test because real
    # provider data moves.
    assert len(report.metrics) == 10
    assert report.overall_status in {
        CrossCheckStatus.PASS,
        CrossCheckStatus.WARN,
        CrossCheckStatus.FAIL,
        CrossCheckStatus.SOURCES_DISAGREE,
    }
    # Revenue should at least be cross-checkable (both sources publish it)
    revenue = next(m for m in report.metrics if m.metric == "revenue")
    # Both providers should have returned a value for 1846.HK revenue
    assert revenue.fmp_value is not None or revenue.yfinance_value is not None

    # Log file should have been written
    assert report.log_path is not None
    assert Path(report.log_path).exists()
