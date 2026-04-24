"""Sprint 4A-beta.1 cleanup tests.

Covers:
- ``compute_forward_wacc`` integration with a Sprint-3 ``WACCContext``
  (zero-debt and levered branches).
- ``ForecastOrchestrator._load_market_price`` parsing the production
  ``wacc_inputs.md``.
- End-to-end propagation from WACCGenerator → forward_ratios so
  ``per_at_market_price`` populates on a live run for 1846.HK.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from portfolio_thesis_engine.forecast.forward_wacc import compute_forward_wacc
from portfolio_thesis_engine.forecast.orchestrator import (
    ForecastOrchestrator,
    ForwardWACCContext,
)
from portfolio_thesis_engine.forecast.schemas import (
    BalanceSheetYear,
    IncomeStatementYear,
)


@dataclass
class _MockCtx:
    cost_of_equity: Decimal
    cost_of_debt: Decimal
    tax_rate: Decimal
    base_wacc: Decimal


def _is_year(revenue: Decimal = Decimal("100")) -> IncomeStatementYear:
    return IncomeStatementYear(
        year=1,
        revenue=revenue,
        revenue_growth_rate=Decimal("0.1"),
        operating_margin=Decimal("0.20"),
        operating_income=revenue * Decimal("0.20"),
        pre_tax_income=revenue * Decimal("0.20"),
        tax_rate=Decimal("0.20"),
        tax_expense=revenue * Decimal("0.04"),
        net_income=revenue * Decimal("0.16"),
        shares_outstanding=Decimal("100"),
        eps=revenue * Decimal("0.16") / Decimal("100"),
    )


def _bs_year(equity: Decimal, debt: Decimal) -> BalanceSheetYear:
    return BalanceSheetYear(
        year=1,
        ppe_net=Decimal("100"),
        goodwill=Decimal("0"),
        working_capital_net=Decimal("0"),
        cash=Decimal("0"),
        total_assets=equity + debt,
        debt=debt,
        equity=equity,
    )


class TestWACCIntegration:
    def test_P2_S4A_BETA_1_WACC_01_integrates_with_sprint3_engine(self):
        """Zero-debt scenario uses CoE directly (equity weight 100%)."""
        ctx = _MockCtx(
            cost_of_equity=Decimal("0.10"),
            cost_of_debt=Decimal("0.04"),
            tax_rate=Decimal("0.20"),
            base_wacc=Decimal("0.10"),
        )
        wacc = compute_forward_wacc(
            bs_year=_bs_year(Decimal("170"), Decimal("0")),
            is_year=_is_year(),
            wacc_context=ctx,
        )
        assert wacc == Decimal("0.10")

    def test_P2_S4A_BETA_1_WACC_02_levered_reduces_wacc(self):
        """50/50 D/E with after-tax CoD < CoE drops WACC below CoE."""
        # context.cost_of_debt is already after-tax per the WACCContext
        # contract — supply 0.04 (CoD_after_tax = 0.05 × 0.80 = 0.04).
        ctx = _MockCtx(
            cost_of_equity=Decimal("0.10"),
            cost_of_debt=Decimal("0.04"),
            tax_rate=Decimal("0.20"),
            base_wacc=Decimal("0.10"),
        )
        wacc = compute_forward_wacc(
            bs_year=_bs_year(Decimal("100"), Decimal("100")),
            is_year=_is_year(),
            wacc_context=ctx,
        )
        # 0.5 × 0.10 + 0.5 × 0.04 = 0.07
        assert abs(wacc - Decimal("0.07")) < Decimal("0.0001")

    def test_P2_S4A_BETA_1_WACC_03_fallback_when_context_none(self):
        """Without wacc_context, function returns fallback_base_wacc."""
        wacc = compute_forward_wacc(
            bs_year=_bs_year(Decimal("170"), Decimal("0")),
            is_year=_is_year(),
            wacc_context=None,
            fallback_base_wacc=Decimal("0.08"),
        )
        assert wacc == Decimal("0.08")


class TestMarketPriceIntegration:
    def test_P2_S4A_BETA_1_MKT_01_loads_market_price_from_wacc_inputs(self):
        """Orchestrator parses ``current_price`` from wacc_inputs.md."""
        orch = ForecastOrchestrator()
        price = orch._load_market_price("1846.HK")  # noqa: SLF001
        assert price is not None
        # EuroEyes share price ~HK$2.92 per the current wacc_inputs.md.
        assert Decimal("2.0") < price < Decimal("5.0")

    def test_P2_S4A_BETA_1_MKT_02_forecast_populates_per_mkt(self):
        """Live run populates ``per_at_market_price`` on forward ratios."""
        orch = ForecastOrchestrator()
        result = orch.run("1846.HK")
        assert result is not None
        assert result.projections

        base_proj = next(
            p for p in result.projections if p.scenario_name == "base"
        )
        y1_ratios = base_proj.forward_ratios[0]

        assert y1_ratios.per_at_market_price is not None
        # EuroEyes base Y1 EPS ~0.35, price ~2.92 → PER ≈ 8.35×
        assert Decimal("5") < y1_ratios.per_at_market_price < Decimal("20")

    def test_P2_S4A_BETA_1_MKT_03_wacc_is_sprint3_generated(self):
        """Live run populates WACC with the Sprint-3 generator value,
        not the old 8.00% hardcoded fallback. EuroEyes 8.06% per
        pte analyze."""
        orch = ForecastOrchestrator()
        result = orch.run("1846.HK")
        assert result is not None

        base_proj = next(
            p for p in result.projections if p.scenario_name == "base"
        )
        y1_wacc = base_proj.forward_ratios[0].wacc_applied
        assert y1_wacc is not None
        # Should NOT be exactly 0.08 (the fallback) — expect ~0.0806.
        assert y1_wacc != Decimal("0.08")
        assert Decimal("0.06") < y1_wacc < Decimal("0.12")


class TestForwardWACCContextDataclass:
    def test_P2_S4A_BETA_1_CTX_01_forward_wacc_context_exposes_protocol(self):
        """ForwardWACCContext dataclass satisfies the WACCContext protocol."""
        ctx = ForwardWACCContext(
            cost_of_equity=Decimal("0.08"),
            cost_of_debt=Decimal("0.04"),
            tax_rate=Decimal("0.20"),
            base_wacc=Decimal("0.08"),
        )
        # All four protocol fields accessible as attributes.
        assert ctx.cost_of_equity == Decimal("0.08")
        assert ctx.cost_of_debt == Decimal("0.04")
        assert ctx.tax_rate == Decimal("0.20")
        assert ctx.base_wacc == Decimal("0.08")
