"""Shared synthetic :class:`ThreeStatementProjection` builder.

Lives in ``tests/fixtures`` so DDM, Residual Income, and any future
methodology test suite (FFO, etc.) can share a single source of truth
for projection construction. Per Sprint 4B Risk #6: avoids the ~80-line
``_synthetic_projection`` helper duplicating across files.
"""

from __future__ import annotations

from decimal import Decimal

from portfolio_thesis_engine.forecast.schemas import (
    BalanceSheetYear,
    CashFlowYear,
    ForwardRatiosYear,
    IncomeStatementYear,
    ThreeStatementProjection,
)


def build_synthetic_projection(
    *,
    dividends_per_year: list[Decimal] | None = None,
    net_income_per_year: list[Decimal] | None = None,
    equity_per_year: list[Decimal] | None = None,
    shares_outstanding: Decimal = Decimal("100_000_000"),
    revenue: Decimal = Decimal("200_000_000"),
    operating_margin: Decimal = Decimal("0.30"),
    tax_rate: Decimal = Decimal("0.20"),
    scenario_name: str = "test_base",
    base_year_label: str = "FY2024",
    years: int | None = None,
) -> ThreeStatementProjection:
    """Build a synthetic three-statement projection for unit tests.

    Defaults model a stable 5-year mid-cap: flat 200M revenue, 30%
    operating margin, $50M net income, $920M equity. Override any of
    the per-year lists to model dividend/equity/NI evolution; the
    helper keeps year counts in sync (raising if mismatched).

    ``CashFlowYear.dividends_paid`` is stored **negative** (CFO sign
    convention) — DDM extractor flips it. Tests should pass positive
    magnitudes to ``dividends_per_year``.
    """
    if years is None:
        candidates = [dividends_per_year, net_income_per_year, equity_per_year]
        non_none = [c for c in candidates if c is not None]
        years = len(non_none[0]) if non_none else 5

    if dividends_per_year is None:
        dividends_per_year = [Decimal("0")] * years
    if net_income_per_year is None:
        net_income_per_year = [Decimal("50_000_000")] * years
    if equity_per_year is None:
        equity_per_year = [Decimal("920_000_000")] * years

    if not (
        len(dividends_per_year) == years
        and len(net_income_per_year) == years
        and len(equity_per_year) == years
    ):
        raise ValueError(
            "dividends_per_year, net_income_per_year, equity_per_year "
            "lengths must all equal `years`."
        )

    operating_income = revenue * operating_margin
    pre_tax_income = operating_income
    tax_expense = pre_tax_income * tax_rate

    is_list: list[IncomeStatementYear] = []
    bs_list: list[BalanceSheetYear] = []
    cf_list: list[CashFlowYear] = []
    fr_list: list[ForwardRatiosYear] = []

    for y in range(1, years + 1):
        idx = y - 1
        ni = net_income_per_year[idx]
        eps = ni / shares_outstanding if shares_outstanding > 0 else Decimal("0")
        is_list.append(
            IncomeStatementYear(
                year=y,
                revenue=revenue,
                revenue_growth_rate=Decimal("0"),
                operating_margin=operating_margin,
                operating_income=operating_income,
                pre_tax_income=pre_tax_income,
                tax_rate=tax_rate,
                tax_expense=tax_expense,
                net_income=ni,
                shares_outstanding=shares_outstanding,
                eps=eps,
            )
        )

        equity = equity_per_year[idx]
        bs_list.append(
            BalanceSheetYear(
                year=y,
                ppe_net=Decimal("500_000_000"),
                goodwill=Decimal("100_000_000"),
                working_capital_net=Decimal("20_000_000"),
                cash=Decimal("300_000_000"),
                total_assets=Decimal("920_000_000"),
                debt=Decimal("0"),
                equity=equity,
            )
        )

        div_outflow = -dividends_per_year[idx]
        cfo = Decimal("50_000_000")
        cfi = Decimal("-30_000_000")
        cff = div_outflow
        cf_list.append(
            CashFlowYear(
                year=y,
                cfo=cfo,
                cfi=cfi,
                cff=cff,
                capex=Decimal("-30_000_000"),
                ma_deployment=Decimal("0"),
                dividends_paid=div_outflow,
                buybacks_executed=Decimal("0"),
                debt_issued=Decimal("0"),
                debt_repaid=Decimal("0"),
                net_interest=Decimal("0"),
                fx_effect=Decimal("0"),
                net_change_cash=cfo + cfi + cff,
            )
        )

        fr_list.append(ForwardRatiosYear(year=y))

    return ThreeStatementProjection(
        scenario_name=scenario_name,
        base_year_label=base_year_label,
        projection_years=years,
        income_statement=is_list,
        balance_sheet=bs_list,
        cash_flow=cf_list,
        forward_ratios=fr_list,
        solver_convergence={"converged": True, "iterations": 1},
    )


__all__ = ["build_synthetic_projection"]
