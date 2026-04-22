"""Unit tests for extraction.module_b_provisions.ModuleBProvisions (Phase 1.5.3)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from portfolio_thesis_engine.extraction.module_b_provisions import ModuleBProvisions
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.wacc import WACCInputs

from .conftest import build_raw, make_context


class TestModuleBGoodwill:
    @pytest.mark.asyncio
    async def test_goodwill_impairment_from_movement_table(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw(
            notes=[
                {
                    "title": "Goodwill",
                    "tables": [
                        {
                            "table_label": "Movement",
                            "columns": ["Description", "HKD millions"],
                            "rows": [
                                ["Opening", "100"],
                                ["Impairment charge", "-20"],
                                ["Closing", "80"],
                            ],
                        }
                    ],
                }
            ],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleBProvisions(MagicMock(), cost_tracker).apply(context)
        adj = [a for a in context.adjustments if a.module == "B.2.goodwill_impairment"]
        assert len(adj) == 1
        assert adj[0].amount == Decimal("-20")

    @pytest.mark.asyncio
    async def test_zero_impairment_no_adjustment(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw(
            notes=[
                {
                    "title": "Goodwill",
                    "tables": [
                        {
                            "rows": [
                                ["Opening", "100"],
                                ["Impairment charge", "0"],
                                ["Closing", "100"],
                            ],
                        }
                    ],
                }
            ],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleBProvisions(MagicMock(), cost_tracker).apply(context)
        assert [
            a for a in context.adjustments if a.module == "B.2.goodwill_impairment"
        ] == []


class TestModuleBProvisionsNote:
    @pytest.mark.asyncio
    async def test_restructuring_row_surfaces(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw(
            notes=[
                {
                    "title": "Provisions",
                    "tables": [
                        {
                            "rows": [
                                ["Warranty provisions", "8.0"],
                                ["Site closure restructuring", "-30.0"],
                            ],
                        }
                    ],
                }
            ],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleBProvisions(MagicMock(), cost_tracker).apply(context)
        adj = [a for a in context.adjustments if a.module == "B.2.restructuring"]
        assert len(adj) == 1

    @pytest.mark.asyncio
    async def test_litigation_row_surfaces(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw(
            notes=[
                {
                    "title": "Provisions",
                    "tables": [
                        {
                            "rows": [
                                ["Legal settlement provision", "-12.0"],
                            ],
                        }
                    ],
                }
            ],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleBProvisions(MagicMock(), cost_tracker).apply(context)
        adj = [a for a in context.adjustments if a.module == "B.2.litigation"]
        assert len(adj) == 1

    @pytest.mark.asyncio
    async def test_operating_provisions_ignored(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw(
            notes=[
                {
                    "title": "Provisions",
                    "tables": [
                        {"rows": [["Warranty provisions", "8.0"]]},
                    ],
                }
            ],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleBProvisions(MagicMock(), cost_tracker).apply(context)
        assert [a for a in context.adjustments if a.module.startswith("B.2")] == []


class TestModuleBISLabels:
    @pytest.mark.asyncio
    async def test_non_operating_income_is_line_surfaces(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw(
            is_lines=[
                {"order": 1, "label": "Revenue", "value": "1000"},
                {"order": 2, "label": "Non-operating income", "value": "12"},
                {
                    "order": 3, "label": "Profit for the year",
                    "value": "100", "is_subtotal": True,
                },
            ],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleBProvisions(MagicMock(), cost_tracker).apply(context)
        adj = [
            a for a in context.adjustments
            if a.module == "B.2.non_operating_other"
        ]
        assert len(adj) == 1
        assert adj[0].amount == Decimal("12")

    @pytest.mark.asyncio
    async def test_associates_is_line_surfaces(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw(
            is_lines=[
                {"order": 1, "label": "Revenue", "value": "1000"},
                {"order": 2, "label": "Share of profits of associates",
                 "value": "5"},
                {
                    "order": 3, "label": "Profit for the year",
                    "value": "100", "is_subtotal": True,
                },
            ],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleBProvisions(MagicMock(), cost_tracker).apply(context)
        adj = [a for a in context.adjustments if a.module == "B.2.associates"]
        assert len(adj) == 1

    @pytest.mark.asyncio
    async def test_discontinued_is_line_surfaces(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw(
            is_lines=[
                {"order": 1, "label": "Revenue", "value": "1000"},
                {"order": 2, "label": "Net income from discontinued operations",
                 "value": "-8"},
                {
                    "order": 3, "label": "Profit for the year",
                    "value": "100", "is_subtotal": True,
                },
            ],
            notes=[
                {
                    "title": "Discontinued operations",
                    "tables": [{"rows": [["Revenue", "50.0"]]}],
                }
            ],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleBProvisions(MagicMock(), cost_tracker).apply(context)
        adj = [a for a in context.adjustments if a.module == "B.2.discontinued"]
        assert len(adj) == 1
        assert any(
            "discontinued-ops note" in d for d in context.decision_log
        )


class TestModuleBApplicability:
    @pytest.mark.asyncio
    async def test_no_non_op_sources_logs_b1_noop(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw()
        context = make_context(raw, wacc_inputs)
        await ModuleBProvisions(MagicMock(), cost_tracker).apply(context)
        assert context.adjustments == []
        assert any(
            "B.1" in d and "no non-operating" in d for d in context.decision_log
        )


class TestModuleBCombined:
    @pytest.mark.asyncio
    async def test_goodwill_and_is_non_op_both_surface(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw(
            is_lines=[
                {"order": 1, "label": "Revenue", "value": "1000"},
                {"order": 2, "label": "Non-operating income", "value": "8"},
                {
                    "order": 3, "label": "Profit for the year",
                    "value": "100", "is_subtotal": True,
                },
            ],
            notes=[
                {
                    "title": "Goodwill",
                    "tables": [
                        {
                            "rows": [
                                ["Impairment charge", "-30"],
                            ],
                        }
                    ],
                },
                {
                    "title": "Provisions",
                    "tables": [
                        {"rows": [["Restructuring charge", "-15.0"]]},
                    ],
                },
            ],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleBProvisions(MagicMock(), cost_tracker).apply(context)
        b2 = [a for a in context.adjustments if a.module.startswith("B.2")]
        modules = {a.module for a in b2}
        assert "B.2.goodwill_impairment" in modules
        assert "B.2.restructuring" in modules
        assert "B.2.non_operating_other" in modules
