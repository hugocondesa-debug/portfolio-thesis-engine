"""Phase 2 Sprint 4A-beta — forecast output schemas.

Five Pydantic classes + two aggregates cover the three-statement
projection per scenario and the multi-scenario ``ForecastResult`` that
the CLI / persistence layer serializes. Model-validators enforce core
deterministic identities (``EPS = NI / shares``,
``Δcash = CFO + CFI + CFF + fx``). The balance-sheet identity is
checked loosely — full accounting is done inside the solver via
roll-forward logic, not via per-year schema validation.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from pydantic import Field, model_validator

from portfolio_thesis_engine.schemas.base import BaseSchema


class IncomeStatementYear(BaseSchema):
    """One year of IS projection."""

    year: int
    revenue: Decimal
    revenue_growth_rate: Decimal
    operating_margin: Decimal
    operating_income: Decimal
    interest_expense: Decimal = Decimal("0")
    interest_income: Decimal = Decimal("0")
    pre_tax_income: Decimal
    tax_rate: Decimal
    tax_expense: Decimal
    net_income: Decimal
    shares_outstanding: Decimal
    eps: Decimal

    @model_validator(mode="after")
    def _derivation_checks(self) -> "IncomeStatementYear":
        implied_oi = self.revenue * self.operating_margin
        tol = abs(self.revenue) * Decimal("0.001")
        if abs(implied_oi - self.operating_income) > tol:
            raise ValueError(
                f"OI {self.operating_income} vs Revenue × OM {implied_oi}"
            )
        if self.shares_outstanding > 0:
            implied_eps = self.net_income / self.shares_outstanding
            # Wider tolerance for EPS — quantization on large share counts.
            if abs(implied_eps - self.eps) > Decimal("0.01"):
                raise ValueError(f"EPS {self.eps} vs NI/shares {implied_eps}")
        return self


class BalanceSheetYear(BaseSchema):
    """One year of BS projection."""

    year: int
    ppe_net: Decimal
    goodwill: Decimal
    working_capital_net: Decimal
    cash: Decimal
    total_assets: Decimal
    debt: Decimal
    equity: Decimal


class CashFlowYear(BaseSchema):
    """One year of CF projection.

    All component fields store the *signed* amounts that flow into CFO/
    CFI/CFF so ``net_change_cash = cfo + cfi + cff + fx_effect`` holds
    as an arithmetic identity. CFI components (``capex``,
    ``ma_deployment``) and CFF outflows (``dividends_paid``,
    ``buybacks_executed``) are stored as **negative** values; ``debt_issued``
    is positive, ``debt_repaid`` is positive (the CFF line subtracts it).
    """

    year: int
    cfo: Decimal
    cfi: Decimal
    cff: Decimal
    capex: Decimal
    ma_deployment: Decimal
    dividends_paid: Decimal
    buybacks_executed: Decimal
    debt_issued: Decimal
    debt_repaid: Decimal
    net_interest: Decimal
    fx_effect: Decimal = Decimal("0")
    net_change_cash: Decimal

    @model_validator(mode="after")
    def _check_sum(self) -> "CashFlowYear":
        implied = self.cfo + self.cfi + self.cff + self.fx_effect
        # Tolerance: 1% of |CFO|, with floor of 1.0 so zero-CFO years
        # don't trigger spurious failures from Decimal noise.
        tol = max(abs(self.cfo) * Decimal("0.01"), Decimal("1"))
        if abs(implied - self.net_change_cash) > tol:
            raise ValueError(
                f"ΔCash {self.net_change_cash} != CFO+CFI+CFF+fx {implied}"
            )
        return self


class ForwardRatiosYear(BaseSchema):
    """Derived ratios for one year."""

    year: int
    per_at_market_price: Decimal | None = None
    per_at_fair_value: Decimal | None = None
    fcf_yield_at_market: Decimal | None = None
    ev_ebitda: Decimal | None = None
    roic: Decimal | None = None
    roe: Decimal | None = None
    debt_to_ebitda: Decimal | None = None
    wacc_applied: Decimal | None = None


class ThreeStatementProjection(BaseSchema):
    """Full 5-year (or N-year) projection for one scenario."""

    scenario_name: str
    scenario_probability: Decimal = Decimal("0")
    base_year_label: str
    projection_years: int

    income_statement: list[IncomeStatementYear] = Field(default_factory=list)
    balance_sheet: list[BalanceSheetYear] = Field(default_factory=list)
    cash_flow: list[CashFlowYear] = Field(default_factory=list)
    forward_ratios: list[ForwardRatiosYear] = Field(default_factory=list)

    solver_convergence: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class ForecastResult(BaseSchema):
    """All-scenarios forecast for one ticker."""

    ticker: str
    generated_at: str
    projections: list[ThreeStatementProjection] = Field(default_factory=list)
    probability_weighted_ev: Decimal | None = None
    expected_forward_eps_y1: Decimal | None = None
    expected_forward_per_y1: Decimal | None = None


__all__ = [
    "BalanceSheetYear",
    "CashFlowYear",
    "ForecastResult",
    "ForwardRatiosYear",
    "IncomeStatementYear",
    "ThreeStatementProjection",
]
