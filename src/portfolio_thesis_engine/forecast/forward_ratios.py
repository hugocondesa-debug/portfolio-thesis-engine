"""Phase 2 Sprint 4A-beta — per-year forward ratio computation.

Combines IS + BS + CF rows to produce PER (at market and at fair
value), FCF yield, ROIC, ROE, Debt/EBITDA. WACC field is populated
downstream by :mod:`forward_wacc`; EV/EBITDA is orchestrator-level.
"""

from __future__ import annotations

from decimal import Decimal

from portfolio_thesis_engine.forecast.schemas import (
    BalanceSheetYear,
    CashFlowYear,
    ForwardRatiosYear,
    IncomeStatementYear,
)


def compute_forward_ratios(
    *,
    is_year: IncomeStatementYear,
    bs_year: BalanceSheetYear,
    cf_year: CashFlowYear,
    market_price: Decimal | None,
    fair_value: Decimal | None,
    ebitda_year: Decimal | None = None,
) -> ForwardRatiosYear:
    """Produce one ``ForwardRatiosYear`` from the three-statement slice."""
    per_market: Decimal | None = None
    if market_price is not None and is_year.eps > 0:
        per_market = market_price / is_year.eps

    per_fv: Decimal | None = None
    if fair_value is not None and is_year.eps > 0:
        per_fv = fair_value / is_year.eps

    # FCF = CFO + CFI's capex component (capex already stored negative).
    fcf = cf_year.cfo + cf_year.capex
    fcf_yield: Decimal | None = None
    if market_price is not None and is_year.shares_outstanding > 0:
        market_cap = market_price * is_year.shares_outstanding
        if market_cap > 0:
            fcf_yield = fcf / market_cap

    nopat = is_year.operating_income * (Decimal("1") - is_year.tax_rate)
    ic = bs_year.ppe_net + bs_year.goodwill + bs_year.working_capital_net
    roic = nopat / ic if ic > 0 else None

    roe = is_year.net_income / bs_year.equity if bs_year.equity > 0 else None

    debt_to_ebitda: Decimal | None = None
    if ebitda_year is not None and ebitda_year > 0:
        debt_to_ebitda = bs_year.debt / ebitda_year

    ev_ebitda: Decimal | None = None
    if (
        market_price is not None
        and ebitda_year is not None
        and ebitda_year > 0
        and is_year.shares_outstanding > 0
    ):
        market_cap = market_price * is_year.shares_outstanding
        enterprise_value = market_cap + bs_year.debt - bs_year.cash
        ev_ebitda = enterprise_value / ebitda_year

    return ForwardRatiosYear(
        year=is_year.year,
        per_at_market_price=per_market,
        per_at_fair_value=per_fv,
        fcf_yield_at_market=fcf_yield,
        ev_ebitda=ev_ebitda,
        roic=roic,
        roe=roe,
        debt_to_ebitda=debt_to_ebitda,
        wacc_applied=None,
    )


__all__ = ["compute_forward_ratios"]
