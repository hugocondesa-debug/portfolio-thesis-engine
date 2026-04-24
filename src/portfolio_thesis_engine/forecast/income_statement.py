"""Phase 2 Sprint 4A-beta — Income Statement forecast engine.

Projects revenue, operating margin, interest, tax, net income, EPS for
N years given a growth pattern + linear margin fade toward a terminal
target. Works purely on Decimals; driven by the scenario drivers
resolved upstream (``base_drivers`` + ``driver_overrides``).
"""

from __future__ import annotations

from decimal import Decimal

from portfolio_thesis_engine.forecast.schemas import IncomeStatementYear


def _take(pattern: list[Decimal] | None, index: int) -> Decimal | None:
    """Return ``pattern[index]`` when the index is in range, else
    ``pattern[-1]`` (pattern extends flat beyond its declared length).
    ``None`` when the pattern itself is empty / None."""
    if not pattern:
        return None
    if index < len(pattern):
        return pattern[index]
    return pattern[-1]


def forecast_income_statement(
    *,
    base_year_revenue: Decimal,
    base_year_operating_margin: Decimal,
    base_year_shares_outstanding: Decimal,
    growth_pattern: list[Decimal],
    margin_target_terminal: Decimal,
    margin_fade_years: int,
    tax_rate: Decimal,
    years: int = 5,
    shares_outstanding_evolution: list[Decimal] | None = None,
    interest_income_per_year: list[Decimal] | None = None,
    interest_expense_per_year: list[Decimal] | None = None,
) -> list[IncomeStatementYear]:
    """Project IS year-by-year for N years.

    Margin fades linearly from ``base_year_operating_margin`` to
    ``margin_target_terminal`` over ``margin_fade_years`` (progress
    capped at 1.0 thereafter). Growth pattern shorter than ``years``
    is held flat at its last value; absent pattern defaults to 5%.
    """
    projections: list[IncomeStatementYear] = []

    current_revenue = base_year_revenue
    default_growth = Decimal("0.05")

    for y in range(1, years + 1):
        taken_growth = _take(growth_pattern, y - 1)
        growth_rate = taken_growth if taken_growth is not None else default_growth
        new_revenue = current_revenue * (Decimal("1") + growth_rate)

        fade_denom = max(margin_fade_years, 1)
        progress = min(Decimal(y) / Decimal(fade_denom), Decimal("1"))
        current_margin = base_year_operating_margin + (
            (margin_target_terminal - base_year_operating_margin) * progress
        )

        operating_income = new_revenue * current_margin
        taken_int_inc = _take(interest_income_per_year, y - 1)
        interest_income = taken_int_inc if taken_int_inc is not None else Decimal("0")
        taken_int_exp = _take(interest_expense_per_year, y - 1)
        interest_expense = (
            taken_int_exp if taken_int_exp is not None else Decimal("0")
        )
        pre_tax_income = operating_income + interest_income - interest_expense
        tax_expense = max(Decimal("0"), pre_tax_income * tax_rate)
        net_income = pre_tax_income - tax_expense

        shares = _take(shares_outstanding_evolution, y - 1)
        if shares is None:
            shares = base_year_shares_outstanding

        eps = net_income / shares if shares > 0 else Decimal("0")

        projections.append(
            IncomeStatementYear(
                year=y,
                revenue=new_revenue,
                revenue_growth_rate=growth_rate,
                operating_margin=current_margin,
                operating_income=operating_income,
                interest_expense=interest_expense,
                interest_income=interest_income,
                pre_tax_income=pre_tax_income,
                tax_rate=tax_rate,
                tax_expense=tax_expense,
                net_income=net_income,
                shares_outstanding=shares,
                eps=eps,
            )
        )

        current_revenue = new_revenue

    return projections


__all__ = ["forecast_income_statement"]
