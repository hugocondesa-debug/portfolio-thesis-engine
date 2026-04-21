"""Unit tests for extraction.module_b_provisions.ModuleBProvisions."""

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
from portfolio_thesis_engine.extraction.module_b_provisions import ModuleBProvisions
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


def _make_context(
    wacc: WACCInputs,
    sections: list[StructuredSection],
) -> ExtractionContext:
    return ExtractionContext(
        ticker="TST",
        fiscal_period_label="FY2024",
        primary_period=parse_fiscal_period("FY2024"),
        sections=sections,
        wacc_inputs=wacc,
    )


def _is_section(parsed: dict[str, Any] | None) -> StructuredSection:
    return StructuredSection(
        section_type="income_statement",
        title="Consolidated Income Statement",
        content="",
        parsed_data=parsed,
    )


# ======================================================================
# 1. Non-operating detection
# ======================================================================


class TestModuleBDetection:
    @pytest.mark.asyncio
    async def test_goodwill_impairment_detected(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "line_items": [
                {"label": "Revenue", "value_current": 1000, "category": "revenue"},
                {
                    "label": "Goodwill impairment charge",
                    "value_current": -50,
                    "category": "non_operating",
                },
                {"label": "Operating income", "value_current": 150, "category": "operating_income"},
            ],
        }
        context = _make_context(_wacc, [_is_section(parsed)])
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)

        adj = [a for a in context.adjustments if "goodwill_impairment" in a.module]
        assert len(adj) == 1
        assert adj[0].amount == Decimal("-50")
        assert "Goodwill impairment charge" in adj[0].description

    @pytest.mark.asyncio
    async def test_restructuring_detected_via_label(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        # category is generic but label says "restructuring" → detected
        parsed = {
            "line_items": [
                {
                    "label": "Restructuring charges",
                    "value_current": -30,
                    "category": "other",
                },
            ],
        }
        context = _make_context(_wacc, [_is_section(parsed)])
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)

        adj = [a for a in context.adjustments if "restructuring" in a.module]
        assert len(adj) == 1

    @pytest.mark.asyncio
    async def test_disposal_gain_detected(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "line_items": [
                {
                    "label": "Gain on disposal of subsidiary",
                    "value_current": 25,
                    "category": "non_operating",
                },
            ],
        }
        context = _make_context(_wacc, [_is_section(parsed)])
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)

        adj = [a for a in context.adjustments if "disposal_gain_loss" in a.module]
        assert len(adj) == 1
        assert adj[0].amount == Decimal("25")

    @pytest.mark.asyncio
    async def test_non_operating_without_known_keyword_uses_other(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "line_items": [
                {
                    "label": "Other unusual items",
                    "value_current": -10,
                    "category": "non_operating",
                },
            ],
        }
        context = _make_context(_wacc, [_is_section(parsed)])
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)

        adj = [a for a in context.adjustments if "non_operating_other" in a.module]
        assert len(adj) == 1

    @pytest.mark.asyncio
    async def test_multiple_items_all_captured(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "line_items": [
                {"label": "Revenue", "value_current": 1000, "category": "revenue"},
                {"label": "Restructuring", "value_current": -20, "category": "non_operating"},
                {"label": "Goodwill impairment", "value_current": -40, "category": "non_operating"},
                {"label": "Gain on sale of asset", "value_current": 15, "category": "non_operating"},
            ],
        }
        context = _make_context(_wacc, [_is_section(parsed)])
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)

        # Three non-op items → three B.2 adjustments
        b_adj = [a for a in context.adjustments if a.module.startswith("B.2")]
        assert len(b_adj) == 3


# ======================================================================
# 2. Specificity: goodwill impairment beats generic impairment
# ======================================================================


class TestModuleBSpecificity:
    @pytest.mark.asyncio
    async def test_goodwill_impairment_wins_over_generic_impairment(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "line_items": [
                {
                    "label": "Goodwill impairment of acquired business",
                    "value_current": -100,
                    "category": "non_operating",
                },
            ],
        }
        context = _make_context(_wacc, [_is_section(parsed)])
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)
        assert any("goodwill_impairment" in a.module for a in context.adjustments)


# ======================================================================
# 3. Non-detection: pure operating items left alone
# ======================================================================


class TestModuleBNonDetection:
    @pytest.mark.asyncio
    async def test_no_non_operating_items_no_adjustments(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "line_items": [
                {"label": "Revenue", "value_current": 1000, "category": "revenue"},
                {"label": "COGS", "value_current": -600, "category": "cost_of_sales"},
                {"label": "Operating income", "value_current": 200, "category": "operating_income"},
            ],
        }
        context = _make_context(_wacc, [_is_section(parsed)])
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)

        assert context.adjustments == []
        assert any("no obvious non-operating" in d for d in context.decision_log)


# ======================================================================
# 4. B.0 applicability — empty/missing IS
# ======================================================================


class TestModuleBApplicability:
    @pytest.mark.asyncio
    async def test_no_is_section_skips(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        context = _make_context(_wacc, sections=[])
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)

        assert context.adjustments == []
        assert any("B.0" in d for d in context.decision_log)

    @pytest.mark.asyncio
    async def test_empty_line_items_skips(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        context = _make_context(_wacc, [_is_section({"line_items": []})])
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)

        assert context.adjustments == []
        assert any("B.0" in d for d in context.decision_log)

    @pytest.mark.asyncio
    async def test_parsed_data_none_skips(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        context = _make_context(_wacc, [_is_section(None)])
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)

        assert context.adjustments == []


# ======================================================================
# 5. Robustness
# ======================================================================


class TestModuleBRobustness:
    @pytest.mark.asyncio
    async def test_malformed_amount_ignored(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "line_items": [
                {"label": "Valid restructuring", "value_current": -20, "category": "non_operating"},
                {"label": "Bogus", "value_current": "not-a-number", "category": "non_operating"},
                {"label": "Null value", "value_current": None, "category": "non_operating"},
            ],
        }
        context = _make_context(_wacc, [_is_section(parsed)])
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)

        # Only the valid one makes it in
        b_adj = [a for a in context.adjustments if a.module.startswith("B.2")]
        assert len(b_adj) == 1

    @pytest.mark.asyncio
    async def test_empty_label_skipped(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "line_items": [
                {"label": "", "value_current": -10, "category": "non_operating"},
            ],
        }
        context = _make_context(_wacc, [_is_section(parsed)])
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)

        assert context.adjustments == []
