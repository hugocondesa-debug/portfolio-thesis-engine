"""Unit tests for extraction.analysis.AnalysisDeriver (Phase 1.5)."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from portfolio_thesis_engine.extraction.analysis import AnalysisDeriver
from portfolio_thesis_engine.extraction.base import (
    ExtractionContext,
    parse_fiscal_period,
)
from portfolio_thesis_engine.schemas.common import Currency, Profile
from portfolio_thesis_engine.schemas.company import ModuleAdjustment
from portfolio_thesis_engine.schemas.raw_extraction import (
    DocumentType,
    ExtractionType,
    RawExtraction,
)
from portfolio_thesis_engine.schemas.wacc import (
    CapitalStructure,
    CostOfCapitalInputs,
    ScenarioDriversManual,
    WACCInputs,
)


@pytest.fixture
def _wacc() -> WACCInputs:
    return WACCInputs(
        ticker="TST",
        profile=Profile.P1_INDUSTRIAL,
        valuation_date="2024-12-31",
        current_price=Decimal("100"),
        cost_of_capital=CostOfCapitalInputs(
            risk_free_rate=Decimal("3"),
            equity_risk_premium=Decimal("5"),
            beta=Decimal("1"),
            cost_of_debt_pretax=Decimal("5"),
            tax_rate_for_wacc=Decimal("25"),
        ),
        capital_structure=CapitalStructure(
            debt_weight=Decimal("30"),
            equity_weight=Decimal("70"),
        ),
        scenarios={
            "base": ScenarioDriversManual(
                probability=Decimal("100"),
                revenue_cagr_explicit_period=Decimal("5"),
                terminal_growth=Decimal("2"),
                terminal_operating_margin=Decimal("18"),
            )
        },
    )


def _build_raw(
    *,
    is_: dict[str, Decimal] | None = None,
    bs: dict[str, Decimal] | None = None,
    cf: dict[str, Decimal] | None = None,
) -> RawExtraction:
    payload: dict[str, Any] = {
        "metadata": {
            "ticker": "TST",
            "company_name": "Test Co",
            "document_type": DocumentType.ANNUAL_REPORT,
            "extraction_type": ExtractionType.NUMERIC,
            "reporting_currency": Currency.USD,
            "unit_scale": "units",
            "fiscal_year": 2024,
            "extraction_date": "2025-01-01",
            "fiscal_periods": [
                {"period": "FY2024", "end_date": "2024-12-31", "is_primary": True},
            ],
        },
        "income_statement": {
            "FY2024": is_
            or {
                "revenue": Decimal("1"),
                "net_income": Decimal("0"),
            },
        },
        "balance_sheet": {
            "FY2024": bs
            or {
                "total_assets": Decimal("1000"),
                "total_equity": Decimal("1000"),
                "total_equity_parent": Decimal("1000"),
            },
        },
    }
    if cf is not None:
        payload["cash_flow"] = {"FY2024": cf}
    return RawExtraction.model_validate(payload)


def _make_context(
    wacc: WACCInputs,
    raw: RawExtraction,
    adjustments: list[ModuleAdjustment] | None = None,
) -> ExtractionContext:
    ctx = ExtractionContext(
        ticker="TST",
        fiscal_period_label="FY2024",
        primary_period=parse_fiscal_period("FY2024"),
        raw_extraction=raw,
        wacc_inputs=wacc,
    )
    if adjustments:
        ctx.adjustments.extend(adjustments)
    return ctx


def _op_tax_rate_adj(rate_pct: str | Decimal) -> ModuleAdjustment:
    return ModuleAdjustment(
        module="A.1",
        description="Operating tax rate",
        amount=Decimal(str(rate_pct)),
        affected_periods=[parse_fiscal_period("FY2024")],
        rationale="test",
    )


_IS_TEST = {
    "revenue": Decimal("1000"),
    "depreciation_amortization": Decimal("-80"),
    "operating_income": Decimal("200"),
    "finance_income": Decimal("5"),
    "finance_expenses": Decimal("-25"),
    "net_income": Decimal("140"),
}

_BS_TEST = {
    "cash_and_equivalents": Decimal("200"),
    "accounts_receivable": Decimal("300"),
    "ppe_net": Decimal("700"),
    "accounts_payable": Decimal("150"),
    "long_term_debt": Decimal("400"),
    "total_equity_parent": Decimal("650"),
    "total_equity": Decimal("650"),
}

_CF_TEST = {
    "operating_cash_flow": Decimal("180"),
    "capex": Decimal("-60"),
}


# ======================================================================
# 1. InvestedCapital
# ======================================================================


class TestInvestedCapital:
    def test_ic_identity_holds(self, _wacc: WACCInputs) -> None:
        raw = _build_raw(bs=_BS_TEST)
        ctx = _make_context(_wacc, raw)
        ic = AnalysisDeriver().derive(ctx).invested_capital_by_period[0]

        # Op assets = 300 (AR) + 700 (PP&E) = 1000, Op liab = 150 (AP) → IC = 850
        assert ic.operating_assets == Decimal("1000")
        assert ic.operating_liabilities == Decimal("150")
        assert ic.invested_capital == Decimal("850")
        # Financial: cash 200, debt 400
        assert ic.financial_assets == Decimal("200")
        assert ic.financial_liabilities == Decimal("400")
        assert ic.equity_claims == Decimal("650")
        # Residual = 850 + 200 - 650 - 0 - 400 = 0
        assert ic.cross_check_residual == Decimal("0")

    def test_missing_bs_yields_zero_ic(self, _wacc: WACCInputs) -> None:
        # BS with only the identity fields → AR/PP&E absent, IC → 0
        raw = _build_raw(
            bs={"total_assets": Decimal("1"), "total_equity": Decimal("1")}
        )
        ctx = _make_context(_wacc, raw)
        ic = AnalysisDeriver().derive(ctx).invested_capital_by_period[0]
        assert ic.invested_capital == Decimal("0")

    def test_equity_parent_fallback_to_total_minus_nci(
        self, _wacc: WACCInputs
    ) -> None:
        raw = _build_raw(
            bs={
                "total_assets": Decimal("100"),
                "total_equity": Decimal("100"),
                "non_controlling_interests": Decimal("20"),
            }
        )
        ctx = _make_context(_wacc, raw)
        ic = AnalysisDeriver().derive(ctx).invested_capital_by_period[0]
        # total_equity_parent absent → falls back to 100 - 20 = 80
        assert ic.equity_claims == Decimal("80")
        assert ic.nci_claims == Decimal("20")


# ======================================================================
# 2. NOPAT Bridge
# ======================================================================


class TestNOPATBridge:
    def test_ebitda_is_op_income_plus_da(self, _wacc: WACCInputs) -> None:
        raw = _build_raw(is_=_IS_TEST)
        ctx = _make_context(_wacc, raw, adjustments=[_op_tax_rate_adj("25")])
        bridge = AnalysisDeriver().derive(ctx).nopat_bridge_by_period[0]

        # EBITDA = 200 + |-80| = 280
        assert bridge.ebitda == Decimal("280")
        assert bridge.ebita is None
        # 280 × 25% = 70 → NOPAT 210
        assert bridge.operating_taxes == Decimal("70")
        assert bridge.nopat == Decimal("210")

    def test_bridge_uses_op_tax_rate_from_a1(self, _wacc: WACCInputs) -> None:
        raw = _build_raw(is_=_IS_TEST)
        ctx = _make_context(_wacc, raw, adjustments=[_op_tax_rate_adj("17")])
        bridge = AnalysisDeriver().derive(ctx).nopat_bridge_by_period[0]
        # 280 × 17% = 47.60
        assert bridge.operating_taxes == Decimal("47.60")

    def test_non_operating_from_is_fields(self, _wacc: WACCInputs) -> None:
        is_with_nonop = dict(_IS_TEST)
        is_with_nonop["non_operating_income"] = Decimal("-10")
        is_with_nonop["share_of_associates"] = Decimal("3")
        raw = _build_raw(is_=is_with_nonop)
        ctx = _make_context(_wacc, raw, adjustments=[_op_tax_rate_adj("25")])
        bridge = AnalysisDeriver().derive(ctx).nopat_bridge_by_period[0]
        assert bridge.non_operating_items == Decimal("-7")

    def test_missing_a1_leaves_op_tax_zero(self, _wacc: WACCInputs) -> None:
        raw = _build_raw(is_=_IS_TEST)
        ctx = _make_context(_wacc, raw)
        bridge = AnalysisDeriver().derive(ctx).nopat_bridge_by_period[0]
        assert bridge.operating_taxes == Decimal("0")

    def test_finance_lines_captured(self, _wacc: WACCInputs) -> None:
        raw = _build_raw(is_=_IS_TEST)
        ctx = _make_context(_wacc, raw, adjustments=[_op_tax_rate_adj("25")])
        bridge = AnalysisDeriver().derive(ctx).nopat_bridge_by_period[0]
        assert bridge.financial_income == Decimal("5")
        # finance_expenses -25 → absolute value 25
        assert bridge.financial_expense == Decimal("25")
        assert bridge.reported_net_income == Decimal("140")


# ======================================================================
# 3. KeyRatios
# ======================================================================


class TestKeyRatios:
    def test_roic_roe_margins(self, _wacc: WACCInputs) -> None:
        raw = _build_raw(is_=_IS_TEST, bs=_BS_TEST, cf=_CF_TEST)
        ctx = _make_context(_wacc, raw, adjustments=[_op_tax_rate_adj("25")])
        ratios = AnalysisDeriver().derive(ctx).ratios_by_period[0]

        # NOPAT 210 / IC 850 → ROIC ≈ 24.7%
        assert ratios.roic is not None
        assert abs(ratios.roic - Decimal("24.705882352941176")) < Decimal("0.01")
        # NI 140 / Equity 650 → ROE ≈ 21.54%
        assert ratios.roe is not None
        assert abs(ratios.roe - Decimal("21.538461538461538")) < Decimal("0.01")
        # Op margin 200/1000 = 20%
        assert ratios.operating_margin == Decimal("20")
        # EBITDA margin 280/1000 = 28%
        assert ratios.ebitda_margin == Decimal("28")
        # Net debt 400 - 200 = 200 / 280 ≈ 0.714
        assert ratios.net_debt_ebitda is not None
        assert abs(ratios.net_debt_ebitda - Decimal("0.714285714")) < Decimal("0.01")
        # CapEx 60 / 1000 = 6%
        assert ratios.capex_revenue == Decimal("6")

    def test_zero_revenue_yields_none_margins(self, _wacc: WACCInputs) -> None:
        raw = _build_raw(
            is_={"revenue": Decimal("0"), "net_income": Decimal("0")},
        )
        ctx = _make_context(_wacc, raw, adjustments=[_op_tax_rate_adj("25")])
        ratios = AnalysisDeriver().derive(ctx).ratios_by_period[0]
        assert ratios.operating_margin is None
        assert ratios.ebitda_margin is None
