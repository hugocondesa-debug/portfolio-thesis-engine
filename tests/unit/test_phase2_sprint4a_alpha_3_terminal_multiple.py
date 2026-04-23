"""Phase 2 Sprint 4A-alpha.3 regression tests — TERMINAL_MULTIPLE
terminal method.

Schema (3):
- ``test_terminal_multiple_enum_accepted``
- ``test_validator_gordon_requires_terminal_growth``
- ``test_validator_terminal_multiple_requires_metric_and_source``

Engine computation (5):
- ``test_terminal_multiple_ev_ebitda_computation``
- ``test_terminal_multiple_ev_sales_computation``
- ``test_terminal_multiple_peer_median_resolution``
- ``test_terminal_multiple_industry_median_resolution``
- ``test_terminal_multiple_user_specified_requires_value``

Cross-validation (2):
- ``test_terminal_multiple_cross_validation_with_gordon``
- ``test_dcf_3_stage_with_terminal_multiple_produces_different_value_than_gordon``

Rendering (1):
- ``test_markdown_renders_terminal_multiple_computation``

Total: 11 tests.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from portfolio_thesis_engine.cli.valuation_cmd import (
    render_valuation_markdown,
)
from portfolio_thesis_engine.dcf.engine import ValuationEngine
from portfolio_thesis_engine.dcf.p1_engine import PeriodInputs
from portfolio_thesis_engine.dcf.schemas import (
    DCFMethodologyConfig,
    DCFProfile,
    DCFStructure,
    ProfileSelection,
    Scenario,
    ScenarioSet,
    TerminalMethod,
    TerminalValueConfig,
    ValuationMethodology,
    ValuationProfile,
    WACCEvolution,
)


# ======================================================================
# Fixtures
# ======================================================================
def _base_drivers() -> dict:
    return {
        "revenue": {
            "base_year_value": Decimal("1000"),
            "growth_pattern": [Decimal("0.05")] * 5,
            "terminal_growth": Decimal("0.025"),
        },
        "operating_margin": {
            "current": Decimal("0.20"),
            "target_terminal": Decimal("0.20"),
        },
        "tax_rate": {"statutory": Decimal("0.20")},
        "capex_intensity": {
            "current": Decimal("0.05"),
            "target": Decimal("0.05"),
        },
        "working_capital_intensity": {
            "current": Decimal("0"),
            "target": Decimal("0"),
        },
        "depreciation_rate": {"current": Decimal("0.08")},
    }


def _vp(industry_median: Decimal | None = Decimal("10")) -> ValuationProfile:
    return ValuationProfile(
        target_ticker="T",
        profile=ProfileSelection(
            code=DCFProfile.P1_INDUSTRIAL_SERVICES,
            source="USER_OVERRIDE",
            confidence="HIGH",
        ),
        dcf_structure=DCFStructure(
            type="THREE_STAGE", explicit_years=5, fade_years=5
        ),
        wacc_evolution=WACCEvolution(
            stage_3_mature_beta=Decimal("0.7"),
            stage_3_target_leverage=Decimal("0"),
        ),
        terminal_value=TerminalValueConfig(
            cross_check_industry_median=industry_median,
        ),
    )


def _pi(industry_median: Decimal | None = Decimal("10")) -> PeriodInputs:
    return PeriodInputs(
        ticker="T",
        stage_1_wacc=Decimal("0.08"),
        stage_3_wacc=Decimal("0.07"),
        shares_outstanding=Decimal("100"),
        industry_median_ev_ebitda=industry_median,
    )


def _ss(scenarios: list[Scenario]) -> ScenarioSet:
    return ScenarioSet(
        target_ticker="T",
        valuation_profile=DCFProfile.P1_INDUSTRIAL_SERVICES,
        base_year="FY2024",
        base_drivers=_base_drivers(),
        scenarios=scenarios,
    )


def _scenario(methodology: DCFMethodologyConfig) -> Scenario:
    return Scenario(
        name="test",
        probability=Decimal("1"),
        rationale="",
        methodology=methodology,
    )


# ======================================================================
# Schema
# ======================================================================
class TestSchema:
    def test_terminal_multiple_enum_accepted(self) -> None:
        config = DCFMethodologyConfig(
            type="DCF_3_STAGE",
            terminal_method=TerminalMethod.TERMINAL_MULTIPLE,
            terminal_multiple_metric="EV_EBITDA",
            terminal_multiple_source="USER_SPECIFIED",
            terminal_multiple_value=Decimal("10"),
        )
        assert config.terminal_method == TerminalMethod.TERMINAL_MULTIPLE

    def test_validator_gordon_requires_terminal_growth(self) -> None:
        with pytest.raises(ValidationError, match="GORDON_GROWTH"):
            DCFMethodologyConfig(
                type="DCF_3_STAGE",
                terminal_method=TerminalMethod.GORDON_GROWTH,
                terminal_growth=None,
            )

    def test_validator_terminal_multiple_requires_metric_and_source(
        self,
    ) -> None:
        # Missing metric
        with pytest.raises(ValidationError, match="terminal_multiple_metric"):
            DCFMethodologyConfig(
                type="DCF_3_STAGE",
                terminal_method=TerminalMethod.TERMINAL_MULTIPLE,
                terminal_multiple_source="USER_SPECIFIED",
                terminal_multiple_value=Decimal("10"),
            )
        # Missing source
        with pytest.raises(ValidationError, match="terminal_multiple_source"):
            DCFMethodologyConfig(
                type="DCF_3_STAGE",
                terminal_method=TerminalMethod.TERMINAL_MULTIPLE,
                terminal_multiple_metric="EV_EBITDA",
            )


# ======================================================================
# Engine computation
# ======================================================================
class TestEngineComputation:
    def test_terminal_multiple_ev_ebitda_computation(self) -> None:
        methodology = DCFMethodologyConfig(
            type="DCF_3_STAGE",
            explicit_years=5,
            fade_years=5,
            terminal_method=TerminalMethod.TERMINAL_MULTIPLE,
            terminal_multiple_metric="EV_EBITDA",
            terminal_multiple_source="USER_SPECIFIED",
            terminal_multiple_value=Decimal("12"),
        )
        result = ValuationEngine().run(
            valuation_profile=_vp(),
            scenario_set=_ss([_scenario(methodology)]),
            period_inputs=_pi(),
        )
        v = result.scenarios_run[0]
        summary = v.methodology_summary
        assert summary["terminal_method"] == "TERMINAL_MULTIPLE"
        assert summary["terminal_metric"] == "EV_EBITDA"
        assert summary["terminal_multiple_used"] == Decimal("12")
        # TV = metric × multiple
        metric_value = summary["terminal_metric_value"]
        assert v.terminal_value == metric_value * Decimal("12")

    def test_terminal_multiple_ev_sales_computation(self) -> None:
        methodology = DCFMethodologyConfig(
            type="DCF_3_STAGE",
            terminal_method=TerminalMethod.TERMINAL_MULTIPLE,
            terminal_multiple_metric="EV_SALES",
            terminal_multiple_source="USER_SPECIFIED",
            terminal_multiple_value=Decimal("3"),
        )
        result = ValuationEngine().run(
            valuation_profile=_vp(),
            scenario_set=_ss([_scenario(methodology)]),
            period_inputs=_pi(),
        )
        v = result.scenarios_run[0]
        # Terminal metric value should equal terminal-year revenue.
        terminal_revenue = (
            v.fade_projections[-1].revenue
            if v.fade_projections
            else v.explicit_projections[-1].revenue
        )
        assert v.methodology_summary["terminal_metric_value"] == terminal_revenue

    def test_terminal_multiple_peer_median_resolution(self) -> None:
        class FakePeers:
            peer_median = {"ev_to_ebitda": Decimal("15")}

        methodology = DCFMethodologyConfig(
            type="DCF_3_STAGE",
            terminal_method=TerminalMethod.TERMINAL_MULTIPLE,
            terminal_multiple_metric="EV_EBITDA",
            terminal_multiple_source="PEER_MEDIAN",
        )
        result = ValuationEngine().run(
            valuation_profile=_vp(),
            scenario_set=_ss([_scenario(methodology)]),
            period_inputs=_pi(),
            peer_comparison=FakePeers(),
        )
        v = result.scenarios_run[0]
        assert v.methodology_summary["terminal_multiple_used"] == Decimal("15")

    def test_terminal_multiple_industry_median_resolution(self) -> None:
        methodology = DCFMethodologyConfig(
            type="DCF_3_STAGE",
            terminal_method=TerminalMethod.TERMINAL_MULTIPLE,
            terminal_multiple_metric="EV_EBITDA",
            terminal_multiple_source="INDUSTRY_MEDIAN",
        )
        result = ValuationEngine().run(
            valuation_profile=_vp(industry_median=Decimal("11")),
            scenario_set=_ss([_scenario(methodology)]),
            period_inputs=_pi(industry_median=Decimal("11")),
        )
        v = result.scenarios_run[0]
        assert v.methodology_summary["terminal_multiple_used"] == Decimal("11")

    def test_terminal_multiple_user_specified_requires_value(self) -> None:
        # Validator should reject USER_SPECIFIED without multiple_value.
        with pytest.raises(ValidationError, match="terminal_multiple_value"):
            DCFMethodologyConfig(
                type="DCF_3_STAGE",
                terminal_method=TerminalMethod.TERMINAL_MULTIPLE,
                terminal_multiple_metric="EV_EBITDA",
                terminal_multiple_source="USER_SPECIFIED",
                terminal_multiple_value=None,
            )


# ======================================================================
# Cross-validation
# ======================================================================
class TestCrossValidation:
    def test_terminal_multiple_cross_validation_with_gordon(self) -> None:
        """Summary surfaces the Gordon-implied growth rate that would
        produce the same terminal value given terminal FCF + WACC.
        Useful for sanity-checking how aggressive a peer-derived
        multiple really is."""
        methodology = DCFMethodologyConfig(
            type="DCF_3_STAGE",
            terminal_method=TerminalMethod.TERMINAL_MULTIPLE,
            terminal_multiple_metric="EV_EBITDA",
            terminal_multiple_source="USER_SPECIFIED",
            terminal_multiple_value=Decimal("12"),
        )
        result = ValuationEngine().run(
            valuation_profile=_vp(),
            scenario_set=_ss([_scenario(methodology)]),
            period_inputs=_pi(),
        )
        summary = result.scenarios_run[0].methodology_summary
        assert summary["gordon_implied_growth"] is not None
        # With WACC 7 % and 12× EV/EBITDA on FCF-rich projections,
        # implied g should be in the low single digits.
        assert Decimal("0") < summary["gordon_implied_growth"] < Decimal("0.05")

    def test_dcf_3_stage_with_terminal_multiple_produces_different_value_than_gordon(
        self,
    ) -> None:
        gordon = DCFMethodologyConfig(
            type="DCF_3_STAGE",
            terminal_method=TerminalMethod.GORDON_GROWTH,
            terminal_growth=Decimal("0.025"),
        )
        multiple = DCFMethodologyConfig(
            type="DCF_3_STAGE",
            terminal_method=TerminalMethod.TERMINAL_MULTIPLE,
            terminal_multiple_metric="EV_EBITDA",
            terminal_multiple_source="USER_SPECIFIED",
            terminal_multiple_value=Decimal("15"),  # generous multiple
        )
        r_g = ValuationEngine().run(
            valuation_profile=_vp(),
            scenario_set=_ss([_scenario(gordon)]),
            period_inputs=_pi(),
        )
        r_m = ValuationEngine().run(
            valuation_profile=_vp(),
            scenario_set=_ss([_scenario(multiple)]),
            period_inputs=_pi(),
        )
        # Same drivers + different terminal methods → different TV +
        # different FV. Equality would be suspicious.
        assert (
            r_g.scenarios_run[0].terminal_value
            != r_m.scenarios_run[0].terminal_value
        )
        assert (
            r_g.scenarios_run[0].fair_value_per_share
            != r_m.scenarios_run[0].fair_value_per_share
        )


# ======================================================================
# Rendering
# ======================================================================
class TestRendering:
    def test_markdown_renders_terminal_multiple_computation(self) -> None:
        methodology = DCFMethodologyConfig(
            type="DCF_3_STAGE",
            terminal_method=TerminalMethod.TERMINAL_MULTIPLE,
            terminal_multiple_metric="EV_EBITDA",
            terminal_multiple_source="USER_SPECIFIED",
            terminal_multiple_value=Decimal("12"),
        )
        base = Scenario(
            name="base",  # markdown render picks the "base" scenario
            probability=Decimal("1"),
            rationale="",
            methodology=methodology,
        )
        result = ValuationEngine().run(
            valuation_profile=_vp(),
            scenario_set=_ss([base]),
            period_inputs=_pi(),
        )
        md = render_valuation_markdown(result, ticker="T")
        # Markdown bridge section should show terminal-multiple-specific
        # lines rather than the Gordon "Terminal FCF / growth" block.
        assert "Terminal method: TERMINAL_MULTIPLE" in md
        assert "Terminal metric" in md
        assert "Terminal multiple" in md
        assert "Gordon-implied growth cross-check" in md
