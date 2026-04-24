"""Sprint 4B Residual Income tests — P5 banks + P2 insurance alt."""

from __future__ import annotations

from decimal import Decimal

import pytest

from portfolio_thesis_engine.dcf.engine import ValuationEngine
from portfolio_thesis_engine.dcf.p1_engine import PeriodInputs
from portfolio_thesis_engine.dcf.schemas import (
    DCFMethodologyConfig,
    DCFProfile,
    ProfileSelection,
    ResidualIncomeMethodologyConfig,
    Scenario,
    ScenarioSet,
    ValuationMethodology,
    ValuationProfile,
)
from portfolio_thesis_engine.forecast.schemas import ForecastResult
from portfolio_thesis_engine.valuation_methodologies.residual_income import (
    RIEngine,
    compute_beginning_book_values,
    extract_book_value_stream,
)
from tests.fixtures.forecast_fixtures import build_synthetic_projection


# ======================================================================
# Book value extractor (4 tests)
# ======================================================================
class TestBookValueExtractor:
    def test_P2_S4B_RI_01_extracts_ending_equity_per_year(self):
        projection = build_synthetic_projection(
            equity_per_year=[
                Decimal("900_000_000"),
                Decimal("950_000_000"),
                Decimal("1_000_000_000"),
            ]
        )
        stream = extract_book_value_stream(projection)
        assert len(stream) == 3
        assert stream[0][1] == Decimal("900_000_000")
        assert stream[2][1] == Decimal("1_000_000_000")

    def test_P2_S4B_RI_02_extracts_net_income_per_year(self):
        projection = build_synthetic_projection(
            net_income_per_year=[
                Decimal("50_000_000"),
                Decimal("55_000_000"),
            ]
        )
        stream = extract_book_value_stream(projection)
        assert [item[2] for item in stream] == [
            Decimal("50_000_000"),
            Decimal("55_000_000"),
        ]

    def test_P2_S4B_RI_03_beginning_book_value_calc(self):
        beginnings = compute_beginning_book_values(
            base_equity=Decimal("100"),
            ending_equities=[
                Decimal("110"),
                Decimal("120"),
                Decimal("130"),
            ],
        )
        # Y1 begin = base; Y2 begin = Y1 ending; Y3 begin = Y2 ending.
        assert beginnings == [Decimal("100"), Decimal("110"), Decimal("120")]

    def test_P2_S4B_RI_04_handles_single_year_projection(self):
        beginnings = compute_beginning_book_values(
            base_equity=Decimal("100"),
            ending_equities=[Decimal("110")],
        )
        assert beginnings == [Decimal("100")]


# ======================================================================
# RI Engine (15 tests)
# ======================================================================
class TestRIEngine:
    def test_P2_S4B_RI_10_basic_positive_ri_stream(self):
        """NI=100, beg equity=900, CoE=10% → RI = 100 - 90 = 10."""
        projection = build_synthetic_projection(
            net_income_per_year=[Decimal("100_000_000")] * 5,
            equity_per_year=[Decimal("900_000_000")] * 5,
        )
        result = RIEngine().compute(
            projection=projection,
            cost_of_equity=Decimal("0.10"),
            base_equity=Decimal("900_000_000"),
            terminal_growth_rate=Decimal("0.02"),
        )
        assert result.methodology == "RESIDUAL_INCOME"
        assert result.base_book_value == Decimal("900_000_000")
        # Y1 RI = 100M - 90M = 10M (positive).
        assert result.years[0].residual_income == Decimal("10_000_000")
        assert result.enterprise_value > result.base_book_value

    def test_P2_S4B_RI_11_negative_ri_ev_below_book(self):
        """NI=50, beg equity=900, CoE=10% → RI = 50 - 90 = -40."""
        projection = build_synthetic_projection(
            net_income_per_year=[Decimal("50_000_000")] * 5,
            equity_per_year=[Decimal("900_000_000")] * 5,
        )
        result = RIEngine().compute(
            projection=projection,
            cost_of_equity=Decimal("0.10"),
            base_equity=Decimal("900_000_000"),
            terminal_growth_rate=Decimal("0.02"),
        )
        assert result.years[0].residual_income == Decimal("-40_000_000")
        assert result.enterprise_value < result.base_book_value

    def test_P2_S4B_RI_12_zero_ri_ev_equals_book(self):
        """NI equals required return → RI = 0, EV ≈ BV."""
        projection = build_synthetic_projection(
            net_income_per_year=[Decimal("90_000_000")] * 5,
            equity_per_year=[Decimal("900_000_000")] * 5,
        )
        result = RIEngine().compute(
            projection=projection,
            cost_of_equity=Decimal("0.10"),
            base_equity=Decimal("900_000_000"),
            terminal_growth_rate=Decimal("0.02"),
        )
        assert result.years[0].residual_income == Decimal("0")
        # Terminal RI = 0 × 1.02 = 0 → terminal value = 0. Sum PV RI = 0.
        # EV = 900M + 0 + 0 = 900M.
        assert abs(result.enterprise_value - Decimal("900_000_000")) < Decimal("100")

    def test_P2_S4B_RI_13_identity_ev_equals_bv_plus_pv_stream(self):
        projection = build_synthetic_projection(
            net_income_per_year=[Decimal("100_000_000")] * 5,
            equity_per_year=[Decimal("900_000_000")] * 5,
        )
        result = RIEngine().compute(
            projection=projection,
            cost_of_equity=Decimal("0.10"),
            base_equity=Decimal("900_000_000"),
            terminal_growth_rate=Decimal("0.02"),
        )
        implied = (
            result.base_book_value
            + result.sum_pv_residual_income
            + result.terminal_pv
        )
        assert abs(result.enterprise_value - implied) < Decimal("1")

    def test_P2_S4B_RI_14_rejects_growth_above_discount_rate(self):
        projection = build_synthetic_projection(
            net_income_per_year=[Decimal("100_000_000")] * 5,
        )
        with pytest.raises(ValueError, match="Terminal growth"):
            RIEngine().compute(
                projection=projection,
                cost_of_equity=Decimal("0.05"),
                base_equity=Decimal("900_000_000"),
                terminal_growth_rate=Decimal("0.06"),
            )

    def test_P2_S4B_RI_15_rejects_non_positive_base_equity(self):
        projection = build_synthetic_projection(
            net_income_per_year=[Decimal("100_000_000")] * 5,
        )
        with pytest.raises(ValueError, match="[Bb]ase equity"):
            RIEngine().compute(
                projection=projection,
                cost_of_equity=Decimal("0.10"),
                base_equity=Decimal("0"),
            )

    def test_P2_S4B_RI_16_fair_value_per_share_derivation(self):
        projection = build_synthetic_projection(
            net_income_per_year=[Decimal("100_000_000")] * 5,
            equity_per_year=[Decimal("900_000_000")] * 5,
            shares_outstanding=Decimal("100_000_000"),
        )
        result = RIEngine().compute(
            projection=projection,
            cost_of_equity=Decimal("0.10"),
            base_equity=Decimal("900_000_000"),
            terminal_growth_rate=Decimal("0.02"),
        )
        expected = result.equity_value / Decimal("100_000_000")
        assert abs(result.fair_value_per_share - expected) < Decimal("0.001")

    def test_P2_S4B_RI_17_growing_ni_increases_ri(self):
        """Rising NI with flat equity → rising RI stream."""
        projection = build_synthetic_projection(
            net_income_per_year=[
                Decimal("100_000_000"),
                Decimal("110_000_000"),
                Decimal("120_000_000"),
                Decimal("130_000_000"),
                Decimal("140_000_000"),
            ],
            equity_per_year=[Decimal("900_000_000")] * 5,
        )
        result = RIEngine().compute(
            projection=projection,
            cost_of_equity=Decimal("0.10"),
            base_equity=Decimal("900_000_000"),
            terminal_growth_rate=Decimal("0.02"),
        )
        # RI grows each year (NI rises, required return flat).
        ris = [y.residual_income for y in result.years]
        assert ris == sorted(ris)
        assert ris[-1] > ris[0]

    def test_P2_S4B_RI_18_terminal_negative_ri_warning(self):
        projection = build_synthetic_projection(
            net_income_per_year=[Decimal("50_000_000")] * 5,
            equity_per_year=[Decimal("900_000_000")] * 5,
        )
        result = RIEngine().compute(
            projection=projection,
            cost_of_equity=Decimal("0.10"),
            base_equity=Decimal("900_000_000"),
            terminal_growth_rate=Decimal("0.02"),
        )
        assert any("below CoE" in w for w in result.warnings)

    def test_P2_S4B_RI_19_negative_sum_pv_ri_warning(self):
        projection = build_synthetic_projection(
            net_income_per_year=[Decimal("50_000_000")] * 5,
            equity_per_year=[Decimal("900_000_000")] * 5,
        )
        result = RIEngine().compute(
            projection=projection,
            cost_of_equity=Decimal("0.10"),
            base_equity=Decimal("900_000_000"),
            terminal_growth_rate=Decimal("0.02"),
        )
        assert result.sum_pv_residual_income < 0
        assert any("value destruction" in w for w in result.warnings)

    def test_P2_S4B_RI_20_coe_equals_roe_matches_book(self):
        """ROE=CoE → RI=0 every year → EV ≈ BV."""
        # NI 100M on equity 1000M = 10% ROE; CoE 10% → zero RI.
        projection = build_synthetic_projection(
            net_income_per_year=[Decimal("100_000_000")] * 5,
            equity_per_year=[Decimal("1_000_000_000")] * 5,
        )
        result = RIEngine().compute(
            projection=projection,
            cost_of_equity=Decimal("0.10"),
            base_equity=Decimal("1_000_000_000"),
            terminal_growth_rate=Decimal("0.02"),
        )
        assert abs(result.enterprise_value - result.base_book_value) < Decimal("100")

    def test_P2_S4B_RI_21_high_roe_higher_ev(self):
        """Higher ROE → higher EV (above book)."""
        low = build_synthetic_projection(
            net_income_per_year=[Decimal("100_000_000")] * 5,
            equity_per_year=[Decimal("1_000_000_000")] * 5,
        )
        high = build_synthetic_projection(
            net_income_per_year=[Decimal("150_000_000")] * 5,
            equity_per_year=[Decimal("1_000_000_000")] * 5,
        )
        engine = RIEngine()
        low_result = engine.compute(
            projection=low,
            cost_of_equity=Decimal("0.10"),
            base_equity=Decimal("1_000_000_000"),
            terminal_growth_rate=Decimal("0.02"),
        )
        high_result = engine.compute(
            projection=high,
            cost_of_equity=Decimal("0.10"),
            base_equity=Decimal("1_000_000_000"),
            terminal_growth_rate=Decimal("0.02"),
        )
        assert high_result.enterprise_value > low_result.enterprise_value

    def test_P2_S4B_RI_22_terminal_discount_rate_override(self):
        projection = build_synthetic_projection(
            net_income_per_year=[Decimal("100_000_000")] * 5,
            equity_per_year=[Decimal("900_000_000")] * 5,
        )
        engine = RIEngine()
        default = engine.compute(
            projection=projection,
            cost_of_equity=Decimal("0.10"),
            base_equity=Decimal("900_000_000"),
            terminal_growth_rate=Decimal("0.02"),
        )
        override = engine.compute(
            projection=projection,
            cost_of_equity=Decimal("0.10"),
            base_equity=Decimal("900_000_000"),
            terminal_growth_rate=Decimal("0.02"),
            terminal_discount_rate=Decimal("0.15"),
        )
        # Higher terminal discount → lower terminal value → lower EV.
        assert override.terminal_value < default.terminal_value

    def test_P2_S4B_RI_23_yearly_ri_structure_valid(self):
        projection = build_synthetic_projection(
            net_income_per_year=[Decimal("100_000_000")] * 3,
            equity_per_year=[Decimal("900_000_000")] * 3,
        )
        result = RIEngine().compute(
            projection=projection,
            cost_of_equity=Decimal("0.10"),
            base_equity=Decimal("900_000_000"),
            terminal_growth_rate=Decimal("0.02"),
        )
        for ri_year in result.years:
            assert ri_year.beginning_book_value > 0
            assert ri_year.discount_factor < Decimal("1")
            # required_return = CoE × beg BV always.
            assert abs(
                ri_year.required_return
                - Decimal("0.10") * ri_year.beginning_book_value
            ) < Decimal("1")

    def test_P2_S4B_RI_24_pv_discount_factors_match_dcf(self):
        projection = build_synthetic_projection(
            net_income_per_year=[Decimal("100_000_000")] * 3,
            equity_per_year=[Decimal("900_000_000")] * 3,
        )
        result = RIEngine().compute(
            projection=projection,
            cost_of_equity=Decimal("0.10"),
            base_equity=Decimal("900_000_000"),
            terminal_growth_rate=Decimal("0.02"),
        )
        # Y1 DF = 1/1.10 ≈ 0.9091; Y3 DF = 1/1.10^3 ≈ 0.7513.
        assert abs(result.years[0].discount_factor - Decimal("0.9091")) < Decimal("0.001")
        assert abs(result.years[2].discount_factor - Decimal("0.7513")) < Decimal("0.001")


# ======================================================================
# RI orchestrator integration (6 tests)
# ======================================================================
def _profile() -> ValuationProfile:
    return ValuationProfile(
        target_ticker="TEST.HK",
        profile=ProfileSelection(code=DCFProfile.P1_INDUSTRIAL_SERVICES),
    )


def _period_inputs(
    cost_of_equity: Decimal | None = Decimal("0.10"),
    equity_claims: Decimal | None = Decimal("900_000_000"),
) -> PeriodInputs:
    return PeriodInputs(
        ticker="TEST.HK",
        stage_1_wacc=Decimal("0.10"),
        stage_3_wacc=Decimal("0.08"),
        shares_outstanding=Decimal("100_000_000"),
        cost_of_equity=cost_of_equity,
        equity_claims=equity_claims,
    )


def _ri_scenario(
    name: str = "ri_base",
    cost_of_equity_override: Decimal | None = None,
) -> Scenario:
    return Scenario(
        name=name,
        probability=Decimal("1"),
        methodology=ResidualIncomeMethodologyConfig(
            terminal_growth=Decimal("0.025"),
            cost_of_equity_override=cost_of_equity_override,
        ),
    )


def _forecast_result(
    scenarios: list[Scenario], ni: Decimal = Decimal("100_000_000")
) -> ForecastResult:
    projections = [
        build_synthetic_projection(
            scenario_name=s.name,
            net_income_per_year=[ni] * 5,
            equity_per_year=[Decimal("900_000_000")] * 5,
        )
        for s in scenarios
    ]
    return ForecastResult(
        ticker="TEST.HK",
        generated_at="2026-04-24T00:00:00Z",
        projections=projections,
    )


class TestRIOrchestratorIntegration:
    def test_P2_S4B_RI_30_dispatches_residual_income_scenario(self):
        scenario = _ri_scenario()
        scenario_set = ScenarioSet(
            target_ticker="TEST.HK",
            valuation_profile=DCFProfile.P1_INDUSTRIAL_SERVICES,
            base_year="FY2024",
            scenarios=[scenario],
        )
        result = ValuationEngine().run(
            valuation_profile=_profile(),
            scenario_set=scenario_set,
            period_inputs=_period_inputs(),
            forecast_result=_forecast_result([scenario]),
        )
        assert len(result.scenarios_run) == 1
        assert (
            result.scenarios_run[0].methodology_used
            == ValuationMethodology.RESIDUAL_INCOME
        )

    def test_P2_S4B_RI_31_scenario_result_has_fair_value_per_share(self):
        scenario = _ri_scenario()
        scenario_set = ScenarioSet(
            target_ticker="TEST.HK",
            valuation_profile=DCFProfile.P1_INDUSTRIAL_SERVICES,
            base_year="FY2024",
            scenarios=[scenario],
        )
        result = ValuationEngine().run(
            valuation_profile=_profile(),
            scenario_set=scenario_set,
            period_inputs=_period_inputs(),
            forecast_result=_forecast_result([scenario]),
        )
        assert result.scenarios_run[0].fair_value_per_share > Decimal("0")

    def test_P2_S4B_RI_32_wacc_context_coe_used_when_no_override(self):
        scenario = _ri_scenario()
        scenario_set = ScenarioSet(
            target_ticker="TEST.HK",
            valuation_profile=DCFProfile.P1_INDUSTRIAL_SERVICES,
            base_year="FY2024",
            scenarios=[scenario],
        )
        result = ValuationEngine().run(
            valuation_profile=_profile(),
            scenario_set=scenario_set,
            period_inputs=_period_inputs(cost_of_equity=Decimal("0.08")),
            forecast_result=_forecast_result([scenario]),
        )
        assert (
            result.scenarios_run[0].methodology_summary["cost_of_equity_applied"]
            == Decimal("0.08")
        )

    def test_P2_S4B_RI_33_scenario_coe_override_precedence(self):
        scenario = _ri_scenario(cost_of_equity_override=Decimal("0.12"))
        scenario_set = ScenarioSet(
            target_ticker="TEST.HK",
            valuation_profile=DCFProfile.P1_INDUSTRIAL_SERVICES,
            base_year="FY2024",
            scenarios=[scenario],
        )
        result = ValuationEngine().run(
            valuation_profile=_profile(),
            scenario_set=scenario_set,
            period_inputs=_period_inputs(cost_of_equity=Decimal("0.08")),
            forecast_result=_forecast_result([scenario]),
        )
        assert (
            result.scenarios_run[0].methodology_summary["cost_of_equity_applied"]
            == Decimal("0.12")
        )

    def test_P2_S4B_RI_34_base_equity_from_period_inputs(self):
        scenario = _ri_scenario()
        scenario_set = ScenarioSet(
            target_ticker="TEST.HK",
            valuation_profile=DCFProfile.P1_INDUSTRIAL_SERVICES,
            base_year="FY2024",
            scenarios=[scenario],
        )
        custom_base = Decimal("1_500_000_000")
        result = ValuationEngine().run(
            valuation_profile=_profile(),
            scenario_set=scenario_set,
            period_inputs=_period_inputs(equity_claims=custom_base),
            forecast_result=_forecast_result([scenario]),
        )
        # base_book_value flows into methodology_summary.
        assert (
            result.scenarios_run[0].methodology_summary["base_book_value"]
            == custom_base
        )

    def test_P2_S4B_RI_35_mixed_scenario_set_dcf_and_ri(self):
        ri = _ri_scenario(name="ri_one")
        ri.probability = Decimal("0.5")
        dcf = Scenario(
            name="dcf_one",
            probability=Decimal("0.5"),
            methodology=DCFMethodologyConfig(
                type="DCF_3_STAGE",
                explicit_years=5,
                fade_years=5,
                terminal_growth=Decimal("0.025"),
            ),
        )
        scenario_set = ScenarioSet(
            target_ticker="TEST.HK",
            valuation_profile=DCFProfile.P1_INDUSTRIAL_SERVICES,
            base_year="FY2024",
            base_drivers={
                "revenue": {"base_year_value": 100_000_000, "growth_pattern": [0.05] * 5},
                "operating_margin": {"current": 0.20, "target_terminal": 0.20},
                "tax_rate": {"statutory": 0.20},
                "capex_intensity": {"current": 0.05, "target": 0.05},
                "working_capital_intensity": {"current": 0.0, "target": 0.0},
                "depreciation_rate": {"current": 0.08},
            },
            scenarios=[ri, dcf],
        )
        result = ValuationEngine().run(
            valuation_profile=_profile(),
            scenario_set=scenario_set,
            period_inputs=_period_inputs(),
            forecast_result=_forecast_result([ri]),
        )
        names = {v.scenario_name for v in result.scenarios_run}
        assert names == {"ri_one", "dcf_one"}
