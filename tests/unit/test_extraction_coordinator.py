"""Unit tests for extraction.coordinator.ExtractionCoordinator (Phase 1.5.3)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from portfolio_thesis_engine.extraction.base import (
    ExtractionContext,
    ExtractionModule,
    parse_fiscal_period,
)
from portfolio_thesis_engine.extraction.coordinator import ExtractionCoordinator
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.common import Profile
from portfolio_thesis_engine.schemas.company import ModuleAdjustment
from portfolio_thesis_engine.schemas.wacc import WACCInputs
from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.shared.exceptions import CostLimitExceededError

from .conftest import build_raw


def _p1_raw():
    """Raw with a tax note + goodwill note so Modules A + B produce
    real adjustments."""
    return build_raw(
        is_lines=[
            {"order": 1, "label": "Revenue", "value": "1000"},
            {"order": 2, "label": "Cost of sales", "value": "-600"},
            {
                "order": 3, "label": "Gross profit",
                "value": "400", "is_subtotal": True,
            },
            {"order": 4, "label": "Operating expenses", "value": "-150"},
            {
                "order": 5, "label": "Operating profit",
                "value": "250", "is_subtotal": True,
            },
            {
                "order": 6, "label": "Profit before taxation",
                "value": "200", "is_subtotal": True,
            },
            {"order": 7, "label": "Income tax", "value": "-40"},
            {
                "order": 8, "label": "Profit for the year",
                "value": "160", "is_subtotal": True,
            },
        ],
        bs_lines=[
            {
                "order": 1, "label": "Total assets",
                "value": "500", "section": "total_assets",
                "is_subtotal": True,
            },
        ],
        notes=[
            {
                "title": "Income tax expense",
                "tables": [
                    {
                        "table_label": "Rate reconciliation",
                        "rows": [
                            ["Tax at statutory rate", "25.0"],
                            ["Effective tax rate", "20.0"],
                            # Non-op keyword → B.2 bucket via A.2
                            ["Prior-year true-up", "5.0"],
                        ],
                    }
                ],
            },
            {
                "title": "Goodwill",
                "tables": [
                    {
                        "table_label": "Movement",
                        "rows": [
                            ["Opening", "100"],
                            ["Impairment charge", "-50"],
                            ["Closing", "50"],
                        ],
                    }
                ],
            },
        ],
    )


class TestProfileLoad:
    def test_p1_loads_modules_a_b_c(
        self, cost_tracker: CostTracker
    ) -> None:
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=cost_tracker,
        )
        assert [m.module_id for m in coord.modules] == ["A", "B", "C"]

    def test_unsupported_profile_raises(self, cost_tracker: CostTracker) -> None:
        with pytest.raises(NotImplementedError, match="Phase 1"):
            ExtractionCoordinator(
                profile=Profile.P2_BANKS,
                llm=MagicMock(),
                cost_tracker=cost_tracker,
            )

    def test_explicit_modules_override_profile(
        self, cost_tracker: CostTracker
    ) -> None:
        sentinel = MagicMock(spec=ExtractionModule)
        sentinel.module_id = "X"
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=cost_tracker,
            modules=[sentinel],
        )
        assert coord.modules == [sentinel]


class _RecordingModule(ExtractionModule):
    def __init__(self, module_id: str, record: list[str]) -> None:
        self.module_id = module_id
        self._record = record

    async def apply(self, context: ExtractionContext) -> ExtractionContext:
        self._record.append(self.module_id)
        context.decision_log.append(
            f"{self.module_id}: saw {len(context.adjustments)} existing adj"
        )
        context.adjustments.append(
            ModuleAdjustment(
                module=self.module_id,
                description=f"touched by {self.module_id}",
                amount=Decimal("1"),
                affected_periods=[context.primary_period],
                rationale="test",
            )
        )
        return context


class TestOrdering:
    @pytest.mark.asyncio
    async def test_modules_run_in_declared_order(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        record: list[str] = []
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=cost_tracker,
            modules=[
                _RecordingModule("first", record),
                _RecordingModule("second", record),
            ],
        )
        result = await coord.extract(_p1_raw(), wacc_inputs)
        assert record == ["first", "second"]
        assert result.modules_run == ["first", "second"]


class TestEndToEndP1:
    @pytest.mark.asyncio
    async def test_p1_coordinator_produces_adjustments(
        self, wacc_inputs: WACCInputs, cost_tracker: CostTracker
    ) -> None:
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=cost_tracker,
        )
        result = await coord.extract(_p1_raw(), wacc_inputs)
        a_mods = [a for a in result.adjustments if a.module.startswith("A.")]
        assert any(a.module == "A.1" for a in a_mods)
        b_mods = [a for a in result.adjustments if a.module.startswith("B.2")]
        assert any("goodwill_impairment" in a.module for a in b_mods)
        assert result.modules_run == ["A", "B", "C"]


class TestCostCap:
    @pytest.mark.asyncio
    async def test_cap_hit_before_first_module_raises(
        self,
        wacc_inputs: WACCInputs,
        cost_tracker: CostTracker,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "llm_max_cost_per_company_usd", 1.0)
        cost_tracker.record(
            operation="bloat",
            model="claude-sonnet-4-6",
            input_tokens=0,
            output_tokens=0,
            cost_usd=Decimal("5"),
            ticker="TST",
        )
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=cost_tracker,
        )
        with pytest.raises(CostLimitExceededError, match="extraction_module_A"):
            await coord.extract(_p1_raw(), wacc_inputs)


class TestParseFiscalPeriod:
    def test_fy_label(self) -> None:
        fp = parse_fiscal_period("FY2024")
        assert fp.year == 2024
        assert fp.label == "FY2024"

    def test_quarter_label(self) -> None:
        fp = parse_fiscal_period("Q3 2024")
        assert fp.year == 2024
        assert fp.quarter == 3

    def test_unknown_falls_back_to_sentinel(self) -> None:
        fp = parse_fiscal_period("gibberish")
        assert fp.year == 1990

    def test_empty_label_does_not_crash(self) -> None:
        fp = parse_fiscal_period("")
        assert fp.label == "unknown"
