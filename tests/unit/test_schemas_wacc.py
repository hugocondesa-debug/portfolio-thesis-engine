"""Unit tests for schemas/wacc.py."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from portfolio_thesis_engine.schemas.common import Profile
from portfolio_thesis_engine.schemas.wacc import (
    CapitalStructure,
    CostOfCapitalInputs,
    ScenarioDriversManual,
    WACCInputs,
)


def _complete_inputs(**overrides) -> dict:
    """Valid WACCInputs init kwargs; override fields per test."""
    base = {
        "ticker": "1846.HK",
        "profile": Profile.P1_INDUSTRIAL,
        "valuation_date": "2025-03-31",
        "current_price": Decimal("12.50"),
        "cost_of_capital": CostOfCapitalInputs(
            risk_free_rate=Decimal("3.5"),
            equity_risk_premium=Decimal("6.0"),
            beta=Decimal("1.2"),
            cost_of_debt_pretax=Decimal("4.5"),
            tax_rate_for_wacc=Decimal("16.5"),
        ),
        "capital_structure": CapitalStructure(
            debt_weight=Decimal("30"), equity_weight=Decimal("70")
        ),
        "scenarios": {
            "bear": ScenarioDriversManual(
                probability=Decimal("25"),
                revenue_cagr_explicit_period=Decimal("3"),
                terminal_growth=Decimal("2"),
                terminal_operating_margin=Decimal("15"),
            ),
            "base": ScenarioDriversManual(
                probability=Decimal("50"),
                revenue_cagr_explicit_period=Decimal("8"),
                terminal_growth=Decimal("2.5"),
                terminal_operating_margin=Decimal("18"),
            ),
            "bull": ScenarioDriversManual(
                probability=Decimal("25"),
                revenue_cagr_explicit_period=Decimal("12"),
                terminal_growth=Decimal("3"),
                terminal_operating_margin=Decimal("22"),
            ),
        },
    }
    return {**base, **overrides}


# ======================================================================
# CapitalStructure — weights must sum to 100 ± 0.5
# ======================================================================


class TestCapitalStructure:
    def test_valid_two_component(self) -> None:
        cs = CapitalStructure(debt_weight=Decimal("30"), equity_weight=Decimal("70"))
        assert cs.preferred_weight == Decimal("0")

    def test_valid_three_component(self) -> None:
        cs = CapitalStructure(
            debt_weight=Decimal("25"),
            equity_weight=Decimal("70"),
            preferred_weight=Decimal("5"),
        )
        assert cs.preferred_weight == Decimal("5")

    def test_sum_exceeds_tolerance_raises(self) -> None:
        with pytest.raises(ValidationError, match="sum to 110"):
            CapitalStructure(debt_weight=Decimal("40"), equity_weight=Decimal("70"))

    def test_sum_too_low_raises(self) -> None:
        with pytest.raises(ValidationError, match="sum to 90"):
            CapitalStructure(debt_weight=Decimal("20"), equity_weight=Decimal("70"))

    def test_sum_within_tolerance_accepted(self) -> None:
        # 100.4 is within ±0.5
        cs = CapitalStructure(debt_weight=Decimal("30.2"), equity_weight=Decimal("70.2"))
        assert cs.debt_weight == Decimal("30.2")


# ======================================================================
# ScenarioDriversManual
# ======================================================================


class TestScenarioDriversManual:
    def test_valid(self) -> None:
        s = ScenarioDriversManual(
            probability=Decimal("50"),
            revenue_cagr_explicit_period=Decimal("8"),
            terminal_growth=Decimal("2.5"),
            terminal_operating_margin=Decimal("18"),
        )
        assert s.wacc_override is None

    def test_probability_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ScenarioDriversManual(
                probability=Decimal("150"),
                revenue_cagr_explicit_period=Decimal("0"),
                terminal_growth=Decimal("0"),
                terminal_operating_margin=Decimal("0"),
            )

    def test_wacc_override_accepted(self) -> None:
        s = ScenarioDriversManual(
            probability=Decimal("50"),
            revenue_cagr_explicit_period=Decimal("8"),
            terminal_growth=Decimal("2.5"),
            terminal_operating_margin=Decimal("18"),
            wacc_override=Decimal("9.5"),
        )
        assert s.wacc_override == Decimal("9.5")


# ======================================================================
# WACCInputs — derived wacc/coe + validators
# ======================================================================


class TestWACCInputsDerivation:
    def test_cost_of_equity_capm(self) -> None:
        w = WACCInputs(**_complete_inputs())
        # 3.5 + 1.2 × 6.0 = 10.7
        assert w.cost_of_equity == Decimal("10.70")

    def test_wacc_weighted_after_tax(self) -> None:
        w = WACCInputs(**_complete_inputs())
        # 0.7 × 10.7 + 0.3 × 4.5 × (1 − 0.165) = 7.49 + 1.12725 = 8.61725
        assert w.wacc == Decimal("8.6172500")

    def test_zero_debt_wacc_equals_cost_of_equity(self) -> None:
        w = WACCInputs(
            **_complete_inputs(
                capital_structure=CapitalStructure(
                    debt_weight=Decimal("0"), equity_weight=Decimal("100")
                )
            )
        )
        assert w.wacc == w.cost_of_equity

    def test_yaml_roundtrip_preserves_inputs_and_derived(self) -> None:
        w = WACCInputs(**_complete_inputs())
        loaded = WACCInputs.from_yaml(w.to_yaml())
        assert loaded == w
        assert loaded.wacc == w.wacc
        assert loaded.cost_of_equity == w.cost_of_equity


class TestWACCInputsValidators:
    def test_rejects_unknown_scenario_label(self) -> None:
        inputs = _complete_inputs()
        inputs["scenarios"]["disaster"] = inputs["scenarios"]["base"]
        with pytest.raises(ValidationError, match="Unknown scenario labels"):
            WACCInputs(**inputs)

    def test_rejects_empty_scenarios(self) -> None:
        with pytest.raises(ValidationError, match="At least one scenario"):
            WACCInputs(**_complete_inputs(scenarios={}))

    def test_rejects_probabilities_not_summing_to_100(self) -> None:
        inputs = _complete_inputs()
        inputs["scenarios"]["base"] = ScenarioDriversManual(
            probability=Decimal("20"),  # brings total to 70, not 100
            revenue_cagr_explicit_period=Decimal("8"),
            terminal_growth=Decimal("2.5"),
            terminal_operating_margin=Decimal("18"),
        )
        with pytest.raises(ValidationError, match="sum to 70"):
            WACCInputs(**inputs)

    def test_probabilities_within_tolerance_accepted(self) -> None:
        # 99.7 is within ±0.5
        inputs = _complete_inputs()
        inputs["scenarios"]["bear"] = ScenarioDriversManual(
            probability=Decimal("24.9"),
            revenue_cagr_explicit_period=Decimal("3"),
            terminal_growth=Decimal("2"),
            terminal_operating_margin=Decimal("15"),
        )
        inputs["scenarios"]["base"] = ScenarioDriversManual(
            probability=Decimal("49.9"),
            revenue_cagr_explicit_period=Decimal("8"),
            terminal_growth=Decimal("2.5"),
            terminal_operating_margin=Decimal("18"),
        )
        inputs["scenarios"]["bull"] = ScenarioDriversManual(
            probability=Decimal("24.9"),
            revenue_cagr_explicit_period=Decimal("12"),
            terminal_growth=Decimal("3"),
            terminal_operating_margin=Decimal("22"),
        )
        w = WACCInputs(**inputs)
        # 99.7 accepted
        assert len(w.scenarios) == 3

    def test_accepts_single_scenario(self) -> None:
        inputs = _complete_inputs(
            scenarios={
                "base": ScenarioDriversManual(
                    probability=Decimal("100"),
                    revenue_cagr_explicit_period=Decimal("8"),
                    terminal_growth=Decimal("2.5"),
                    terminal_operating_margin=Decimal("18"),
                )
            }
        )
        w = WACCInputs(**inputs)
        assert set(w.scenarios) == {"base"}

    def test_explicit_period_default(self) -> None:
        w = WACCInputs(**_complete_inputs())
        assert w.explicit_period_years == 10

    def test_explicit_period_out_of_range_rejected(self) -> None:
        with pytest.raises(ValidationError):
            WACCInputs(**_complete_inputs(explicit_period_years=50))
