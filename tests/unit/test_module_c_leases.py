"""Unit tests for extraction.module_c_leases.ModuleCLeases (Phase 1.5.3)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from portfolio_thesis_engine.extraction.module_c_leases import ModuleCLeases
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.wacc import WACCInputs

from .conftest import build_raw, make_context


def _leases_note(
    *,
    rou_rows: list[list] | None = None,
    liab_rows: list[list] | None = None,
) -> dict:
    tables: list[dict] = []
    if rou_rows:
        tables.append(
            {
                "table_label": "Right-of-use assets — movement",
                "columns": ["Description", "HKD millions"],
                "rows": rou_rows,
            }
        )
    if liab_rows:
        tables.append(
            {
                "table_label": "Lease liabilities — movement",
                "columns": ["Description", "HKD millions"],
                "rows": liab_rows,
            }
        )
    return {"title": "Leases", "tables": tables}


class TestModuleCDisclosed:
    @pytest.mark.asyncio
    async def test_additions_from_rou_table(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw(
            notes=[
                _leases_note(
                    rou_rows=[
                        ["Opening balance", "400"],
                        ["Additions", "120"],
                        ["Depreciation charge for the year", "-80"],
                        ["Closing balance at 31 December", "440"],
                    ],
                    liab_rows=[
                        ["Opening balance at 1 January", "400"],
                        ["New leases recognised", "120"],
                        ["Interest accretion on lease liabilities", "20"],
                        ["Principal payment of lease liabilities", "-90"],
                        ["Closing balance at 31 December", "450"],
                    ],
                )
            ],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleCLeases(MagicMock(), cost_tracker).apply(context)

        c3 = [a for a in context.adjustments if a.module == "C.3"]
        assert len(c3) == 1
        assert c3[0].amount == Decimal("120")
        decisions = "\n".join(context.decision_log)
        assert "C.1" in decisions
        assert "C.2" in decisions


class TestModuleCDerived:
    @pytest.mark.asyncio
    async def test_additions_derived_from_liability_movement(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        # closing - opening + principal_payments = 430 - 400 + 90 = 120
        raw = build_raw(
            notes=[
                _leases_note(
                    liab_rows=[
                        ["Opening balance at 1 January", "400"],
                        ["Principal payment of lease liabilities", "-90"],
                        ["Closing balance at 31 December", "430"],
                    ],
                )
            ],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleCLeases(MagicMock(), cost_tracker).apply(context)

        c3 = [a for a in context.adjustments if a.module == "C.3"]
        assert len(c3) == 1
        assert c3[0].amount == Decimal("120")
        assert any("derived" in e for e in context.estimates_log)


class TestModuleCApplicability:
    @pytest.mark.asyncio
    async def test_no_leases_note_skips(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw()
        context = make_context(raw, wacc_inputs)
        await ModuleCLeases(MagicMock(), cost_tracker).apply(context)
        assert context.adjustments == []
        assert any("C.0" in d for d in context.decision_log)

    @pytest.mark.asyncio
    async def test_leases_note_without_movement_skips_c3(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw(
            notes=[
                {
                    "title": "Leases",
                    "tables": [],
                    "narrative_summary": "No material IFRS 16 activity.",
                }
            ],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleCLeases(MagicMock(), cost_tracker).apply(context)
        assert [a for a in context.adjustments if a.module == "C.3"] == []
        assert any("C.1" in d for d in context.decision_log)


class TestModuleCExtras:
    @pytest.mark.asyncio
    async def test_interest_and_depreciation_logged(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        raw = build_raw(
            notes=[
                _leases_note(
                    rou_rows=[
                        ["Depreciation charge for the year", "25"],
                        ["Additions", "30"],
                    ],
                    liab_rows=[
                        ["Opening balance at 1 January", "100"],
                        ["Interest expense on lease liabilities", "5"],
                        ["Principal payment of lease liabilities", "-10"],
                        ["Closing balance at 31 December", "120"],
                    ],
                )
            ],
        )
        context = make_context(raw, wacc_inputs)
        await ModuleCLeases(MagicMock(), cost_tracker).apply(context)
        decisions = "\n".join(context.decision_log)
        assert "interest on lease liabilities" in decisions
        assert "ROU depreciation" in decisions
