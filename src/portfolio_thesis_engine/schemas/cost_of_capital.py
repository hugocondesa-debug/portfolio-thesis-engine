"""Phase 2 Sprint 3 — Cost-of-capital schemas.

Auto-generated WACC following Damodaran's framework:
bottom-up levered beta, CRP weighted by operational revenue geography,
synthetic-rating-based cost of debt, currency regime detection for
local-vs-USD consistency. Separate from the legacy ``WACCInputs``
(which stays the manual ingestion path via ``wacc_inputs.md``).
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field

from portfolio_thesis_engine.schemas.base import BaseSchema


_CurrencyRegime = Literal["DEVELOPED", "HIGH_INFLATION"]


class CostOfEquityInputs(BaseSchema):
    """All inputs + derived values for the CAPM cost of equity."""

    target_ticker: str
    listing_currency: str

    risk_free_rate: Decimal
    risk_free_source: str

    industry_key: str
    industry_unlevered_beta: Decimal
    debt_to_equity: Decimal
    marginal_tax_rate: Decimal
    levered_beta: Decimal

    mature_market_erp: Decimal
    mature_market: str = "US"

    revenue_geography: dict[str, Decimal] = Field(default_factory=dict)
    country_crp: dict[str, Decimal] = Field(default_factory=dict)
    weighted_crp: Decimal = Decimal("0")

    inflation_local: Decimal | None = None
    inflation_us: Decimal = Decimal("0.024")
    inflation_differential_abs: Decimal | None = None
    currency_regime: _CurrencyRegime = "DEVELOPED"
    requires_usd_conversion: bool = False

    cost_of_equity_base: Decimal
    cost_of_equity_final: Decimal


class CostOfDebtInputs(BaseSchema):
    """Synthetic-rating cost of debt. When the target has zero
    financial debt :attr:`is_applicable` is ``False`` and WACC reduces
    to equity-only."""

    target_ticker: str
    listing_currency: str
    risk_free_rate: Decimal

    ebit: Decimal | None = None
    interest_expense: Decimal | None = None
    interest_coverage_ratio: Decimal | None = None

    synthetic_rating: str | None = None
    rating_spread: Decimal | None = None

    cost_of_debt_pretax: Decimal | None = None
    marginal_tax_rate: Decimal
    cost_of_debt_aftertax: Decimal | None = None

    is_applicable: bool = True
    rationale: str | None = None


class WACCComputation(BaseSchema):
    """Auto-generated WACC (equity-weighted CoE + debt-weighted CoD)
    with full audit trail. Additive alongside any manual
    :class:`WACCInputs` loaded from ``wacc_inputs.md``."""

    target_ticker: str
    base_currency: str

    cost_of_equity: CostOfEquityInputs
    cost_of_debt: CostOfDebtInputs

    equity_market_value: Decimal | None = None
    debt_book_value: Decimal = Decimal("0")
    total_value: Decimal | None = None
    equity_weight: Decimal
    debt_weight: Decimal

    wacc: Decimal
    wacc_audit_narrative: str

    manual_wacc: Decimal | None = None
    manual_vs_computed_bps: int | None = None


__all__ = [
    "CostOfEquityInputs",
    "CostOfDebtInputs",
    "WACCComputation",
]
