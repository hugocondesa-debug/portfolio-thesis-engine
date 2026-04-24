"""Phase 2 Sprint 4A-alpha.2 regression tests — methodology taxonomy.

Part A — Methodology enum + configs (5):
- ``test_methodology_enum_has_ten_values``
- ``test_dcf_methodology_config_accepts_3_stage_or_2_stage``
- ``test_multiple_exit_config_default_values``
- ``test_transaction_precedent_config_control_premium_default_zero``
- ``test_methodology_discriminator_parses_correct_subclass``

Part B — Dispatcher routing (5):
- ``test_dispatcher_routes_dcf_3_stage_to_p1_engine``
- ``test_dispatcher_routes_dcf_2_stage_to_p1_engine_with_zero_fade``
- ``test_dispatcher_routes_multiple_exit_to_multiple_exit_engine``
- ``test_dispatcher_routes_transaction_precedent_correctly``
- ``test_dispatcher_ddm_emits_not_implemented_warning``

Part C — M2 DCF 2-stage (4):
- ``test_dcf_2_stage_skips_fade_projections``
- ``test_dcf_2_stage_terminal_off_last_explicit``
- ``test_dcf_2_stage_shorter_horizon_yields_lower_tv``
- ``test_bear_structural_methodology_used_dcf_2_stage``

Part D — M3 MultipleExit (6):
- ``test_multiple_exit_uses_peer_median_when_configured``
- ``test_multiple_exit_uses_user_specified_value``
- ``test_multiple_exit_applies_multiple_multiplier``
- ``test_multiple_exit_discounts_to_present``
- ``test_multiple_exit_equity_bridge_uses_net_debt``
- ``test_multiple_exit_methodology_used_recorded``

Part E — M10 TransactionPrecedent (3):
- ``test_transaction_precedent_multiple_times_ebitda``
- ``test_transaction_precedent_applies_control_premium``
- ``test_transaction_precedent_no_pv_discount``

Integration — EuroEyes 6 scenarios (4):
- ``test_euroeyes_six_scenarios_present``
- ``test_euroeyes_scenario_probabilities_sum_one``
- ``test_euroeyes_methodology_mix_visible_in_results``
- ``test_euroeyes_expected_value_with_new_scenario_mix``

Total: 27 tests.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from portfolio_thesis_engine.dcf.engine import ValuationEngine
from portfolio_thesis_engine.dcf.orchestrator import DCFOrchestrator
from portfolio_thesis_engine.dcf.p1_engine import PeriodInputs
from portfolio_thesis_engine.dcf.schemas import (
    DCFMethodologyConfig,
    DCFProfile,
    DCFStructure,
    DDMMethodologyConfig,
    ForecastWarning,
    MultipleExitMethodologyConfig,
    ProfileSelection,
    Scenario,
    ScenarioDriverOverride,
    ScenarioSet,
    TerminalValueConfig,
    TransactionPrecedentMethodologyConfig,
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
            "growth_pattern": [
                Decimal("0.05"), Decimal("0.05"), Decimal("0.05"),
                Decimal("0.05"), Decimal("0.05"),
            ],
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


def _vp() -> ValuationProfile:
    return ValuationProfile(
        target_ticker="TEST",
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
            cross_check_industry_median=Decimal("10"),
        ),
    )


def _pi() -> PeriodInputs:
    return PeriodInputs(
        ticker="TEST",
        stage_1_wacc=Decimal("0.08"),
        stage_3_wacc=Decimal("0.07"),
        shares_outstanding=Decimal("100"),
        net_debt=Decimal("0"),
        market_price=Decimal("10"),
        industry_median_ev_ebitda=Decimal("10"),
    )


def _scenario(
    name: str = "base",
    *,
    methodology,
    probability: Decimal = Decimal("1"),
    overrides: dict | None = None,
) -> Scenario:
    return Scenario(
        name=name,
        probability=probability,
        rationale="",
        methodology=methodology,
        driver_overrides=overrides or {},
    )


def _ss(scenarios: list[Scenario]) -> ScenarioSet:
    return ScenarioSet(
        target_ticker="TEST",
        valuation_profile=DCFProfile.P1_INDUSTRIAL_SERVICES,
        base_year="FY2024",
        base_drivers=_base_drivers(),
        scenarios=scenarios,
    )


# ======================================================================
# Part A — Methodology enum + configs
# ======================================================================
class TestPartAMethodologyConfigs:
    def test_methodology_enum_has_ten_values(self) -> None:
        assert len(list(ValuationMethodology)) == 10

    def test_dcf_methodology_config_accepts_3_stage_or_2_stage(self) -> None:
        three = DCFMethodologyConfig(type="DCF_3_STAGE")
        two = DCFMethodologyConfig(type="DCF_2_STAGE", fade_years=0)
        assert three.type == "DCF_3_STAGE"
        assert two.fade_years == 0

    def test_multiple_exit_config_default_values(self) -> None:
        cfg = MultipleExitMethodologyConfig()
        assert cfg.type == "MULTIPLE_EXIT"
        assert cfg.multiple_multiplier == Decimal("1.0")
        assert cfg.discount_rate_source == "STAGE_1_WACC"

    def test_transaction_precedent_config_control_premium_default_zero(
        self,
    ) -> None:
        cfg = TransactionPrecedentMethodologyConfig()
        assert cfg.control_premium == Decimal("0.0")

    def test_methodology_discriminator_parses_correct_subclass(self) -> None:
        from portfolio_thesis_engine.dcf.schemas import Scenario as _Scenario

        s = _Scenario.model_validate({
            "name": "s",
            "probability": 1,
            "methodology": {
                "type": "MULTIPLE_EXIT",
                "metric": "FORWARD_EBITDA",
                "metric_year": 2,
                "multiple_value": 12,
                "multiple_source": "USER_SPECIFIED",
            },
        })
        assert isinstance(s.methodology, MultipleExitMethodologyConfig)


# ======================================================================
# Part B — Dispatcher routing
# ======================================================================
class TestPartBDispatcher:
    def test_dispatcher_routes_dcf_3_stage_to_p1_engine(self) -> None:
        ss = _ss([_scenario(methodology=DCFMethodologyConfig(type="DCF_3_STAGE"))])
        result = ValuationEngine().run(
            valuation_profile=_vp(), scenario_set=ss, period_inputs=_pi()
        )
        assert (
            result.scenarios_run[0].methodology_used
            == ValuationMethodology.DCF_3_STAGE
        )
        assert len(result.scenarios_run[0].fade_projections) > 0

    def test_dispatcher_routes_dcf_2_stage_to_p1_engine_with_zero_fade(
        self,
    ) -> None:
        ss = _ss([
            _scenario(methodology=DCFMethodologyConfig(
                type="DCF_2_STAGE", explicit_years=2, fade_years=0,
            ))
        ])
        result = ValuationEngine().run(
            valuation_profile=_vp(), scenario_set=ss, period_inputs=_pi()
        )
        v = result.scenarios_run[0]
        assert v.methodology_used == ValuationMethodology.DCF_2_STAGE
        assert v.fade_projections == []
        assert len(v.explicit_projections) == 2

    def test_dispatcher_routes_multiple_exit_to_multiple_exit_engine(
        self,
    ) -> None:
        ss = _ss([
            _scenario(methodology=MultipleExitMethodologyConfig(
                metric_year=2, multiple_source="USER_SPECIFIED",
                multiple_value=Decimal("10"),
            ))
        ])
        result = ValuationEngine().run(
            valuation_profile=_vp(), scenario_set=ss, period_inputs=_pi()
        )
        assert (
            result.scenarios_run[0].methodology_used
            == ValuationMethodology.MULTIPLE_EXIT
        )

    def test_dispatcher_routes_transaction_precedent_correctly(self) -> None:
        ss = _ss([
            _scenario(methodology=TransactionPrecedentMethodologyConfig(
                multiple_value=Decimal("12"),
            ))
        ])
        result = ValuationEngine().run(
            valuation_profile=_vp(), scenario_set=ss, period_inputs=_pi()
        )
        assert (
            result.scenarios_run[0].methodology_used
            == ValuationMethodology.TRANSACTION_PRECEDENT
        )

    def test_dispatcher_ddm_emits_not_implemented_warning(self) -> None:
        """Sprint 4B implemented DDM, but the dispatcher still raises
        :class:`NotImplementedError` when it has no three-statement
        projection to consume. The aggregation pipeline converts it into
        a CRITICAL warning so the scenario drops cleanly."""
        ss = _ss([_scenario(methodology=DDMMethodologyConfig())])
        result = ValuationEngine().run(
            valuation_profile=_vp(), scenario_set=ss, period_inputs=_pi()
        )
        assert result.scenarios_run == []
        assert any(
            w.severity == "CRITICAL"
            and "three-statement projection" in w.observation
            for w in result.warnings
        )


# ======================================================================
# Part C — M2 DCF 2-stage
# ======================================================================
class TestPartCDCF2Stage:
    def _ss_two_stage(self) -> ScenarioSet:
        return _ss([
            _scenario(
                name="bear",
                methodology=DCFMethodologyConfig(
                    type="DCF_2_STAGE",
                    explicit_years=2,
                    fade_years=0,
                    terminal_growth=Decimal("0.01"),
                ),
            )
        ])

    def test_dcf_2_stage_skips_fade_projections(self) -> None:
        result = ValuationEngine().run(
            valuation_profile=_vp(),
            scenario_set=self._ss_two_stage(),
            period_inputs=_pi(),
        )
        v = result.scenarios_run[0]
        assert v.fade_projections == []
        assert len(v.explicit_projections) == 2

    def test_dcf_2_stage_terminal_off_last_explicit(self) -> None:
        result = ValuationEngine().run(
            valuation_profile=_vp(),
            scenario_set=self._ss_two_stage(),
            period_inputs=_pi(),
        )
        v = result.scenarios_run[0]
        # Terminal FCF should equal the last explicit year's FCF.
        assert v.terminal_fcf == v.explicit_projections[-1].fcf

    def test_dcf_2_stage_shorter_horizon_yields_lower_tv(self) -> None:
        """Matching inputs but 2 explicit vs 5 explicit → 2-stage
        gets a smaller terminal value (less compounding before the
        terminal)."""
        ss_2y = _ss([_scenario(
            methodology=DCFMethodologyConfig(
                type="DCF_2_STAGE", explicit_years=2, fade_years=0,
            )
        )])
        ss_5y = _ss([_scenario(
            methodology=DCFMethodologyConfig(
                type="DCF_3_STAGE", explicit_years=5, fade_years=5,
            )
        )])
        r_2y = ValuationEngine().run(
            valuation_profile=_vp(), scenario_set=ss_2y, period_inputs=_pi()
        )
        r_5y = ValuationEngine().run(
            valuation_profile=_vp(), scenario_set=ss_5y, period_inputs=_pi()
        )
        assert r_2y.scenarios_run[0].terminal_value < r_5y.scenarios_run[0].terminal_value

    def test_bear_structural_methodology_used_dcf_2_stage(self) -> None:
        """EuroEyes' bear_structural scenario uses DCF_2_STAGE."""
        result = DCFOrchestrator().run("1846.HK")
        assert result is not None
        bear = next(
            v for v in result.scenarios_run if v.scenario_name == "bear_structural"
        )
        assert bear.methodology_used == ValuationMethodology.DCF_2_STAGE
        assert bear.fade_projections == []


# ======================================================================
# Part D — M3 MultipleExit
# ======================================================================
class TestPartDMultipleExit:
    def _run(
        self,
        *,
        multiple_source: str = "USER_SPECIFIED",
        multiple_value: Decimal | None = Decimal("10"),
        multiplier: Decimal = Decimal("1.0"),
        metric_year: int = 2,
        peer_comparison=None,
    ):
        methodology = MultipleExitMethodologyConfig(
            metric_year=metric_year,
            multiple_source=multiple_source,  # type: ignore[arg-type]
            multiple_value=multiple_value,
            multiple_multiplier=multiplier,
        )
        ss = _ss([_scenario(methodology=methodology)])
        return ValuationEngine().run(
            valuation_profile=_vp(),
            scenario_set=ss,
            period_inputs=_pi(),
            peer_comparison=peer_comparison,
        )

    def test_multiple_exit_uses_peer_median_when_configured(self) -> None:
        # Fake peer_comparison with a median.
        class FakePeers:
            peer_median = {"ev_to_ebitda": Decimal("15")}

        result = self._run(
            multiple_source="PEER_MEDIAN",
            multiple_value=None,
            peer_comparison=FakePeers(),
        )
        v = result.scenarios_run[0]
        assert v.methodology_summary["target_multiple"] == Decimal("15")

    def test_multiple_exit_uses_user_specified_value(self) -> None:
        result = self._run(multiple_source="USER_SPECIFIED", multiple_value=Decimal("12"))
        v = result.scenarios_run[0]
        assert v.methodology_summary["target_multiple"] == Decimal("12")

    def test_multiple_exit_applies_multiple_multiplier(self) -> None:
        result = self._run(multiple_value=Decimal("10"), multiplier=Decimal("1.5"))
        v = result.scenarios_run[0]
        assert v.methodology_summary["adjusted_multiple"] == Decimal("15")

    def test_multiple_exit_discounts_to_present(self) -> None:
        """Exit EV at metric_year=2 should be discounted ~1.166x at 8 %
        WACC."""
        result = self._run(metric_year=2)
        v = result.scenarios_run[0]
        exit_ev = v.methodology_summary["exit_enterprise_value"]
        exit_pv = v.methodology_summary["exit_pv"]
        # PV/EV ratio ≈ 1 / 1.08² = 0.857
        ratio = exit_pv / exit_ev
        assert abs(ratio - Decimal("0.857")) < Decimal("0.01")

    def test_multiple_exit_equity_bridge_uses_net_debt(self) -> None:
        # Positive net debt reduces equity vs enterprise.
        pi_with_debt = PeriodInputs(
            ticker="TEST",
            stage_1_wacc=Decimal("0.08"),
            stage_3_wacc=Decimal("0.07"),
            shares_outstanding=Decimal("100"),
            net_debt=Decimal("50"),
            market_price=Decimal("10"),
            industry_median_ev_ebitda=Decimal("10"),
        )
        methodology = MultipleExitMethodologyConfig(
            metric_year=2, multiple_source="USER_SPECIFIED",
            multiple_value=Decimal("10"),
        )
        ss = _ss([_scenario(methodology=methodology)])
        result = ValuationEngine().run(
            valuation_profile=_vp(), scenario_set=ss, period_inputs=pi_with_debt
        )
        v = result.scenarios_run[0]
        assert v.equity_value == v.enterprise_value - Decimal("50")

    def test_multiple_exit_methodology_used_recorded(self) -> None:
        result = self._run()
        assert (
            result.scenarios_run[0].methodology_used
            == ValuationMethodology.MULTIPLE_EXIT
        )


# ======================================================================
# Part E — M10 TransactionPrecedent
# ======================================================================
class TestPartETransactionPrecedent:
    def _run(
        self,
        *,
        multiple: Decimal = Decimal("12"),
        control_premium: Decimal = Decimal("0"),
    ):
        methodology = TransactionPrecedentMethodologyConfig(
            multiple_value=multiple,
            control_premium=control_premium,
        )
        ss = _ss([_scenario(methodology=methodology)])
        return ValuationEngine().run(
            valuation_profile=_vp(), scenario_set=ss, period_inputs=_pi()
        )

    def test_transaction_precedent_multiple_times_ebitda(self) -> None:
        result = self._run(multiple=Decimal("12"))
        v = result.scenarios_run[0]
        # EBITDA ≈ base revenue × current margin + D&A proxy
        # = 1000 × 0.20 + 1000 × 0.08/10 = 200 + 8 = 208
        assert abs(v.methodology_summary["ttm_ebitda"] - Decimal("208")) < Decimal("1")
        assert v.methodology_summary["standalone_enterprise_value"] == Decimal("208") * Decimal("12")

    def test_transaction_precedent_applies_control_premium(self) -> None:
        no_premium = self._run(control_premium=Decimal("0"))
        with_premium = self._run(control_premium=Decimal("0.25"))
        v_a = no_premium.scenarios_run[0]
        v_b = with_premium.scenarios_run[0]
        ratio = v_b.enterprise_value / v_a.enterprise_value
        assert abs(ratio - Decimal("1.25")) < Decimal("0.001")

    def test_transaction_precedent_no_pv_discount(self) -> None:
        """Terminal value == enterprise value (no PV discount applied)."""
        result = self._run()
        v = result.scenarios_run[0]
        assert v.terminal_pv == v.enterprise_value


# ======================================================================
# Integration — EuroEyes 6 scenarios
# ======================================================================
class TestEuroEyesSixScenarios:
    def _result(self):
        return DCFOrchestrator().run("1846.HK")

    def test_euroeyes_six_scenarios_present(self) -> None:
        result = self._result()
        assert result is not None
        names = {v.scenario_name for v in result.scenarios_run}
        # Sprint 4A-alpha.6 added ``m_and_a_accelerated`` to the original
        # six. The test name is preserved for git-blame continuity; the
        # assertion is the canonical 7-scenario set.
        assert names == {
            "base",
            "bull_re_rating",
            "bull_operational",
            "bear_structural",
            "bear_prc_delay",
            "takeover_floor",
            "m_and_a_accelerated",
        }

    def test_euroeyes_scenario_probabilities_sum_one(self) -> None:
        result = self._result()
        assert result is not None
        total = sum(
            (v.scenario_probability for v in result.scenarios_run),
            start=Decimal("0"),
        )
        assert abs(total - Decimal("1")) < Decimal("0.01")

    def test_euroeyes_methodology_mix_visible_in_results(self) -> None:
        result = self._result()
        assert result is not None
        methodologies = {v.methodology_used for v in result.scenarios_run}
        assert methodologies == {
            ValuationMethodology.DCF_3_STAGE,
            ValuationMethodology.DCF_2_STAGE,
            ValuationMethodology.MULTIPLE_EXIT,
            ValuationMethodology.TRANSACTION_PRECEDENT,
        }

    def test_euroeyes_expected_value_with_new_scenario_mix(self) -> None:
        result = self._result()
        assert result is not None
        # Six-scenario weighted expected value should sit in a
        # reasonable HK$ range (somewhere between the bear cases and
        # the bull cases).
        assert Decimal("4") < result.expected_value_per_share < Decimal("10")
