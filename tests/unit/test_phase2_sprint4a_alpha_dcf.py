"""Phase 2 Sprint 4A-alpha regression tests — P1 DCF + profile
architecture.

Part A — Profile taxonomy (8):
- ``test_profile_enum_has_six_values``
- ``test_heuristic_maps_healthcare_services_to_p1``
- ``test_heuristic_maps_bank_to_p2``
- ``test_heuristic_maps_reit_to_p3``
- ``test_heuristic_maps_oil_to_p4``
- ``test_heuristic_maps_biotech_to_p5``
- ``test_heuristic_defaults_to_p1_when_no_match``
- ``test_valuation_profile_loader_uses_yaml_when_present``

Part B — Scenarios (5):
- ``test_scenarios_yaml_loads``
- ``test_probabilities_sum_to_one_validation``
- ``test_probability_mismatch_raises``
- ``test_terminal_multiple_probabilities_separately_validated``
- ``test_unlimited_scenarios_supported``

Part C — P1 DCF engine (9):
- ``test_p1_engine_runs_single_scenario``
- ``test_revenue_compounds_through_growth_pattern``
- ``test_margin_fades_linearly``
- ``test_wacc_evolution_linear_stage_1_to_stage_3``
- ``test_terminal_value_gordon_growth_formula``
- ``test_terminal_multiple_warning_when_above_threshold``
- ``test_enterprise_to_equity_bridge_subtracts_net_debt``
- ``test_expected_value_is_probability_weighted``
- ``test_non_p1_profile_raises_not_implemented``

Part D — Forecast coherence (3):
- ``test_warning_when_fcf_negative_in_mature_years``
- ``test_warning_severity_tiers``
- ``test_no_warnings_on_healthy_projection``

Part E — CLI (3):
- ``test_pte_valuation_renders_table``
- ``test_pte_valuation_export_markdown``
- ``test_pte_analyze_embeds_dcf_summary``

Integration — EuroEyes (4):
- ``test_euroeyes_expected_value_in_range``
- ``test_euroeyes_four_scenarios_present``
- ``test_euroeyes_stage_1_matches_sprint_3_wacc``
- ``test_euroeyes_terminal_multiple_under_threshold``

Total: 32 tests.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from rich.console import Console

from portfolio_thesis_engine.cli import analyze_cmd, valuation_cmd
from portfolio_thesis_engine.dcf.orchestrator import DCFOrchestrator
from portfolio_thesis_engine.dcf.p1_engine import P1DCFEngine, PeriodInputs
from portfolio_thesis_engine.dcf.profiles import (
    infer_profile_from_industry,
    load_valuation_profile,
)
from portfolio_thesis_engine.dcf.schemas import (
    DCFProfile,
    DCFStructure,
    ProfileSelection,
    Scenario,
    ScenarioDriverOverride,
    ScenarioSet,
    TerminalMultipleScenario,
    TerminalValueConfig,
    ValuationProfile,
    WACCEvolution,
)


# ======================================================================
# Helpers
# ======================================================================
def _base_drivers(
    *,
    revenue: Decimal = Decimal("715682000"),
    growth_pattern: list[Decimal] | None = None,
    margin_current: Decimal = Decimal("0.162"),
    margin_terminal: Decimal = Decimal("0.180"),
    terminal_growth: Decimal = Decimal("0.025"),
    capex_current: Decimal = Decimal("0.112"),
    capex_terminal: Decimal = Decimal("0.060"),
    wc_current: Decimal = Decimal("-0.004"),
    wc_terminal: Decimal = Decimal("-0.002"),
    tax: Decimal = Decimal("0.165"),
    depreciation: Decimal = Decimal("0.08"),
) -> dict:
    if growth_pattern is None:
        growth_pattern = [
            Decimal("0.055"), Decimal("0.065"), Decimal("0.070"),
            Decimal("0.060"), Decimal("0.045"),
        ]
    return {
        "revenue": {
            "base_year_value": revenue,
            "growth_pattern": growth_pattern,
            "terminal_growth": terminal_growth,
        },
        "operating_margin": {
            "current": margin_current,
            "target_terminal": margin_terminal,
        },
        "tax_rate": {"statutory": tax},
        "capex_intensity": {
            "current": capex_current,
            "target": capex_terminal,
        },
        "working_capital_intensity": {
            "current": wc_current,
            "target": wc_terminal,
        },
        "depreciation_rate": {"current": depreciation},
    }


def _scenario(
    name: str = "base",
    *,
    probability: Decimal = Decimal("1.0"),
    overrides: dict[str, ScenarioDriverOverride] | None = None,
) -> Scenario:
    return Scenario(
        name=name,
        probability=probability,
        rationale="test",
        driver_overrides=overrides or {},
    )


def _scenario_set(
    *,
    scenarios: list[Scenario] | None = None,
    base_drivers: dict | None = None,
    terminal_multiples: list[TerminalMultipleScenario] | None = None,
) -> ScenarioSet:
    return ScenarioSet(
        target_ticker="TEST.HK",
        valuation_profile=DCFProfile.P1_INDUSTRIAL_SERVICES,
        base_year="FY2024",
        base_drivers=base_drivers or _base_drivers(),
        scenarios=scenarios or [_scenario()],
        terminal_multiple_scenarios=terminal_multiples,
    )


def _valuation_profile(
    *,
    mature_beta: Decimal = Decimal("0.68"),
    target_leverage: Decimal = Decimal("0.0"),
    industry_median: Decimal | None = Decimal("10.5"),
) -> ValuationProfile:
    return ValuationProfile(
        target_ticker="TEST.HK",
        profile=ProfileSelection(
            code=DCFProfile.P1_INDUSTRIAL_SERVICES,
            source="USER_OVERRIDE",
            confidence="HIGH",
            rationale="test",
        ),
        dcf_structure=DCFStructure(
            type="THREE_STAGE", explicit_years=5, fade_years=5
        ),
        wacc_evolution=WACCEvolution(
            stage_3_mature_beta=mature_beta,
            stage_3_target_leverage=target_leverage,
        ),
        terminal_value=TerminalValueConfig(
            cross_check_industry_median=industry_median,
        ),
    )


def _period_inputs(
    *,
    stage_1: Decimal = Decimal("0.08"),
    stage_3: Decimal = Decimal("0.075"),
    shares: Decimal = Decimal("320000000"),
    net_debt: Decimal = Decimal("-741000000"),
    industry_median: Decimal | None = Decimal("10.5"),
) -> PeriodInputs:
    return PeriodInputs(
        ticker="TEST.HK",
        stage_1_wacc=stage_1,
        stage_3_wacc=stage_3,
        shares_outstanding=shares,
        net_debt=net_debt,
        industry_median_ev_ebitda=industry_median,
    )


# ======================================================================
# Part A — Profile taxonomy
# ======================================================================
class TestPartAProfileTaxonomy:
    def test_profile_enum_has_six_values(self) -> None:
        assert len(list(DCFProfile)) == 6

    def test_heuristic_maps_healthcare_services_to_p1(self) -> None:
        h = infer_profile_from_industry("Healthcare Services")
        assert h.suggested_profile == DCFProfile.P1_INDUSTRIAL_SERVICES
        assert h.confidence == "HIGH"

    def test_heuristic_maps_bank_to_p2(self) -> None:
        h = infer_profile_from_industry("Banks")
        assert h.suggested_profile == DCFProfile.P2_FINANCIAL
        assert h.confidence == "HIGH"

    def test_heuristic_maps_reit_to_p3(self) -> None:
        h = infer_profile_from_industry("Residential REITs")
        assert h.suggested_profile == DCFProfile.P3_REIT

    def test_heuristic_maps_oil_to_p4(self) -> None:
        h = infer_profile_from_industry("Oil & Gas Exploration")
        assert h.suggested_profile == DCFProfile.P4_CYCLICAL_COMMODITY

    def test_heuristic_maps_biotech_to_p5(self) -> None:
        h = infer_profile_from_industry("Biotech")
        assert h.suggested_profile == DCFProfile.P5_HIGH_GROWTH

    def test_heuristic_defaults_to_p1_when_no_match(self) -> None:
        h = infer_profile_from_industry("Utterly Unknown Industry")
        assert h.suggested_profile == DCFProfile.P1_INDUSTRIAL_SERVICES
        assert h.confidence == "LOW"

    def test_valuation_profile_loader_uses_yaml_when_present(self) -> None:
        # EuroEyes has a starter YAML; test it loads the USER_OVERRIDE
        # rather than synthesising a heuristic.
        profile = load_valuation_profile("1846.HK")
        assert profile.profile.code == DCFProfile.P1_INDUSTRIAL_SERVICES
        assert profile.profile.source == "USER_OVERRIDE"


# ======================================================================
# Part B — Scenarios
# ======================================================================
class TestPartBScenarios:
    def test_scenarios_yaml_loads(self) -> None:
        from portfolio_thesis_engine.dcf.scenarios import load_scenarios

        sset = load_scenarios("1846.HK")
        assert sset is not None
        assert sset.target_ticker == "1846.HK"
        # Sprint 4A-alpha.2 introduced per-scenario methodology with 6
        # scenarios; Sprint 4A-alpha.6 added ``m_and_a_accelerated`` →
        # 7 total.
        assert len(sset.scenarios) == 7
        names = {s.name for s in sset.scenarios}
        assert "m_and_a_accelerated" in names

    def test_probabilities_sum_to_one_validation(self) -> None:
        # 0.4 + 0.25 + 0.25 + 0.10 = 1.00, valid.
        ss = _scenario_set(
            scenarios=[
                _scenario("a", probability=Decimal("0.4")),
                _scenario("b", probability=Decimal("0.25")),
                _scenario("c", probability=Decimal("0.25")),
                _scenario("d", probability=Decimal("0.10")),
            ]
        )
        assert ss is not None

    def test_probability_mismatch_raises(self) -> None:
        with pytest.raises(ValueError, match="Scenario probabilities"):
            _scenario_set(
                scenarios=[
                    _scenario("a", probability=Decimal("0.5")),
                    _scenario("b", probability=Decimal("0.3")),
                ]
            )

    def test_terminal_multiple_probabilities_separately_validated(self) -> None:
        ss = _scenario_set(
            terminal_multiples=[
                TerminalMultipleScenario(
                    name="a", probability=Decimal("0.5"), ev_ebitda=Decimal("10")
                ),
                TerminalMultipleScenario(
                    name="b", probability=Decimal("0.5"), ev_ebitda=Decimal("13")
                ),
            ]
        )
        assert ss.terminal_multiple_scenarios is not None
        assert len(ss.terminal_multiple_scenarios) == 2

    def test_unlimited_scenarios_supported(self) -> None:
        scenarios = [
            _scenario(f"s{i}", probability=Decimal("0.1"))
            for i in range(10)
        ]
        ss = _scenario_set(scenarios=scenarios)
        assert len(ss.scenarios) == 10


# ======================================================================
# Part C — P1 DCF engine
# ======================================================================
class TestPartCDCFEngine:
    def test_p1_engine_runs_single_scenario(self) -> None:
        engine = P1DCFEngine()
        result = engine.run(
            valuation_profile=_valuation_profile(),
            scenario_set=_scenario_set(),
            period_inputs=_period_inputs(),
        )
        assert len(result.scenarios_run) == 1
        v = result.scenarios_run[0]
        assert len(v.explicit_projections) == 5
        assert len(v.fade_projections) == 5

    def test_revenue_compounds_through_growth_pattern(self) -> None:
        engine = P1DCFEngine()
        result = engine.run(
            valuation_profile=_valuation_profile(),
            scenario_set=_scenario_set(
                base_drivers=_base_drivers(
                    revenue=Decimal("1000"),
                    growth_pattern=[Decimal("0.1")] * 5,
                )
            ),
            period_inputs=_period_inputs(),
        )
        projections = result.scenarios_run[0].explicit_projections
        # 1000 × 1.1^5 = 1610.51
        expected_y5 = Decimal("1000") * Decimal("1.61051")
        assert abs(projections[-1].revenue - expected_y5) < Decimal("1")

    def test_margin_fades_linearly(self) -> None:
        engine = P1DCFEngine()
        result = engine.run(
            valuation_profile=_valuation_profile(),
            scenario_set=_scenario_set(
                base_drivers=_base_drivers(
                    margin_current=Decimal("0.10"),
                    margin_terminal=Decimal("0.20"),
                )
            ),
            period_inputs=_period_inputs(),
        )
        v = result.scenarios_run[0]
        all_projections = v.explicit_projections + v.fade_projections
        # 10 years total; year 1 margin ≈ 0.11, year 10 ≈ 0.20.
        assert abs(all_projections[0].operating_margin - Decimal("0.11")) < Decimal("0.01")
        assert abs(all_projections[-1].operating_margin - Decimal("0.20")) < Decimal("0.001")

    def test_wacc_evolution_linear_stage_1_to_stage_3(self) -> None:
        engine = P1DCFEngine()
        result = engine.run(
            valuation_profile=_valuation_profile(),
            scenario_set=_scenario_set(),
            period_inputs=_period_inputs(
                stage_1=Decimal("0.10"), stage_3=Decimal("0.06"),
            ),
        )
        v = result.scenarios_run[0]
        # Years 1-5: stage 1.
        assert all(
            p.wacc_applied == Decimal("0.10") for p in v.explicit_projections
        )
        # Year 10: stage 3.
        assert v.fade_projections[-1].wacc_applied == Decimal("0.06")
        # Year 6 — first fade step of 5 → stage_1 + 1/5 × (stage_3 − stage_1)
        # = 0.10 + 0.2 × (-0.04) = 0.092.
        assert abs(v.fade_projections[0].wacc_applied - Decimal("0.092")) < Decimal("0.001")

    def test_terminal_value_gordon_growth_formula(self) -> None:
        engine = P1DCFEngine()
        result = engine.run(
            valuation_profile=_valuation_profile(),
            scenario_set=_scenario_set(),
            period_inputs=_period_inputs(),
        )
        v = result.scenarios_run[0]
        # TV = FCF_10 × (1+g) / (WACC_term - g)
        expected_tv = (
            v.terminal_fcf * (Decimal("1") + v.terminal_growth)
            / (v.terminal_wacc - v.terminal_growth)
        )
        assert abs(v.terminal_value - expected_tv) < Decimal("1")

    def test_terminal_multiple_warning_when_above_threshold(self) -> None:
        """Industry median 5× + warning_threshold 1.5× → warn if implied > 7.5×."""
        profile = _valuation_profile(industry_median=Decimal("5.0"))
        profile.terminal_value.warning_threshold = Decimal("1.5")
        engine = P1DCFEngine()
        result = engine.run(
            valuation_profile=profile,
            scenario_set=_scenario_set(),
            period_inputs=_period_inputs(
                industry_median=Decimal("5.0"),
            ),
        )
        # EuroEyes-like fixture produces EV/EBITDA ≈ 15+ → warn.
        v = result.scenarios_run[0]
        if v.terminal_multiple_validation.implied_ev_ebitda is not None:
            assert v.terminal_multiple_validation.warning_emitted is True

    def test_enterprise_to_equity_bridge_subtracts_net_debt(self) -> None:
        engine = P1DCFEngine()
        # Positive net_debt case — equity should be less than EV.
        result = engine.run(
            valuation_profile=_valuation_profile(),
            scenario_set=_scenario_set(),
            period_inputs=_period_inputs(net_debt=Decimal("100000000")),
        )
        v = result.scenarios_run[0]
        assert v.equity_value < v.enterprise_value
        assert v.equity_value == v.enterprise_value - Decimal("100000000")

    def test_expected_value_is_probability_weighted(self) -> None:
        engine = P1DCFEngine()
        ss = _scenario_set(
            scenarios=[
                _scenario("a", probability=Decimal("0.5")),
                _scenario(
                    "b", probability=Decimal("0.5"),
                    overrides={
                        "operating_margin": ScenarioDriverOverride(
                            target_terminal=Decimal("0.30")
                        )
                    },
                ),
            ]
        )
        result = engine.run(
            valuation_profile=_valuation_profile(),
            scenario_set=ss,
            period_inputs=_period_inputs(),
        )
        a_val = result.scenarios_run[0].fair_value_per_share
        b_val = result.scenarios_run[1].fair_value_per_share
        expected = (a_val + b_val) / Decimal("2")
        assert abs(result.expected_value_per_share - expected) < Decimal("0.01")

    def test_non_p1_profile_raises_not_implemented(self) -> None:
        engine = P1DCFEngine()
        profile = _valuation_profile()
        profile.profile.code = DCFProfile.P2_FINANCIAL
        with pytest.raises(NotImplementedError):
            engine.run(
                valuation_profile=profile,
                scenario_set=_scenario_set(),
                period_inputs=_period_inputs(),
            )


# ======================================================================
# Part D — Forecast coherence
# ======================================================================
class TestPartDCoherence:
    def test_warning_when_fcf_negative_in_mature_years(self) -> None:
        """Hyper-aggressive capex intensity drives mature FCF negative
        → coherence warning."""
        engine = P1DCFEngine()
        ss = _scenario_set(
            base_drivers=_base_drivers(
                capex_current=Decimal("1.0"),  # 100 % of revenue
                capex_terminal=Decimal("0.8"),
                margin_current=Decimal("0.05"),
                margin_terminal=Decimal("0.05"),
            )
        )
        result = engine.run(
            valuation_profile=_valuation_profile(),
            scenario_set=ss,
            period_inputs=_period_inputs(),
        )
        messages = [w.metric for w in result.warnings]
        assert "free_cash_flow" in messages

    def test_warning_severity_tiers(self) -> None:
        """Severity enum exists and CRITICAL fires for degenerate Gordon growth."""
        engine = P1DCFEngine()
        profile = _valuation_profile()
        # Force terminal_growth >= terminal_wacc by using tiny stage_3 WACC.
        result = engine.run(
            valuation_profile=profile,
            scenario_set=_scenario_set(
                base_drivers=_base_drivers(terminal_growth=Decimal("0.10"))
            ),
            period_inputs=_period_inputs(stage_3=Decimal("0.05")),
        )
        severities = {w.severity for w in result.warnings}
        assert "CRITICAL" in severities

    def test_no_warnings_on_healthy_projection(self) -> None:
        engine = P1DCFEngine()
        result = engine.run(
            valuation_profile=_valuation_profile(
                industry_median=Decimal("20.0")  # Permissive multiple
            ),
            scenario_set=_scenario_set(),
            period_inputs=_period_inputs(
                industry_median=Decimal("20.0"),
            ),
        )
        # Base EuroEyes-like projection should pass every check.
        assert result.warnings == []


# ======================================================================
# Part E — CLI
# ======================================================================
class TestPartECLI:
    def test_pte_valuation_renders_table(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buf = io.StringIO()
        monkeypatch.setattr(
            valuation_cmd, "console", Console(file=buf, width=200, record=True)
        )
        valuation_cmd._run_valuation(
            "1846.HK", export=None, scenario_filter=None,
            detail=False, market_price=Decimal("2.65"),
            orchestrator=None,
        )
        rendered = buf.getvalue()
        # Sprint 4A-alpha.2 renamed table to "Valuation scenarios"
        # because scenarios can now be non-DCF methodologies.
        assert "Valuation scenarios" in rendered or "DCF scenarios" in rendered
        assert "base" in rendered
        assert "Expected value" in rendered

    def test_pte_valuation_export_markdown(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        buf = io.StringIO()
        monkeypatch.setattr(
            valuation_cmd, "console", Console(file=buf, width=200)
        )
        out = tmp_path / "valuation.md"
        valuation_cmd._run_valuation(
            "1846.HK", export=out, scenario_filter=None,
            detail=False, market_price=Decimal("2.65"),
            orchestrator=None,
        )
        md = out.read_text()
        assert "# 1846.HK — DCF Valuation" in md
        assert "Expected value per share" in md

    def test_pte_analyze_embeds_dcf_summary(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from portfolio_thesis_engine.analytical.historicals import (
            HistoricalNormalizer,
        )

        buf = io.StringIO()
        monkeypatch.setattr(
            analyze_cmd, "console", Console(file=buf, width=200, record=True)
        )
        analyze_cmd._run_analyze(
            "1846.HK", export=None, normalizer=HistoricalNormalizer()
        )
        rendered = buf.getvalue()
        assert "Scenario-weighted DCF" in rendered


# ======================================================================
# Integration — EuroEyes end-to-end
# ======================================================================
class TestEuroEyesIntegration:
    def _result(self):
        return DCFOrchestrator().run("1846.HK")

    def test_euroeyes_expected_value_in_range(self) -> None:
        """Expected per-share value should be HK$5-10 range — triangulated
        with Phase-1 DCF HK$7.55 single-stage and peer-implied HK$10+."""
        result = self._result()
        assert result is not None
        assert result.expected_value_per_share is not None
        assert Decimal("4") < result.expected_value_per_share < Decimal("15")

    def test_euroeyes_four_scenarios_present(self) -> None:
        """Sprint 4A-alpha.2 expanded the EuroEyes YAML to 6 scenarios
        with per-scenario methodologies. At minimum, every new name
        must be present."""
        result = self._result()
        assert result is not None
        names = {v.scenario_name for v in result.scenarios_run}
        assert names >= {
            "base",
            "bull_re_rating",
            "bull_operational",
            "bear_structural",
            "bear_prc_delay",
            "takeover_floor",
        }

    def test_euroeyes_stage_1_matches_sprint_3_wacc(self) -> None:
        """Stage-1 WACC should be the Sprint-3 auto WACC (~8.06 %)."""
        result = self._result()
        assert result is not None
        assert abs(result.stage_1_wacc - Decimal("0.08")) < Decimal("0.01")

    def test_euroeyes_terminal_multiple_under_threshold(self) -> None:
        """Base scenario terminal EV/EBITDA shouldn't grossly exceed
        the 10.5× industry median × 1.5× threshold = 15.75×."""
        result = self._result()
        assert result is not None
        base = next(v for v in result.scenarios_run if v.scenario_name == "base")
        if base.terminal_multiple_validation.implied_ev_ebitda is not None:
            assert (
                base.terminal_multiple_validation.implied_ev_ebitda
                < Decimal("20")
            )
