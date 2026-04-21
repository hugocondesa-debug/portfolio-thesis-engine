"""Unit tests for extraction.module_c_leases.ModuleCLeases."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from portfolio_thesis_engine.extraction.base import (
    ExtractionContext,
    parse_fiscal_period,
)
from portfolio_thesis_engine.extraction.module_c_leases import ModuleCLeases
from portfolio_thesis_engine.extraction.raw_extraction_adapter import StructuredSection
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.common import Profile
from portfolio_thesis_engine.schemas.wacc import (
    CapitalStructure,
    CostOfCapitalInputs,
    ScenarioDriversManual,
    WACCInputs,
)


@pytest.fixture
def _cost_tracker(tmp_path: Path) -> CostTracker:
    return CostTracker(log_path=tmp_path / "costs.jsonl")


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


def _make_context(wacc: WACCInputs, sections: list[StructuredSection]) -> ExtractionContext:
    return ExtractionContext(
        ticker="TST",
        fiscal_period_label="FY2024",
        primary_period=parse_fiscal_period("FY2024"),
        sections=sections,
        wacc_inputs=wacc,
    )


def _leases(parsed: dict[str, Any] | None) -> StructuredSection:
    return StructuredSection(
        section_type="notes_leases",
        title="Note 8 — Leases",
        content="",
        parsed_data=parsed,
    )


class TestModuleCDisclosed:
    @pytest.mark.asyncio
    async def test_disclosed_additions_field_used_directly(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "rou_assets_by_category": [
                {"category": "Medical facilities", "value_current": 500},
                {"category": "Vehicles", "value_current": 50},
            ],
            "lease_liability_movement": {
                "opening_balance": 400,
                "additions": 120,
                "depreciation_of_rou": 80,
                "interest_expense": 20,
                "principal_payments": 90,
                "closing_balance": 430,
            },
        }
        context = _make_context(_wacc, [_leases(parsed)])
        module = ModuleCLeases(MagicMock(), _cost_tracker)

        await module.apply(context)

        c3 = [a for a in context.adjustments if a.module == "C.3"]
        assert len(c3) == 1
        assert c3[0].amount == Decimal("120")
        assert "Lease additions for FCFF" in c3[0].description
        # C.1 / C.2 decision-log entries
        decisions = "\n".join(context.decision_log)
        assert "C.1" in decisions
        assert "C.2" in decisions
        assert "C.3" in decisions


class TestModuleCDerived:
    @pytest.mark.asyncio
    async def test_additions_derived_from_movement(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        # No additions field → back out from closing - opening + principal_payments
        # = 430 - 400 + 90 = 120
        parsed = {
            "lease_liability_movement": {
                "opening_balance": 400,
                "closing_balance": 430,
                "principal_payments": 90,
            },
        }
        context = _make_context(_wacc, [_leases(parsed)])
        module = ModuleCLeases(MagicMock(), _cost_tracker)

        await module.apply(context)

        c3 = [a for a in context.adjustments if a.module == "C.3"]
        assert len(c3) == 1
        assert c3[0].amount == Decimal("120")
        assert any("derived" in e for e in context.estimates_log)


class TestModuleCApplicability:
    @pytest.mark.asyncio
    async def test_no_notes_leases_skips(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        context = _make_context(_wacc, [])
        module = ModuleCLeases(MagicMock(), _cost_tracker)

        await module.apply(context)

        assert context.adjustments == []
        assert any("C.0" in d for d in context.decision_log)

    @pytest.mark.asyncio
    async def test_parsed_data_none_skips(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        context = _make_context(_wacc, [_leases(None)])
        module = ModuleCLeases(MagicMock(), _cost_tracker)

        await module.apply(context)
        assert context.adjustments == []

    @pytest.mark.asyncio
    async def test_missing_movement_structure_skips_additions(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "rou_assets_by_category": [
                {"category": "Fleet", "value_current": 100},
            ],
            # No lease_liability_movement
        }
        context = _make_context(_wacc, [_leases(parsed)])
        module = ModuleCLeases(MagicMock(), _cost_tracker)

        await module.apply(context)

        # No C.3 adjustment (additions undefinable) but C.1 log still fires
        assert [a for a in context.adjustments if a.module == "C.3"] == []
        assert any("C.1" in d for d in context.decision_log)
        assert any("could not be derived" in e for e in context.estimates_log)


class TestModuleCExtras:
    @pytest.mark.asyncio
    async def test_interest_and_depreciation_logged_when_present(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "lease_liability_movement": {
                "opening_balance": 100,
                "closing_balance": 120,
                "additions": 30,
                "interest_expense": 5,
                "depreciation_of_rou": 25,
                "principal_payments": 10,
            },
        }
        context = _make_context(_wacc, [_leases(parsed)])
        module = ModuleCLeases(MagicMock(), _cost_tracker)
        await module.apply(context)

        decisions = "\n".join(context.decision_log)
        assert "interest on lease liabilities" in decisions
        assert "ROU depreciation" in decisions
