"""Unit tests for extraction.analysis.AnalysisDeriver."""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from portfolio_thesis_engine.extraction.analysis import AnalysisDeriver
from portfolio_thesis_engine.extraction.base import (
    ExtractionContext,
    parse_fiscal_period,
)
from portfolio_thesis_engine.schemas.common import Profile
from portfolio_thesis_engine.schemas.company import ModuleAdjustment
from portfolio_thesis_engine.schemas.wacc import (
    CapitalStructure,
    CostOfCapitalInputs,
    ScenarioDriversManual,
    WACCInputs,
)
from portfolio_thesis_engine.section_extractor.base import StructuredSection


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


def _section(section_type: str, parsed: dict[str, Any] | None) -> StructuredSection:
    return StructuredSection(
        section_type=section_type,
        title=section_type,
        content="",
        parsed_data=parsed,
    )


def _make_context(
    wacc: WACCInputs,
    sections: list[StructuredSection],
    adjustments: list[ModuleAdjustment] | None = None,
) -> ExtractionContext:
    ctx = ExtractionContext(
        ticker="TST",
        fiscal_period_label="FY2024",
        primary_period=parse_fiscal_period("FY2024"),
        sections=sections,
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


def _b2_adj(amount: str | Decimal, subtype: str = "goodwill_impairment") -> ModuleAdjustment:
    return ModuleAdjustment(
        module=f"B.2.{subtype}",
        description="test non-op",
        amount=Decimal(str(amount)),
        affected_periods=[parse_fiscal_period("FY2024")],
        rationale="test",
    )


_IS_PARSED = {
    "line_items": [
        {"label": "Revenue", "value_current": 1000, "category": "revenue"},
        {"label": "D&A", "value_current": 80, "category": "d_and_a"},
        {"label": "Operating income", "value_current": 200, "category": "operating_income"},
        {"label": "Finance income", "value_current": 5, "category": "finance_income"},
        {"label": "Finance expense", "value_current": 25, "category": "finance_expense"},
        {"label": "Net income", "value_current": 140, "category": "net_income"},
    ],
}

_BS_PARSED = {
    "line_items": [
        {"label": "Cash", "value_current": 200, "category": "cash"},
        {"label": "Receivables", "value_current": 300, "category": "operating_assets"},
        {"label": "PP&E", "value_current": 700, "category": "operating_assets"},
        {"label": "Trade payables", "value_current": 150, "category": "operating_liabilities"},
        {"label": "Debt", "value_current": 400, "category": "financial_liabilities"},
        {"label": "Equity", "value_current": 650, "category": "equity"},
    ],
}

_CF_PARSED = {
    "line_items": [
        {"label": "CFO", "value_current": 180, "category": "cfo"},
        {"label": "CapEx", "value_current": -60, "category": "capex"},
    ],
}


# ======================================================================
# 1. InvestedCapital
# ======================================================================


class TestInvestedCapital:
    def test_ic_identity_holds(self, _wacc: WACCInputs) -> None:
        sections = [_section("balance_sheet", _BS_PARSED)]
        ctx = _make_context(_wacc, sections)
        result = AnalysisDeriver().derive(ctx)
        ic = result.invested_capital_by_period[0]

        # Op assets = 1000 (300+700), Op liab = 150, IC = 850
        assert ic.operating_assets == Decimal("1000")
        assert ic.operating_liabilities == Decimal("150")
        assert ic.invested_capital == Decimal("850")
        # Financial assets (cash only) = 200; financial_liabilities = 400
        assert ic.financial_assets == Decimal("200")
        assert ic.financial_liabilities == Decimal("400")
        assert ic.equity_claims == Decimal("650")
        # Residual = 850 + 200 - 650 - 0 - 400 = 0
        assert ic.cross_check_residual == Decimal("0")

    def test_missing_bs_yields_zero_ic(self, _wacc: WACCInputs) -> None:
        ctx = _make_context(_wacc, sections=[])
        ic = AnalysisDeriver().derive(ctx).invested_capital_by_period[0]
        assert ic.invested_capital == Decimal("0")
        assert ic.cross_check_residual == Decimal("0")


# ======================================================================
# 2. NOPAT Bridge
# ======================================================================


class TestNOPATBridge:
    def test_ebitda_is_op_income_plus_da(self, _wacc: WACCInputs) -> None:
        ctx = _make_context(
            _wacc,
            [_section("income_statement", _IS_PARSED)],
            adjustments=[_op_tax_rate_adj("25")],
        )
        bridge = AnalysisDeriver().derive(ctx).nopat_bridge_by_period[0]
        # D&A 80 is added back: EBITDA = 200 + 80 = 280
        assert bridge.ebitda == Decimal("280")
        # EBITA stays None because the parser doesn't split D from A.
        assert bridge.ebita is None
        # Operating taxes anchor off EBITDA when EBITA is absent:
        # 280 * 25% = 70, NOPAT = 210
        assert bridge.operating_taxes == Decimal("70")
        assert bridge.nopat == Decimal("210")

    def test_bridge_uses_op_tax_rate_from_a1(self, _wacc: WACCInputs) -> None:
        ctx = _make_context(
            _wacc,
            [_section("income_statement", _IS_PARSED)],
            adjustments=[_op_tax_rate_adj("17")],
        )
        bridge = AnalysisDeriver().derive(ctx).nopat_bridge_by_period[0]
        # 280 * 17% = 47.60
        assert bridge.operating_taxes == Decimal("47.60")

    def test_non_operating_sums_is_and_b2(self, _wacc: WACCInputs) -> None:
        is_with_nonop = {
            "line_items": [
                *_IS_PARSED["line_items"],
                {
                    "label": "One-off",
                    "value_current": -10,
                    "category": "non_operating",
                },
            ],
        }
        ctx = _make_context(
            _wacc,
            [_section("income_statement", is_with_nonop)],
            adjustments=[
                _op_tax_rate_adj("25"),
                _b2_adj("-20"),  # One Module B adjustment
            ],
        )
        bridge = AnalysisDeriver().derive(ctx).nopat_bridge_by_period[0]
        # IS non-op -10 + B.2 adjustment -20 = -30
        assert bridge.non_operating_items == Decimal("-30")

    def test_missing_a1_leaves_op_tax_zero(self, _wacc: WACCInputs) -> None:
        ctx = _make_context(_wacc, [_section("income_statement", _IS_PARSED)])
        bridge = AnalysisDeriver().derive(ctx).nopat_bridge_by_period[0]
        assert bridge.operating_taxes == Decimal("0")

    def test_finance_lines_captured(self, _wacc: WACCInputs) -> None:
        ctx = _make_context(
            _wacc,
            [_section("income_statement", _IS_PARSED)],
            adjustments=[_op_tax_rate_adj("25")],
        )
        bridge = AnalysisDeriver().derive(ctx).nopat_bridge_by_period[0]
        assert bridge.financial_income == Decimal("5")
        assert bridge.financial_expense == Decimal("25")
        assert bridge.reported_net_income == Decimal("140")


# ======================================================================
# 3. KeyRatios
# ======================================================================


class TestKeyRatios:
    def test_roic_roe_margins(self, _wacc: WACCInputs) -> None:
        sections = [
            _section("income_statement", _IS_PARSED),
            _section("balance_sheet", _BS_PARSED),
            _section("cash_flow", _CF_PARSED),
        ]
        ctx = _make_context(_wacc, sections, adjustments=[_op_tax_rate_adj("25")])
        ratios = AnalysisDeriver().derive(ctx).ratios_by_period[0]

        # NOPAT = 210, IC = 850 → ROIC ≈ 24.7%
        assert ratios.roic is not None
        assert abs(ratios.roic - Decimal("24.705882352941176")) < Decimal("0.01")
        # NI = 140, Equity = 650 → ROE ≈ 21.54%
        assert ratios.roe is not None
        assert abs(ratios.roe - Decimal("21.538461538461538")) < Decimal("0.01")
        # Op income 200 / Revenue 1000 = 20%
        assert ratios.operating_margin == Decimal("20")
        # EBITDA already includes D&A (Op Income 200 + D&A 80 = 280); margin = 28%
        assert ratios.ebitda_margin == Decimal("28")
        # Net debt = 400 - 200 = 200; EBITDA 280; ratio ≈ 0.714
        assert ratios.net_debt_ebitda is not None
        assert abs(ratios.net_debt_ebitda - Decimal("0.714285714")) < Decimal("0.01")
        # CapEx 60 / Revenue 1000 = 6%
        assert ratios.capex_revenue == Decimal("6")

    def test_zero_revenue_yields_none_margins(self, _wacc: WACCInputs) -> None:
        is_empty = {
            "line_items": [
                {"label": "Revenue", "value_current": 0, "category": "revenue"},
            ],
        }
        ctx = _make_context(
            _wacc,
            [_section("income_statement", is_empty)],
            adjustments=[_op_tax_rate_adj("25")],
        )
        ratios = AnalysisDeriver().derive(ctx).ratios_by_period[0]
        # Division by zero → None
        assert ratios.operating_margin is None
        assert ratios.ebitda_margin is None

    def test_missing_sections_yield_none_or_zero_gracefully(
        self, _wacc: WACCInputs
    ) -> None:
        # No sections — everything defaults
        ctx = _make_context(_wacc, sections=[])
        result = AnalysisDeriver().derive(ctx)
        assert result.ratios_by_period[0].roic is None
        assert result.invested_capital_by_period[0].invested_capital == Decimal("0")
        # EBITDA is always populated (zero when no lines); EBITA stays None.
        assert result.nopat_bridge_by_period[0].ebitda == Decimal("0")
        assert result.nopat_bridge_by_period[0].ebita is None
