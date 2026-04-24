"""DDM output schemas — per-scenario projection of dividend stream + PV."""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field

from portfolio_thesis_engine.schemas.base import BaseSchema


class DDMYear(BaseSchema):
    """One year of DDM projection."""

    year: int
    dividend_total: Decimal
    dividend_per_share: Decimal
    shares_outstanding: Decimal
    cost_of_equity: Decimal
    discount_factor: Decimal
    pv_dividend: Decimal


class DDMProjection(BaseSchema):
    """Full DDM output for one scenario.

    ``enterprise_value`` equals ``equity_value`` for DDM (the model is
    inherently an equity-only valuation — no debt or minority-interest
    bridge). ``shares_outstanding_terminal`` is the last projected year's
    share count so buyback schedules that reduce shares over the horizon
    produce a higher per-share value.
    """

    scenario_name: str
    methodology: Literal["DDM"] = "DDM"
    base_year_label: str
    projection_years: int

    years: list[DDMYear] = Field(default_factory=list)

    terminal_dividend: Decimal
    terminal_growth_rate: Decimal
    terminal_discount_rate: Decimal
    terminal_value: Decimal
    terminal_pv: Decimal

    enterprise_value: Decimal
    equity_value: Decimal
    shares_outstanding_terminal: Decimal
    fair_value_per_share: Decimal

    warnings: list[str] = Field(default_factory=list)


__all__ = ["DDMProjection", "DDMYear"]
