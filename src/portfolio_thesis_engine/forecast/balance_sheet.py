"""Phase 2 Sprint 4A-beta — Balance Sheet forecast engine.

Roll-forward BS year-by-year given per-year capex, D&A, M&A, revenue
(for WC sizing), NI, dividends, buybacks, and debt deltas. Cash is
**not** solved here — it's derived by :mod:`cash_flow` + propagated by
:mod:`iterative_solver`. The BS rows returned by this module treat
``cash`` as a placeholder equal to ``base_year_cash`` so downstream
callers know to overwrite it.
"""

from __future__ import annotations

from decimal import Decimal

from portfolio_thesis_engine.forecast.schemas import BalanceSheetYear


def forecast_balance_sheet(
    *,
    base_year_ppe: Decimal,
    base_year_goodwill: Decimal,
    base_year_wc: Decimal,
    base_year_cash: Decimal,
    base_year_debt: Decimal,
    base_year_equity: Decimal,
    base_year_total_assets: Decimal,
    capex_per_year: list[Decimal],
    da_per_year: list[Decimal],
    ma_deployment_per_year: list[Decimal],
    revenue_per_year: list[Decimal],
    wc_to_revenue_target: Decimal,
    net_income_per_year: list[Decimal],
    dividends_per_year: list[Decimal],
    buybacks_per_year: list[Decimal],
    debt_delta_per_year: list[Decimal],
    years: int = 5,
) -> list[BalanceSheetYear]:
    """Roll BS forward N years.

    PPE: prior + capex − D&A. Goodwill: prior + M&A deployment.
    Working capital: ``revenue_per_year[y] × wc_to_revenue_target``.
    Debt: prior + delta (positive = issuance, negative = repayment).
    Equity: prior + NI − dividends − buybacks.
    Cash: held at ``base_year_cash`` — overwritten by the solver.
    """
    projections: list[BalanceSheetYear] = []

    ppe = base_year_ppe
    goodwill = base_year_goodwill
    debt = base_year_debt
    equity = base_year_equity

    for y in range(1, years + 1):
        idx = y - 1
        ppe = ppe + capex_per_year[idx] - da_per_year[idx]
        goodwill = goodwill + ma_deployment_per_year[idx]
        wc = revenue_per_year[idx] * wc_to_revenue_target
        debt = debt + debt_delta_per_year[idx]
        equity = (
            equity
            + net_income_per_year[idx]
            - dividends_per_year[idx]
            - buybacks_per_year[idx]
        )

        cash = base_year_cash  # Placeholder — solver updates.
        total_assets = ppe + goodwill + wc + cash

        projections.append(
            BalanceSheetYear(
                year=y,
                ppe_net=ppe,
                goodwill=goodwill,
                working_capital_net=wc,
                cash=cash,
                total_assets=total_assets,
                debt=debt,
                equity=equity,
            )
        )

    return projections


__all__ = ["forecast_balance_sheet"]
