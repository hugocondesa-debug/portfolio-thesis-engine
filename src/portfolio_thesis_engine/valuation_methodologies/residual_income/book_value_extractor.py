"""Extract book-value + net-income streams from a :class:`ThreeStatementProjection`.

RI needs **beginning** book value per year. The BS projections store
**ending** book values per year. This module converts: ``Y1 begin =
base_equity`` (from canonical state); ``Yn begin = Y(n-1) ending``.
"""

from __future__ import annotations

from decimal import Decimal

from portfolio_thesis_engine.forecast.schemas import ThreeStatementProjection


def extract_book_value_stream(
    projection: ThreeStatementProjection,
) -> list[tuple[int, Decimal, Decimal, Decimal]]:
    """Return ``(year, ending_book_value, net_income, shares)`` per year.

    Pairs ``projection.balance_sheet`` with ``projection.income_statement``
    positionally so year numbers align.
    """
    stream: list[tuple[int, Decimal, Decimal, Decimal]] = []
    for bs_year, is_year in zip(
        projection.balance_sheet, projection.income_statement
    ):
        stream.append(
            (
                bs_year.year,
                bs_year.equity,
                is_year.net_income,
                is_year.shares_outstanding,
            )
        )
    return stream


def compute_beginning_book_values(
    base_equity: Decimal,
    ending_equities: list[Decimal],
) -> list[Decimal]:
    """Convert ``[ending_Y1, ending_Y2, ...]`` → ``[begin_Y1, begin_Y2, ...]``.

    ``begin_Y1 = base_equity``; ``begin_Yn = ending_Y(n-1)`` for n ≥ 2.
    """
    beginnings: list[Decimal] = [base_equity]
    for ending in ending_equities[:-1]:
        beginnings.append(ending)
    return beginnings


__all__ = ["compute_beginning_book_values", "extract_book_value_stream"]
