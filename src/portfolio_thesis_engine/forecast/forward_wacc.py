"""Phase 2 Sprint 4A-beta — per-year WACC.

Reflects evolving capital structure: when a scenario's debt policy
triggers ``LEVER_UP``, the tax-shielded cost of debt entering the
weighted average lowers WACC below cost of equity. For zero-debt
scenarios, WACC collapses to the cost of equity.

Sprint 4A-beta.1 — accepts a ``WACCContext`` protocol bridging the
Sprint-3 :class:`WACCGenerator` output (cost_of_equity_final,
cost_of_debt_aftertax, marginal_tax_rate, wacc) into the forward
projection. The ``fallback_base_wacc`` is used only when no context
is supplied (tests, headless orchestration).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Protocol

from portfolio_thesis_engine.forecast.schemas import (
    BalanceSheetYear,
    IncomeStatementYear,
)


class WACCContext(Protocol):
    """Adapter surface for the Sprint-3 :class:`WACCComputation`.

    The protocol exposes the four scalars forward_wacc needs:

    - ``cost_of_equity`` — final after currency-regime conversion.
    - ``cost_of_debt`` — after-tax (zero when the company has no debt).
    - ``tax_rate`` — marginal rate used for the CoD tax shield when
      the forward balance sheet adds debt mid-horizon.
    - ``base_wacc`` — the Sprint-3 overall WACC, returned verbatim for
      degenerate years (equity + debt ≤ 0).
    """

    cost_of_equity: Decimal
    cost_of_debt: Decimal
    tax_rate: Decimal
    base_wacc: Decimal


def compute_forward_wacc(
    bs_year: BalanceSheetYear,
    is_year: IncomeStatementYear,
    wacc_context: WACCContext | None = None,
    fallback_base_wacc: Decimal = Decimal("0.08"),
) -> Decimal:
    """Return the weighted-average cost of capital for this year.

    When ``wacc_context`` is supplied (the normal production path), the
    equity/debt weights are taken from the projected balance sheet and
    applied to the context's CoE / after-tax CoD. When absent (unit
    tests, fast-path smoke), the function returns ``fallback_base_wacc``
    — preserves the pre-Sprint 4A-beta.1 behaviour.
    """
    _ = is_year  # Reserved for future dynamic-CoE extensions.

    if wacc_context is None:
        return fallback_base_wacc

    total_capital = bs_year.equity + bs_year.debt
    if total_capital <= 0:
        return wacc_context.base_wacc

    equity_weight = bs_year.equity / total_capital
    debt_weight = bs_year.debt / total_capital

    # context.cost_of_debt is already after-tax per the Sprint-3 schema.
    # If a downstream adapter ever stores the pre-tax value, it should
    # apply (1 - tax) before constructing the context.
    return (
        equity_weight * wacc_context.cost_of_equity
        + debt_weight * wacc_context.cost_of_debt
    )


__all__ = ["WACCContext", "compute_forward_wacc"]
