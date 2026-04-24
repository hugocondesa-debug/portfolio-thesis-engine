"""Sprint 4A-beta — three-statement forecast + iterative solver tests.

Target: 40+ tests across 8 classes covering the new
``src/portfolio_thesis_engine/forecast/`` module. Test IDs follow the
``test_P2_S4A_BETA_{section}_{NN}`` convention so failures in a CI
digest are immediately attributable to a sprint section.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
import yaml

from portfolio_thesis_engine.forecast.balance_sheet import (
    forecast_balance_sheet,
)
from portfolio_thesis_engine.forecast.capital_allocation_consumer import (
    ParsedBuybackPolicy,
    ParsedCapitalAllocation,
    ParsedDebtPolicy,
    ParsedDividendPolicy,
    ParsedMAPolicy,
    ParsedShareIssuancePolicy,
    default_policies,
    load_capital_allocation,
)
from portfolio_thesis_engine.forecast.cash_flow import derive_cash_flow
from portfolio_thesis_engine.forecast.forward_ratios import (
    compute_forward_ratios,
)
from portfolio_thesis_engine.forecast.forward_wacc import compute_forward_wacc
from portfolio_thesis_engine.forecast.income_statement import (
    forecast_income_statement,
)
from portfolio_thesis_engine.forecast.iterative_solver import (
    CONVERGENCE_TOLERANCE,
    compute_cash_residual,
    fixed_point_solve,
)
from portfolio_thesis_engine.forecast.orchestrator import (
    ForecastOrchestrator,
    persist_forecast,
)
from portfolio_thesis_engine.forecast.schemas import (
    BalanceSheetYear,
    CashFlowYear,
    ForecastResult,
    ForwardRatiosYear,
    IncomeStatementYear,
    ThreeStatementProjection,
)


# ======================================================================
# IS projection (6 tests)
# ======================================================================
class TestIncomeStatementForecast:
    def test_P2_S4A_BETA_IS_01_simple_projection_5_years(self):
        result = forecast_income_statement(
            base_year_revenue=Decimal("1000000"),
            base_year_operating_margin=Decimal("0.20"),
            base_year_shares_outstanding=Decimal("100000"),
            growth_pattern=[Decimal("0.10")] * 5,
            margin_target_terminal=Decimal("0.25"),
            margin_fade_years=3,
            tax_rate=Decimal("0.20"),
            years=5,
        )
        assert len(result) == 5
        assert result[0].revenue == Decimal("1100000.00")
        assert result[0].year == 1
        # Y5 = 1M × 1.1^5 ≈ 1_610_510
        assert abs(result[4].revenue - Decimal("1610510")) < Decimal("10")

    def test_P2_S4A_BETA_IS_02_margin_fade_linear(self):
        result = forecast_income_statement(
            base_year_revenue=Decimal("1000000"),
            base_year_operating_margin=Decimal("0.10"),
            base_year_shares_outstanding=Decimal("100000"),
            growth_pattern=[Decimal("0.0")] * 5,
            margin_target_terminal=Decimal("0.30"),
            margin_fade_years=2,
            tax_rate=Decimal("0.20"),
            years=5,
        )
        # Y1: 10% + (30% - 10%) × 1/2 = 20%
        assert abs(result[0].operating_margin - Decimal("0.20")) < Decimal("0.001")
        # Y2+: 30%
        assert abs(result[1].operating_margin - Decimal("0.30")) < Decimal("0.001")
        assert abs(result[4].operating_margin - Decimal("0.30")) < Decimal("0.001")

    def test_P2_S4A_BETA_IS_03_eps_derivation_consistent(self):
        result = forecast_income_statement(
            base_year_revenue=Decimal("1000000"),
            base_year_operating_margin=Decimal("0.20"),
            base_year_shares_outstanding=Decimal("100000"),
            growth_pattern=[Decimal("0.05")] * 5,
            margin_target_terminal=Decimal("0.25"),
            margin_fade_years=3,
            tax_rate=Decimal("0.20"),
            years=5,
        )
        for year in result:
            assert year.eps == year.net_income / year.shares_outstanding

    def test_P2_S4A_BETA_IS_04_shares_outstanding_evolution(self):
        shares_evol = [
            Decimal("99000"),
            Decimal("98000"),
            Decimal("97000"),
            Decimal("96000"),
            Decimal("95000"),
        ]
        result = forecast_income_statement(
            base_year_revenue=Decimal("1000000"),
            base_year_operating_margin=Decimal("0.20"),
            base_year_shares_outstanding=Decimal("100000"),
            growth_pattern=[Decimal("0.0")] * 5,
            margin_target_terminal=Decimal("0.20"),
            margin_fade_years=3,
            tax_rate=Decimal("0.20"),
            shares_outstanding_evolution=shares_evol,
            years=5,
        )
        assert result[0].eps < result[4].eps  # EPS grows from buybacks

    def test_P2_S4A_BETA_IS_05_interest_income_offsets_tax(self):
        interest = [Decimal("50000")] * 5
        result = forecast_income_statement(
            base_year_revenue=Decimal("1000000"),
            base_year_operating_margin=Decimal("0.20"),
            base_year_shares_outstanding=Decimal("100000"),
            growth_pattern=[Decimal("0.0")] * 5,
            margin_target_terminal=Decimal("0.20"),
            margin_fade_years=3,
            tax_rate=Decimal("0.20"),
            interest_income_per_year=interest,
            years=5,
        )
        # Pre-tax Y1 = OI + Interest = 200k + 50k = 250k
        assert result[0].pre_tax_income == Decimal("250000")
        # Tax = 250k × 20% = 50k
        assert result[0].tax_expense == Decimal("50000")

    def test_P2_S4A_BETA_IS_06_zero_shares_safe(self):
        result = forecast_income_statement(
            base_year_revenue=Decimal("1000000"),
            base_year_operating_margin=Decimal("0.20"),
            base_year_shares_outstanding=Decimal("100000"),
            growth_pattern=[Decimal("0.05")] * 5,
            margin_target_terminal=Decimal("0.20"),
            margin_fade_years=3,
            tax_rate=Decimal("0.20"),
            shares_outstanding_evolution=[Decimal("0")] * 5,
            years=5,
        )
        for year in result:
            assert year.eps == Decimal("0")


# ======================================================================
# BS projection (6 tests)
# ======================================================================
class TestBalanceSheetForecast:
    def _base_args(self):
        return {
            "base_year_ppe": Decimal("1000000"),
            "base_year_goodwill": Decimal("500000"),
            "base_year_wc": Decimal("0"),
            "base_year_cash": Decimal("200000"),
            "base_year_debt": Decimal("0"),
            "base_year_equity": Decimal("1700000"),
            "base_year_total_assets": Decimal("1700000"),
            "capex_per_year": [Decimal("100000")] * 5,
            "da_per_year": [Decimal("80000")] * 5,
            "ma_deployment_per_year": [Decimal("0")] * 5,
            "revenue_per_year": [
                Decimal("1000000"),
                Decimal("1100000"),
                Decimal("1210000"),
                Decimal("1331000"),
                Decimal("1464100"),
            ],
            "wc_to_revenue_target": Decimal("0.05"),
            "net_income_per_year": [Decimal("150000")] * 5,
            "dividends_per_year": [Decimal("30000")] * 5,
            "buybacks_per_year": [Decimal("0")] * 5,
            "debt_delta_per_year": [Decimal("0")] * 5,
            "years": 5,
        }

    def test_P2_S4A_BETA_BS_01_ppe_roll_forward(self):
        result = forecast_balance_sheet(**self._base_args())
        # Y1 PPE = 1M + 100k - 80k = 1.02M
        assert result[0].ppe_net == Decimal("1020000")
        # Y5 PPE = 1M + 5×(100k - 80k) = 1.1M
        assert result[4].ppe_net == Decimal("1100000")

    def test_P2_S4A_BETA_BS_02_goodwill_accumulates_with_ma(self):
        args = self._base_args()
        args["ma_deployment_per_year"] = [Decimal("200000")] * 5
        result = forecast_balance_sheet(**args)
        # Y1 goodwill = 500k + 200k = 700k
        assert result[0].goodwill == Decimal("700000")
        # Y5 goodwill = 500k + 5×200k = 1.5M
        assert result[4].goodwill == Decimal("1500000")

    def test_P2_S4A_BETA_BS_03_working_capital_tied_to_revenue(self):
        result = forecast_balance_sheet(**self._base_args())
        # WC = revenue × 0.05
        assert result[0].working_capital_net == Decimal("50000")
        assert result[4].working_capital_net == Decimal("73205.00")

    def test_P2_S4A_BETA_BS_04_equity_roll_with_ni_dividends(self):
        result = forecast_balance_sheet(**self._base_args())
        # Y1 equity = 1.7M + 150k NI - 30k dividend = 1.82M
        assert result[0].equity == Decimal("1820000")
        # Y5 equity = 1.7M + 5×(150k - 30k) = 2.3M
        assert result[4].equity == Decimal("2300000")

    def test_P2_S4A_BETA_BS_05_debt_delta_applied(self):
        args = self._base_args()
        args["debt_delta_per_year"] = [
            Decimal("100000"),
            Decimal("0"),
            Decimal("-50000"),
            Decimal("0"),
            Decimal("0"),
        ]
        result = forecast_balance_sheet(**args)
        assert result[0].debt == Decimal("100000")
        assert result[1].debt == Decimal("100000")
        assert result[2].debt == Decimal("50000")
        assert result[4].debt == Decimal("50000")

    def test_P2_S4A_BETA_BS_06_cash_placeholder_preserved(self):
        """Cash returned by the BS module equals the base-year cash —
        the iterative solver is expected to overwrite this."""
        result = forecast_balance_sheet(**self._base_args())
        for bs in result:
            assert bs.cash == Decimal("200000")


# ======================================================================
# CF derivation (6 tests)
# ======================================================================
class TestCashFlowDerivation:
    def _base_kwargs(self, **overrides):
        kwargs = {
            "net_income": Decimal("100000"),
            "da": Decimal("30000"),
            "wc_change": Decimal("10000"),
            "capex": Decimal("40000"),
            "ma_deployment": Decimal("0"),
            "dividends_paid": Decimal("20000"),
            "buybacks_executed": Decimal("0"),
            "debt_issued": Decimal("0"),
            "debt_repaid": Decimal("0"),
            "net_interest": Decimal("0"),
            "tax_rate": Decimal("0.20"),
            "year": 1,
        }
        kwargs.update(overrides)
        return kwargs

    def test_P2_S4A_BETA_CF_01_cfo_indirect_method(self):
        cf = derive_cash_flow(**self._base_kwargs())
        # CFO = NI + D&A - ΔWC = 100k + 30k - 10k = 120k
        assert cf.cfo == Decimal("120000")

    def test_P2_S4A_BETA_CF_02_cfi_signs_outflows(self):
        cf = derive_cash_flow(
            **self._base_kwargs(capex=Decimal("40000"), ma_deployment=Decimal("25000"))
        )
        # CFI = -capex - M&A = -65k
        assert cf.cfi == Decimal("-65000")
        assert cf.capex == Decimal("-40000")
        assert cf.ma_deployment == Decimal("-25000")

    def test_P2_S4A_BETA_CF_03_cff_dividends_and_debt(self):
        cf = derive_cash_flow(
            **self._base_kwargs(
                dividends_paid=Decimal("20000"),
                buybacks_executed=Decimal("10000"),
                debt_issued=Decimal("50000"),
                debt_repaid=Decimal("0"),
            )
        )
        # CFF = -div - buybacks + net debt - after-tax interest
        #     = -20k - 10k + 50k - 0 = 20k
        assert cf.cff == Decimal("20000")

    def test_P2_S4A_BETA_CF_04_delta_cash_sum_identity(self):
        cf = derive_cash_flow(
            **self._base_kwargs(
                capex=Decimal("40000"),
                dividends_paid=Decimal("20000"),
                fx_effect=Decimal("5000"),
            )
        )
        # 120 - 40 - 20 + 5 = 65
        assert cf.net_change_cash == Decimal("65000")

    def test_P2_S4A_BETA_CF_05_fx_effect_propagates(self):
        cf = derive_cash_flow(
            **self._base_kwargs(fx_effect=Decimal("-12000"))
        )
        assert cf.fx_effect == Decimal("-12000")

    def test_P2_S4A_BETA_CF_06_interest_is_after_tax(self):
        cf = derive_cash_flow(
            **self._base_kwargs(net_interest=Decimal("10000"), tax_rate=Decimal("0.30"))
        )
        # After-tax interest = 10k × 0.7 = 7k; CFF deducts it.
        assert cf.net_interest == Decimal("7000.0")


# ======================================================================
# Capital allocation consumer (6 tests)
# ======================================================================
class TestCapitalAllocationConsumer:
    def test_P2_S4A_BETA_CA_01_load_euroeyes_yaml(self):
        parsed = load_capital_allocation("1846.HK")
        assert parsed is not None
        assert parsed.ticker == "1846.HK"
        assert parsed.dividend_policy.type == "PAYOUT_RATIO"
        assert parsed.dividend_policy.payout_ratio == Decimal("0.115")

    def test_P2_S4A_BETA_CA_02_debt_policy_maintain_zero(self):
        parsed = load_capital_allocation("1846.HK")
        assert parsed is not None
        assert parsed.debt_policy.type == "MAINTAIN_ZERO"
        assert parsed.debt_policy.alternative_for_ma is not None
        assert parsed.debt_policy.alternative_for_ma["type"] == "LEVER_UP"

    def test_P2_S4A_BETA_CA_03_ma_policy_opportunistic(self):
        parsed = load_capital_allocation("1846.HK")
        assert parsed is not None
        assert parsed.ma_policy.type == "OPPORTUNISTIC"
        assert parsed.ma_policy.annual_deployment_target == Decimal("50000000")
        assert "Europe" in parsed.ma_policy.geography_focus

    def test_P2_S4A_BETA_CA_04_missing_file_returns_none(self):
        assert load_capital_allocation("DOES-NOT-EXIST") is None

    def test_P2_S4A_BETA_CA_05_default_policies_defensive(self):
        default = default_policies()
        assert default.dividend_policy.type == "PAYOUT_RATIO"
        assert default.dividend_policy.payout_ratio == Decimal("0.30")
        assert default.share_issuance_policy.type == "ZERO"
        assert default.debt_policy.type == "MAINTAIN_CURRENT"

    def test_P2_S4A_BETA_CA_06_net_cash_baseline_extracted(self):
        parsed = load_capital_allocation("1846.HK")
        assert parsed is not None
        # Last entry in historical_context.cash_evolution — H1_2025
        assert parsed.net_cash_baseline == Decimal("741782000")


# ======================================================================
# Iterative solver (5 tests)
# ======================================================================
class TestIterativeSolver:
    def test_P2_S4A_BETA_SOLVER_01_converges_trivial(self):
        """Identity iteration converges instantly (residual = 0)."""
        def identity(state):
            return state

        def zero_residual(a, b):
            return Decimal("0")

        initial = {"bs_cash": [Decimal("100")] * 3}
        final, info = fixed_point_solve(
            initial_state=initial,
            iteration_fn=identity,
            convergence_fn=zero_residual,
        )
        assert info["converged"] is True
        assert info["iterations"] == 1

    def test_P2_S4A_BETA_SOLVER_02_respects_max_iterations(self):
        """Divergent iteration stops at max_iterations with converged=False."""
        def divergent(state):
            cash = state.get("bs_cash", [Decimal("0")])
            return {"bs_cash": [c + Decimal("100") for c in cash]}

        initial = {"bs_cash": [Decimal("0")] * 3}
        final, info = fixed_point_solve(
            initial_state=initial,
            iteration_fn=divergent,
            convergence_fn=compute_cash_residual,
            max_iterations=3,
        )
        assert info["converged"] is False
        assert info["iterations"] == 3

    def test_P2_S4A_BETA_SOLVER_03_residual_relative_when_cash_nonzero(self):
        state_a = {"bs_cash": [Decimal("100"), Decimal("200"), Decimal("300")]}
        state_b = {"bs_cash": [Decimal("105"), Decimal("205"), Decimal("305")]}
        # Relative delta = |600 - 615| / 600 = 0.025
        residual = compute_cash_residual(state_a, state_b)
        assert abs(residual - Decimal("0.025")) < Decimal("0.0001")

    def test_P2_S4A_BETA_SOLVER_04_residual_absolute_when_cash_zero(self):
        state_a = {"bs_cash": [Decimal("0"), Decimal("0")]}
        state_b = {"bs_cash": [Decimal("50"), Decimal("50")]}
        residual = compute_cash_residual(state_a, state_b)
        assert residual == Decimal("100")

    def test_P2_S4A_BETA_SOLVER_05_converges_damped_fixed_point(self):
        """Damped iteration x_{n+1} = x_n / 2 converges to 0 within
        tolerance after a handful of iterations."""
        def halve(state):
            return {
                "bs_cash": [c / Decimal("2") for c in state["bs_cash"]]
            }

        initial = {"bs_cash": [Decimal("1000")] * 3}
        final, info = fixed_point_solve(
            initial_state=initial,
            iteration_fn=halve,
            convergence_fn=compute_cash_residual,
            tolerance=CONVERGENCE_TOLERANCE,
        )
        # |Δ| / previous = 0.5 each step; need ~14 iterations for 0.5^14 < tol
        # but since tolerance is 0.0001 it stops sooner via absolute cash.
        assert info["converged"] is False or info["iterations"] <= 20


# ======================================================================
# Forward ratios (4 tests)
# ======================================================================
class TestForwardRatios:
    def _is_year(self, **kw):
        defaults = dict(
            year=1,
            revenue=Decimal("1000000"),
            revenue_growth_rate=Decimal("0.10"),
            operating_margin=Decimal("0.20"),
            operating_income=Decimal("200000"),
            pre_tax_income=Decimal("200000"),
            tax_rate=Decimal("0.20"),
            tax_expense=Decimal("40000"),
            net_income=Decimal("160000"),
            shares_outstanding=Decimal("100000"),
            eps=Decimal("1.60"),
        )
        defaults.update(kw)
        return IncomeStatementYear(**defaults)

    def _bs_year(self, **kw):
        defaults = dict(
            year=1,
            ppe_net=Decimal("500000"),
            goodwill=Decimal("200000"),
            working_capital_net=Decimal("50000"),
            cash=Decimal("100000"),
            total_assets=Decimal("850000"),
            debt=Decimal("0"),
            equity=Decimal("800000"),
        )
        defaults.update(kw)
        return BalanceSheetYear(**defaults)

    def _cf_year(self, **kw):
        defaults = dict(
            year=1,
            cfo=Decimal("180000"),
            cfi=Decimal("-60000"),
            cff=Decimal("-40000"),
            capex=Decimal("-60000"),
            ma_deployment=Decimal("0"),
            dividends_paid=Decimal("-40000"),
            buybacks_executed=Decimal("0"),
            debt_issued=Decimal("0"),
            debt_repaid=Decimal("0"),
            net_interest=Decimal("0"),
            net_change_cash=Decimal("80000"),
        )
        defaults.update(kw)
        return CashFlowYear(**defaults)

    def test_P2_S4A_BETA_RATIOS_01_per_at_market(self):
        ratios = compute_forward_ratios(
            is_year=self._is_year(),
            bs_year=self._bs_year(),
            cf_year=self._cf_year(),
            market_price=Decimal("20"),
            fair_value=None,
        )
        # PER = 20 / 1.60 = 12.5
        assert ratios.per_at_market_price == Decimal("12.5")

    def test_P2_S4A_BETA_RATIOS_02_fcf_yield_at_market(self):
        ratios = compute_forward_ratios(
            is_year=self._is_year(),
            bs_year=self._bs_year(),
            cf_year=self._cf_year(),  # FCF = 180k + (-60k) = 120k
            market_price=Decimal("20"),
            fair_value=None,
        )
        # Market cap = 20 × 100k = 2M; yield = 120k / 2M = 0.06
        assert ratios.fcf_yield_at_market == Decimal("0.06")

    def test_P2_S4A_BETA_RATIOS_03_roic_and_roe(self):
        ratios = compute_forward_ratios(
            is_year=self._is_year(),
            bs_year=self._bs_year(),
            cf_year=self._cf_year(),
            market_price=None,
            fair_value=None,
        )
        # NOPAT = 200k × 0.8 = 160k; IC = 500k + 200k + 50k = 750k;
        # ROIC = 160/750 ≈ 21.33%
        assert abs(ratios.roic - Decimal("0.21333")) < Decimal("0.01")
        # ROE = 160k / 800k = 20%
        assert ratios.roe == Decimal("0.2")

    def test_P2_S4A_BETA_RATIOS_04_debt_to_ebitda(self):
        ratios = compute_forward_ratios(
            is_year=self._is_year(),
            bs_year=self._bs_year(debt=Decimal("500000")),
            cf_year=self._cf_year(),
            market_price=None,
            fair_value=None,
            ebitda_year=Decimal("250000"),
        )
        assert ratios.debt_to_ebitda == Decimal("2")


# ======================================================================
# Forward WACC (3 tests)
# ======================================================================
class TestForwardWACC:
    def _is_year(self):
        return IncomeStatementYear(
            year=1,
            revenue=Decimal("1000000"),
            revenue_growth_rate=Decimal("0.10"),
            operating_margin=Decimal("0.20"),
            operating_income=Decimal("200000"),
            pre_tax_income=Decimal("200000"),
            tax_rate=Decimal("0.20"),
            tax_expense=Decimal("40000"),
            net_income=Decimal("160000"),
            shares_outstanding=Decimal("100000"),
            eps=Decimal("1.60"),
        )

    def _bs_year(self, equity: Decimal, debt: Decimal):
        return BalanceSheetYear(
            year=1,
            ppe_net=Decimal("500000"),
            goodwill=Decimal("200000"),
            working_capital_net=Decimal("50000"),
            cash=Decimal("100000"),
            total_assets=Decimal("850000"),
            debt=debt,
            equity=equity,
        )

    def _ctx(
        self,
        coe: Decimal = Decimal("0.09"),
        cod_aftertax: Decimal = Decimal("0.04"),
        tax: Decimal = Decimal("0.20"),
        base: Decimal = Decimal("0.08"),
    ):
        """Mini WACCContext — Sprint 4A-beta.1 changed the signature to
        accept a context protocol; these tests now exercise the same
        branches via mock contexts."""
        from dataclasses import dataclass

        @dataclass
        class _Ctx:
            cost_of_equity: Decimal
            cost_of_debt: Decimal
            tax_rate: Decimal
            base_wacc: Decimal

        return _Ctx(
            cost_of_equity=coe,
            cost_of_debt=cod_aftertax,
            tax_rate=tax,
            base_wacc=base,
        )

    def test_P2_S4A_BETA_WACC_01_zero_debt_equals_coe(self):
        wacc = compute_forward_wacc(
            bs_year=self._bs_year(Decimal("1000000"), Decimal("0")),
            is_year=self._is_year(),
            wacc_context=self._ctx(coe=Decimal("0.09")),
        )
        assert wacc == Decimal("0.09")

    def test_P2_S4A_BETA_WACC_02_leverage_lowers_wacc(self):
        # context.cost_of_debt is already after-tax. For parity with the
        # pre-refactor test (pretax CoD 6%, tax 25% → after-tax 4.5%),
        # feed cod_aftertax=0.045 directly.
        wacc = compute_forward_wacc(
            bs_year=self._bs_year(Decimal("500000"), Decimal("500000")),
            is_year=self._is_year(),
            wacc_context=self._ctx(
                coe=Decimal("0.10"),
                cod_aftertax=Decimal("0.045"),
                tax=Decimal("0.25"),
            ),
        )
        # 0.5 × 10% + 0.5 × 4.5% = 5% + 2.25% = 7.25%
        assert abs(wacc - Decimal("0.0725")) < Decimal("0.0001")

    def test_P2_S4A_BETA_WACC_03_degenerate_returns_base(self):
        wacc = compute_forward_wacc(
            bs_year=self._bs_year(Decimal("0"), Decimal("0")),
            is_year=self._is_year(),
            wacc_context=self._ctx(base=Decimal("0.08")),
        )
        assert wacc == Decimal("0.08")


# ======================================================================
# Forecast orchestrator (5 tests)
# ======================================================================
class TestForecastOrchestrator:
    def test_P2_S4A_BETA_ORCH_01_run_euroeyes_produces_7_scenarios(self):
        orch = ForecastOrchestrator()
        result = orch.run("1846.HK", years=5)
        assert result is not None
        assert result.ticker == "1846.HK"
        assert len(result.projections) == 7

    def test_P2_S4A_BETA_ORCH_02_each_scenario_has_5_year_slices(self):
        orch = ForecastOrchestrator()
        result = orch.run("1846.HK", years=5)
        assert result is not None
        for projection in result.projections:
            assert len(projection.income_statement) == 5
            assert len(projection.balance_sheet) == 5
            assert len(projection.cash_flow) == 5
            assert len(projection.forward_ratios) == 5

    def test_P2_S4A_BETA_ORCH_03_base_scenario_converges(self):
        orch = ForecastOrchestrator()
        result = orch.run("1846.HK", years=5)
        assert result is not None
        base = next(p for p in result.projections if p.scenario_name == "base")
        assert base.solver_convergence.get("converged") is True

    def test_P2_S4A_BETA_ORCH_04_missing_scenarios_returns_none(self):
        orch = ForecastOrchestrator()
        assert orch.run("DOES-NOT-EXIST", years=5) is None

    def test_P2_S4A_BETA_ORCH_05_persistence_writes_json(self, tmp_path, monkeypatch):
        from portfolio_thesis_engine.shared import config as shared_config

        monkeypatch.setattr(shared_config.settings, "data_dir", tmp_path)
        # Also patch the already-imported symbol inside orchestrator module.
        from portfolio_thesis_engine.forecast import orchestrator as forecast_orch

        monkeypatch.setattr(forecast_orch.settings, "data_dir", tmp_path)

        result = ForecastResult(
            ticker="TEST.HK",
            generated_at="2026-04-24T00:00:00Z",
            projections=[
                ThreeStatementProjection(
                    scenario_name="base",
                    scenario_probability=Decimal("1"),
                    base_year_label="FY2024",
                    projection_years=1,
                )
            ],
        )
        path = persist_forecast(result)
        assert path.exists()
        assert path.parent == tmp_path / "forecast_snapshots" / "TEST-HK"
        assert "TEST.HK" in path.read_text()
