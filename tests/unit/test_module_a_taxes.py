"""Unit tests for extraction.module_a_taxes.ModuleATaxes (Phase 1.5.3)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from portfolio_thesis_engine.extraction.module_a_taxes import ModuleATaxes
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.wacc import WACCInputs

from .conftest import build_raw, make_context


def _clean_is_lines(
    *,
    revenue: str = "1000",
    pbt: str = "100",
    income_tax: str = "-20",
    net_income: str = "80",
) -> list[dict]:
    return [
        {"order": 1, "label": "Revenue", "value": revenue},
        {
            "order": 2, "label": "Profit before taxation",
            "value": pbt, "is_subtotal": True,
        },
        {"order": 3, "label": "Income tax", "value": income_tax},
        {
            "order": 4, "label": "Profit for the year",
            "value": net_income, "is_subtotal": True,
        },
    ]


def _tax_note(
    *,
    effective: str | None = "20.0",
    statutory: str | None = "16.5",
    recon_rows: list[list] | None = None,
) -> dict:
    rows: list[list] = []
    if statutory is not None:
        rows.append(["Tax at statutory rate", statutory])
    if effective is not None:
        rows.append(["Effective tax rate", effective])
    if recon_rows:
        rows.extend(recon_rows)
    return {
        "title": "Income tax expense",
        "tables": [
            {
                "table_label": "Rate reconciliation",
                "columns": ["Description", "%"],
                "rows": rows,
            }
        ],
    }


class TestModuleAHappyPath:
    @pytest.mark.asyncio
    async def test_non_op_item_removed_from_operating_rate(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw(
            is_lines=_clean_is_lines(),
            notes=[
                _tax_note(
                    recon_rows=[
                        ["Prior-year adjustments", "3.0"],
                        ["Non-deductible expenses", "0.5"],
                    ]
                )
            ],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleATaxes(MagicMock(), cost_tracker).apply(context)

        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        assert len(a1) == 1
        # Non-op item: "Prior-year adjustments" (keyword "prior year") = 3.0
        # Operating tax = |-20| - 3 = 17; pbt = 100 → rate ≈ 17%
        assert abs(a1[0].amount - Decimal("17.00")) < Decimal("0.1")

        a2 = [adj for adj in context.adjustments if adj.module == "A.2"]
        assert len(a2) == 1
        assert "Prior-year" in a2[0].description


class TestModuleAMateriality:
    @pytest.mark.asyncio
    async def test_immaterial_keeps_effective_rate(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        # Statutory tax at 25% of 1000 = 250; non-op of 2 is <1%
        raw = build_raw(
            is_lines=_clean_is_lines(pbt="1000", income_tax="-180"),
            notes=[
                _tax_note(
                    effective="18.0",
                    statutory="25.0",
                    recon_rows=[["Prior-year adjustments", "2.0"]],
                )
            ],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleATaxes(MagicMock(), cost_tracker).apply(context)
        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        assert len(a1) == 1
        assert a1[0].amount == Decimal("18.0")
        assert any("below 5%" in d for d in context.decision_log)


class TestModuleAFallbacks:
    @pytest.mark.asyncio
    async def test_no_taxes_note_falls_back_to_statutory(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw(is_lines=_clean_is_lines())
        context = make_context(raw, wacc_inputs)
        await ModuleATaxes(MagicMock(), cost_tracker).apply(context)
        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        assert a1[0].amount == Decimal("25.0")
        assert any("statutory fallback" in d for d in context.decision_log)

    @pytest.mark.asyncio
    async def test_missing_effective_rate_falls_back(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw(
            is_lines=_clean_is_lines(),
            notes=[_tax_note(effective=None)],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleATaxes(MagicMock(), cost_tracker).apply(context)
        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        assert a1[0].amount == Decimal("25.0")

    @pytest.mark.asyncio
    async def test_missing_income_tax_line_falls_back(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        # IS has no income-tax-like label
        raw = build_raw(
            is_lines=[
                {"order": 1, "label": "Revenue", "value": "1000"},
                {
                    "order": 2, "label": "Profit for the year",
                    "value": "80", "is_subtotal": True,
                },
            ],
            notes=[_tax_note()],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleATaxes(MagicMock(), cost_tracker).apply(context)
        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        assert a1[0].amount == Decimal("25.0")


class TestModuleALabelHeuristics:
    @pytest.mark.asyncio
    async def test_goodwill_keyword_treated_as_non_op(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw(
            is_lines=_clean_is_lines(),
            notes=[
                _tax_note(
                    recon_rows=[
                        ["Goodwill impairment non-deductible", "4.0"],
                    ]
                )
            ],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleATaxes(MagicMock(), cost_tracker).apply(context)
        a2 = [adj for adj in context.adjustments if adj.module == "A.2"]
        assert len(a2) == 1

    @pytest.mark.asyncio
    async def test_neutral_label_stays_operating(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw(
            is_lines=_clean_is_lines(),
            notes=[
                _tax_note(
                    recon_rows=[
                        ["Other miscellaneous items", "2.5"],
                    ]
                )
            ],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleATaxes(MagicMock(), cost_tracker).apply(context)
        a2 = [adj for adj in context.adjustments if adj.module == "A.2"]
        assert a2 == []


class TestModuleACashTaxes:
    @pytest.mark.asyncio
    async def test_cf_cash_tax_line_logs_a4(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw(
            is_lines=_clean_is_lines(),
            cf_lines=[
                {"order": 1, "label": "Profit before tax", "value": "100",
                 "section": "operating"},
                {"order": 2, "label": "Income taxes paid",
                 "value": "-18", "section": "operating"},
                {"order": 3, "label": "Net cash generated from operating activities",
                 "value": "82", "section": "operating", "is_subtotal": True},
            ],
            notes=[_tax_note()],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleATaxes(MagicMock(), cost_tracker).apply(context)
        assert any(
            "A.4" in d and "cash taxes" in d for d in context.decision_log
        )

    @pytest.mark.asyncio
    async def test_a5_always_logged_when_note_present(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw(
            is_lines=_clean_is_lines(),
            notes=[_tax_note()],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleATaxes(MagicMock(), cost_tracker).apply(context)
        assert any("A.5" in d for d in context.decision_log)
