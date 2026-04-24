"""Extract dividend stream from :class:`ThreeStatementProjection`.

The forecast module stores ``CashFlowYear.dividends_paid`` as a
**negative outflow** (consistent with indirect-method CF presentation).
DDM treats dividends as positive cash returned to shareholders, so the
extractor flips the sign before the engine discounts.
"""

from __future__ import annotations

from decimal import Decimal

from portfolio_thesis_engine.forecast.schemas import ThreeStatementProjection


def extract_dividend_stream(
    projection: ThreeStatementProjection,
) -> list[tuple[int, Decimal, Decimal]]:
    """Return ``(year, dividend_total, shares_outstanding)`` per year.

    Pairs ``projection.cash_flow`` with ``projection.income_statement``
    on positional index so year numbers align. ``dividend_total`` is
    the absolute value of ``cash_flow[y].dividends_paid``.
    """
    stream: list[tuple[int, Decimal, Decimal]] = []
    for cf_year, is_year in zip(
        projection.cash_flow, projection.income_statement
    ):
        dividend_total = abs(cf_year.dividends_paid)
        stream.append((cf_year.year, dividend_total, is_year.shares_outstanding))
    return stream


def compute_dividend_per_share(
    dividend_total: Decimal, shares_outstanding: Decimal
) -> Decimal:
    """DPS = dividend_total / shares_outstanding (0 when shares ≤ 0)."""
    if shares_outstanding <= 0:
        return Decimal("0")
    return dividend_total / shares_outstanding


__all__ = ["compute_dividend_per_share", "extract_dividend_stream"]
