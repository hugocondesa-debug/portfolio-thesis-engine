"""WACC inputs — parsed from ``wacc_inputs.md`` and consumed by valuation.

Phase 1 scope: one :class:`WACCInputs` per company carries identity,
cost-of-capital components, capital structure, and per-scenario drivers.
WACC and cost of equity are **computed** from the components (CAPM for
equity, after-tax weighted average for WACC) so there's a single source
of truth; callers never set ``wacc`` or ``cost_of_equity`` directly.

Validators:

- capital_structure weights sum to 100 (±0.5)
- per-scenario probabilities sum to 100 (±0.5)
- every scenario in :attr:`WACCInputs.scenarios` uses a recognised label
"""

from __future__ import annotations

from decimal import Decimal
from typing import Annotated

from pydantic import Field, model_validator

from portfolio_thesis_engine.schemas.base import BaseSchema
from portfolio_thesis_engine.schemas.common import Money, Percentage, Profile

_ALLOWED_SCENARIO_LABELS = frozenset({"bear", "base", "bull"})
_WEIGHT_SUM_TOLERANCE = Decimal("0.5")
_PROB_SUM_TOLERANCE = Decimal("0.5")


class CostOfCapitalInputs(BaseSchema):
    """CAPM + cost-of-debt inputs (percentages, e.g. 3.5 = 3.5%)."""

    risk_free_rate: Percentage
    equity_risk_premium: Percentage
    beta: Annotated[Decimal, Field(ge=0, le=5, description="Market beta")]
    cost_of_debt_pretax: Percentage
    tax_rate_for_wacc: Annotated[
        Decimal,
        Field(ge=0, le=100, description="Marginal tax rate for WACC, %"),
    ]


class CapitalStructure(BaseSchema):
    """Target weights in percent. Must sum to 100 (±0.5)."""

    debt_weight: Annotated[Decimal, Field(ge=0, le=100)]
    equity_weight: Annotated[Decimal, Field(ge=0, le=100)]
    preferred_weight: Annotated[Decimal, Field(ge=0, le=100)] = Decimal("0")

    @model_validator(mode="after")
    def _weights_sum_to_100(self) -> CapitalStructure:
        total = self.debt_weight + self.equity_weight + self.preferred_weight
        if abs(total - Decimal("100")) > _WEIGHT_SUM_TOLERANCE:
            raise ValueError(
                f"capital_structure weights sum to {total}; expected 100 ± {_WEIGHT_SUM_TOLERANCE}"
            )
        return self


class ScenarioDriversManual(BaseSchema):
    """Per-scenario drivers supplied manually by the analyst."""

    probability: Annotated[Decimal, Field(ge=0, le=100)]
    revenue_cagr_explicit_period: Percentage
    terminal_growth: Percentage
    terminal_operating_margin: Percentage
    # If set, overrides the root WACC for this scenario only.
    wacc_override: Percentage | None = None


class WACCInputs(BaseSchema):
    """Valuation inputs for a single company, parsed from
    ``wacc_inputs.md`` via :mod:`ingestion.wacc_parser`."""

    # --- Identification ------------------------------------------------
    ticker: str = Field(min_length=1, max_length=20)
    profile: Profile
    valuation_date: str = Field(pattern=r"^\d{4}-\d{2}-\d{2}$")
    current_price: Money

    # --- Components (components → computed wacc/coe) -------------------
    cost_of_capital: CostOfCapitalInputs
    capital_structure: CapitalStructure

    # --- Scenarios -----------------------------------------------------
    scenarios: dict[str, ScenarioDriversManual]

    # --- Optional ------------------------------------------------------
    explicit_period_years: Annotated[int, Field(ge=1, le=25)] = 10
    notes: str | None = None

    # --- Derived properties -------------------------------------------
    # Kept as plain `@property` (not pydantic computed_field) so they are
    # NOT included in model_dump output — that would break YAML roundtrip
    # because `extra="forbid"` rejects them on load. Callers read them
    # directly from the object; every caller that needs them has the
    # instance already.
    @property
    def cost_of_equity(self) -> Decimal:
        """CAPM: Rf + β × ERP, in percent."""
        coc = self.cost_of_capital
        return coc.risk_free_rate + coc.beta * coc.equity_risk_premium

    @property
    def wacc(self) -> Decimal:
        """Weighted average cost of capital, in percent.

        WACC = w_e × k_e + w_d × k_d × (1 − t) + w_p × k_e
        (preferred uses equity cost; refined in Phase 2 if needed).
        All inputs are percentages; divide by 100 to convert to fractions
        before multiplying, then multiply back by 100 for the output.
        """
        coc = self.cost_of_capital
        cs = self.capital_structure
        hundred = Decimal("100")
        w_e = cs.equity_weight / hundred
        w_d = cs.debt_weight / hundred
        w_p = cs.preferred_weight / hundred
        k_e = self.cost_of_equity / hundred
        k_d_after_tax = (coc.cost_of_debt_pretax / hundred) * (
            Decimal("1") - coc.tax_rate_for_wacc / hundred
        )
        return (w_e * k_e + w_d * k_d_after_tax + w_p * k_e) * hundred

    # --- Validators ---------------------------------------------------
    @model_validator(mode="after")
    def _scenario_labels_allowed(self) -> WACCInputs:
        unknown = set(self.scenarios) - _ALLOWED_SCENARIO_LABELS
        if unknown:
            raise ValueError(
                f"Unknown scenario labels: {sorted(unknown)}. "
                f"Expected subset of {sorted(_ALLOWED_SCENARIO_LABELS)}"
            )
        if not self.scenarios:
            raise ValueError("At least one scenario is required")
        return self

    @model_validator(mode="after")
    def _probabilities_sum_to_100(self) -> WACCInputs:
        total = sum(
            (s.probability for s in self.scenarios.values()),
            start=Decimal("0"),
        )
        if abs(total - Decimal("100")) > _PROB_SUM_TOLERANCE:
            raise ValueError(
                f"scenario probabilities sum to {total}; expected 100 ± {_PROB_SUM_TOLERANCE}"
            )
        return self
