"""Residual Income output schemas — EV = BookValue + PV(RI) + PV(terminal)."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field

from portfolio_thesis_engine.schemas.base import BaseSchema


class RIYear(BaseSchema):
    """One year of Residual Income projection.

    ``residual_income = net_income − cost_of_equity × beginning_book_value``.
    Positive RI = earning above CoE on invested book equity; negative
    RI = value destruction.
    """

    year: int
    net_income: Decimal
    beginning_book_value: Decimal
    required_return: Decimal
    residual_income: Decimal
    discount_factor: Decimal
    pv_residual_income: Decimal


class RIProjection(BaseSchema):
    """Full Residual Income output for one scenario.

    ``enterprise_value = base_book_value + sum_pv_residual_income + terminal_pv``
    where the terminal tail is Gordon Growth on the last-year RI.
    """

    scenario_name: str
    methodology: Literal["RESIDUAL_INCOME"] = "RESIDUAL_INCOME"
    base_year_label: str
    projection_years: int

    base_book_value: Decimal

    years: list[RIYear] = Field(default_factory=list)

    terminal_residual_income: Decimal
    terminal_growth_rate: Decimal
    terminal_discount_rate: Decimal
    terminal_value: Decimal
    terminal_pv: Decimal

    sum_pv_residual_income: Decimal
    enterprise_value: Decimal
    equity_value: Decimal
    shares_outstanding_terminal: Decimal
    fair_value_per_share: Decimal

    warnings: list[str] = Field(default_factory=list)


__all__ = ["RIProjection", "RIYear"]
