"""Phase 2 Sprint 4A-beta — per-year WACC.

Reflects evolving capital structure: when a scenario's debt policy
triggers ``LEVER_UP``, the tax-shielded cost of debt entering the
weighted average lowers WACC below cost of equity. For zero-debt
scenarios, WACC collapses to the cost of equity and the ``base_wacc``
argument is returned only when equity + debt is non-positive (i.e.
degenerate projections).
"""

from __future__ import annotations

from decimal import Decimal

from portfolio_thesis_engine.forecast.schemas import (
    BalanceSheetYear,
    IncomeStatementYear,
)


def compute_forward_wacc(
    *,
    bs_year: BalanceSheetYear,
    is_year: IncomeStatementYear,
    base_wacc: Decimal,
    cost_of_equity: Decimal,
    cost_of_debt: Decimal,
    tax_rate: Decimal,
) -> Decimal:
    """Return the weighted-average cost of capital for this year."""
    _ = is_year  # Reserved for future dynamic-CoE extensions.
    total_capital = bs_year.equity + bs_year.debt

    if total_capital <= 0:
        return base_wacc

    equity_weight = bs_year.equity / total_capital
    debt_weight = bs_year.debt / total_capital

    after_tax_cod = cost_of_debt * (Decimal("1") - tax_rate)
    return (equity_weight * cost_of_equity) + (debt_weight * after_tax_cod)


__all__ = ["compute_forward_wacc"]
