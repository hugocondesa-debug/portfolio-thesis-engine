"""Unit tests for extraction.analysis.AnalysisDeriver (Phase 1.5.3)."""

from __future__ import annotations

from decimal import Decimal

from portfolio_thesis_engine.extraction.analysis import AnalysisDeriver
from portfolio_thesis_engine.extraction.base import parse_fiscal_period
from portfolio_thesis_engine.schemas.company import ModuleAdjustment
from portfolio_thesis_engine.schemas.wacc import WACCInputs

from .conftest import build_raw, make_context

# ----------------------------------------------------------------------
# Canonical fixtures
# ----------------------------------------------------------------------

_IS_LINES = [
    {"order": 1, "label": "Revenue", "value": "1000"},
    {"order": 2, "label": "Cost of sales", "value": "-600"},
    {"order": 3, "label": "Gross profit", "value": "400", "is_subtotal": True},
    {"order": 4, "label": "Depreciation and amortisation", "value": "-80"},
    {"order": 5, "label": "Other operating expenses", "value": "-120"},
    {
        "order": 6, "label": "Operating profit",
        "value": "200", "is_subtotal": True,
    },
    {"order": 7, "label": "Finance income", "value": "5"},
    {"order": 8, "label": "Finance costs", "value": "-25"},
    {
        "order": 9, "label": "Profit before taxation",
        "value": "180", "is_subtotal": True,
    },
    {"order": 10, "label": "Income tax", "value": "-40"},
    {
        "order": 11, "label": "Profit for the year",
        "value": "140", "is_subtotal": True,
    },
]

_BS_LINES = [
    {
        "order": 1, "label": "Cash and cash equivalents",
        "value": "200", "section": "current_assets",
    },
    {
        "order": 2, "label": "Trade receivables",
        "value": "300", "section": "current_assets",
    },
    {
        "order": 3, "label": "Total current assets",
        "value": "500", "section": "current_assets",
        "is_subtotal": True,
    },
    {
        "order": 4, "label": "Property, plant and equipment",
        "value": "700", "section": "non_current_assets",
    },
    {
        "order": 5, "label": "Total non-current assets",
        "value": "700", "section": "non_current_assets",
        "is_subtotal": True,
    },
    {
        "order": 6, "label": "Total assets",
        "value": "1200", "section": "total_assets",
        "is_subtotal": True,
    },
    {
        "order": 7, "label": "Trade payables",
        "value": "150", "section": "current_liabilities",
    },
    {
        "order": 8, "label": "Total current liabilities",
        "value": "150", "section": "current_liabilities",
        "is_subtotal": True,
    },
    {
        "order": 9, "label": "Long-term borrowings",
        "value": "400", "section": "non_current_liabilities",
    },
    {
        "order": 10, "label": "Total non-current liabilities",
        "value": "400", "section": "non_current_liabilities",
        "is_subtotal": True,
    },
    {
        "order": 11, "label": "Total liabilities",
        "value": "550", "section": "total_liabilities",
        "is_subtotal": True,
    },
    {
        "order": 12, "label": "Share capital", "value": "250",
        "section": "equity",
    },
    {
        "order": 13, "label": "Retained earnings", "value": "400",
        "section": "equity",
    },
    {
        "order": 14, "label": "Equity attributable to owners of the Company",
        "value": "650", "section": "equity", "is_subtotal": True,
    },
    {
        "order": 15, "label": "Total equity", "value": "650",
        "section": "equity", "is_subtotal": True,
    },
]

_CF_LINES = [
    {
        "order": 1, "label": "Net cash generated from operating activities",
        "value": "180", "section": "operating", "is_subtotal": True,
    },
    {
        "order": 2, "label": "Purchase of property, plant and equipment",
        "value": "-60", "section": "investing",
    },
    {
        "order": 3, "label": "Net cash used in investing activities",
        "value": "-60", "section": "investing", "is_subtotal": True,
    },
]


def _op_tax_rate_adj(rate_pct: str) -> ModuleAdjustment:
    return ModuleAdjustment(
        module="A.1",
        description="Operating tax rate",
        amount=Decimal(rate_pct),
        affected_periods=[parse_fiscal_period("FY2024")],
        rationale="test",
    )


class TestInvestedCapital:
    def test_ic_from_label_and_section(self, wacc_inputs: WACCInputs) -> None:
        raw = build_raw(bs_lines=_BS_LINES)
        ctx = make_context(raw, wacc_inputs)
        ic = AnalysisDeriver().derive(ctx).invested_capital_by_period[0]
        # Operating assets: Trade receivables (300) + PP&E (700) = 1000
        assert ic.operating_assets == Decimal("1000")
        # Operating liabilities: Trade payables (150)
        assert ic.operating_liabilities == Decimal("150")
        assert ic.invested_capital == Decimal("850")
        # Financial assets: Cash (200)
        assert ic.financial_assets == Decimal("200")
        # Financial liabilities: Long-term borrowings (400)
        assert ic.financial_liabilities == Decimal("400")
        # Equity from "Equity attributable to owners" subtotal
        assert ic.equity_claims == Decimal("650")
        # 850 + 200 - 650 - 0 - 400 = 0
        assert ic.cross_check_residual == Decimal("0")

    def test_missing_bs_yields_zero(self, wacc_inputs: WACCInputs) -> None:
        raw = build_raw()  # default: just Total assets placeholder
        ctx = make_context(raw, wacc_inputs)
        ic = AnalysisDeriver().derive(ctx).invested_capital_by_period[0]
        assert ic.invested_capital == Decimal("0")


class TestNOPATBridge:
    def test_ebitda_op_income_plus_da(self, wacc_inputs: WACCInputs) -> None:
        raw = build_raw(is_lines=_IS_LINES)
        ctx = make_context(raw, wacc_inputs)
        ctx.adjustments.append(_op_tax_rate_adj("25"))
        bridge = AnalysisDeriver().derive(ctx).nopat_bridge_by_period[0]
        # Op income 200 + |D&A| 80 = 280
        assert bridge.ebitda == Decimal("280")
        assert bridge.ebita is None
        # 280 * 25% = 70
        assert bridge.operating_taxes == Decimal("70")
        assert bridge.nopat == Decimal("210")

    def test_finance_lines_captured(self, wacc_inputs: WACCInputs) -> None:
        raw = build_raw(is_lines=_IS_LINES)
        ctx = make_context(raw, wacc_inputs)
        ctx.adjustments.append(_op_tax_rate_adj("25"))
        bridge = AnalysisDeriver().derive(ctx).nopat_bridge_by_period[0]
        assert bridge.financial_income == Decimal("5")
        assert bridge.financial_expense == Decimal("25")
        assert bridge.reported_net_income == Decimal("140")

    def test_non_operating_from_is_fields(self, wacc_inputs: WACCInputs) -> None:
        is_lines = [
            *_IS_LINES[:6],
            {
                "order": 6, "label": "Share of profits of associates",
                "value": "3",
            },
            *[
                {**li, "order": li["order"] + 1}
                for li in _IS_LINES[6:]
            ],
        ]
        raw = build_raw(is_lines=is_lines)
        ctx = make_context(raw, wacc_inputs)
        ctx.adjustments.append(_op_tax_rate_adj("25"))
        bridge = AnalysisDeriver().derive(ctx).nopat_bridge_by_period[0]
        assert bridge.non_operating_items == Decimal("3")

    def test_missing_a1_leaves_op_tax_zero(self, wacc_inputs: WACCInputs) -> None:
        raw = build_raw(is_lines=_IS_LINES)
        ctx = make_context(raw, wacc_inputs)
        bridge = AnalysisDeriver().derive(ctx).nopat_bridge_by_period[0]
        assert bridge.operating_taxes == Decimal("0")


class TestKeyRatios:
    def test_roic_roe_margins(self, wacc_inputs: WACCInputs) -> None:
        raw = build_raw(is_lines=_IS_LINES, bs_lines=_BS_LINES, cf_lines=_CF_LINES)
        ctx = make_context(raw, wacc_inputs)
        ctx.adjustments.append(_op_tax_rate_adj("25"))
        ratios = AnalysisDeriver().derive(ctx).ratios_by_period[0]
        # NOPAT 210 / IC 850 → ROIC ≈ 24.7%
        assert ratios.roic is not None
        assert abs(ratios.roic - Decimal("24.7058823529")) < Decimal("0.01")
        # NI 140 / Equity 650 → ROE ≈ 21.54%
        assert ratios.roe is not None
        assert abs(ratios.roe - Decimal("21.5384615385")) < Decimal("0.01")
        # Op margin 200/1000 = 20%
        assert ratios.operating_margin == Decimal("20")
        # EBITDA margin 280/1000 = 28%
        assert ratios.ebitda_margin == Decimal("28")
        # Net debt 400 - 200 = 200 / 280 ≈ 0.714
        assert ratios.net_debt_ebitda is not None
        assert abs(ratios.net_debt_ebitda - Decimal("0.714285714")) < Decimal("0.01")
        # CapEx 60 / 1000 = 6%
        assert ratios.capex_revenue == Decimal("6")

    def test_zero_revenue_yields_none_margins(
        self, wacc_inputs: WACCInputs
    ) -> None:
        raw = build_raw(
            is_lines=[
                {"order": 1, "label": "Revenue", "value": "0"},
                {
                    "order": 2, "label": "Profit for the year",
                    "value": "0", "is_subtotal": True,
                },
            ],
        )
        ctx = make_context(raw, wacc_inputs)
        ctx.adjustments.append(_op_tax_rate_adj("25"))
        ratios = AnalysisDeriver().derive(ctx).ratios_by_period[0]
        assert ratios.operating_margin is None
        assert ratios.ebitda_margin is None
