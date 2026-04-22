"""Unit tests for extraction.coordinator.ExtractionCoordinator (Phase 1.5)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from portfolio_thesis_engine.extraction.base import (
    ExtractionContext,
    ExtractionModule,
    parse_fiscal_period,
)
from portfolio_thesis_engine.extraction.coordinator import ExtractionCoordinator
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
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
from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.shared.exceptions import CostLimitExceededError

# ======================================================================
# Fixtures
# ======================================================================


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


def _build_raw(ticker: str = "TST", fp: str = "FY2024") -> RawExtraction:
    payload: dict[str, Any] = {
        "metadata": {
            "ticker": ticker,
            "company_name": "Test Co",
            "document_type": DocumentType.ANNUAL_REPORT,
            "extraction_type": ExtractionType.NUMERIC,
            "reporting_currency": Currency.USD,
            "unit_scale": "units",
            "fiscal_year": 2024,
            "extraction_date": "2025-01-01",
            "fiscal_periods": [
                {"period": fp, "end_date": "2024-12-31", "is_primary": True},
            ],
        },
        "income_statement": {
            fp: {
                "revenue": Decimal("1000"),
                "operating_income": Decimal("150"),
                "income_before_tax": Decimal("200"),
                "income_tax": Decimal("-40"),
                "net_income": Decimal("160"),
            },
        },
        "balance_sheet": {
            fp: {"total_assets": Decimal("500"), "total_equity": Decimal("300")},
        },
        "notes": {
            "taxes": {
                "effective_tax_rate_percent": Decimal("20.0"),
                "statutory_rate_percent": Decimal("25.0"),
                "reconciling_items": [
                    # Material non-op (>5% of statutory_tax 50) → triggers A.2
                    {
                        "description": "Prior-year true-up",
                        "amount": Decimal("5.0"),
                        "classification": "one_time",
                    },
                ],
            },
            "goodwill": {
                "opening": Decimal("100"),
                "impairment": Decimal("-50"),
                "closing": Decimal("50"),
            },
        },
    }
    return RawExtraction.model_validate(payload)


# ======================================================================
# 1. Profile loading
# ======================================================================


class TestLoadModulesForProfile:
    def test_p1_loads_modules_a_b_c(self, _cost_tracker: CostTracker) -> None:
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=_cost_tracker,
        )
        ids = [m.module_id for m in coord.modules]
        assert ids == ["A", "B", "C"]

    def test_unsupported_profile_raises(self, _cost_tracker: CostTracker) -> None:
        with pytest.raises(NotImplementedError, match="Phase 1"):
            ExtractionCoordinator(
                profile=Profile.P2_BANKS,
                llm=MagicMock(),
                cost_tracker=_cost_tracker,
            )

    def test_explicit_modules_override_profile(
        self, _cost_tracker: CostTracker
    ) -> None:
        sentinel = MagicMock(spec=ExtractionModule)
        sentinel.module_id = "X"
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=_cost_tracker,
            modules=[sentinel],
        )
        assert coord.modules == [sentinel]


# ======================================================================
# 2. Module ordering + context propagation
# ======================================================================


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
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        record: list[str] = []
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=_cost_tracker,
            modules=[
                _RecordingModule("first", record),
                _RecordingModule("second", record),
                _RecordingModule("third", record),
            ],
        )
        result = await coord.extract(_build_raw(), _wacc)
        assert record == ["first", "second", "third"]
        assert result.modules_run == ["first", "second", "third"]

    @pytest.mark.asyncio
    async def test_context_propagates_between_modules(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        record: list[str] = []
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=_cost_tracker,
            modules=[
                _RecordingModule("A", record),
                _RecordingModule("B", record),
            ],
        )
        result = await coord.extract(_build_raw(), _wacc)
        assert "B: saw 1 existing adj" in result.decision_log


# ======================================================================
# 3. End-to-end with real Modules A + B + C
# ======================================================================


class TestEndToEndP1:
    @pytest.mark.asyncio
    async def test_p1_coordinator_produces_adjustments_from_raw(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=_cost_tracker,
        )
        result = await coord.extract(_build_raw(), _wacc)

        assert result.ticker == "TST"
        assert result.fiscal_period_label == "FY2024"
        assert result.primary_period.year == 2024

        a_mods = [a for a in result.adjustments if a.module.startswith("A.")]
        assert any(a.module == "A.1" for a in a_mods)
        assert any(a.module == "A.2" for a in a_mods)

        # Module B produced B.2.goodwill_impairment from notes.goodwill
        b_mods = [a for a in result.adjustments if a.module.startswith("B.2")]
        assert any("goodwill_impairment" in a.module for a in b_mods)

        assert result.modules_run == ["A", "B", "C"]


# ======================================================================
# 4. Cost-cap enforcement
# ======================================================================


class TestCostCapEnforcement:
    @pytest.mark.asyncio
    async def test_cap_hit_before_first_module_raises(
        self,
        _wacc: WACCInputs,
        _cost_tracker: CostTracker,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "llm_max_cost_per_company_usd", 1.0)
        _cost_tracker.record(
            operation="ingestion_preload",
            model="claude-sonnet-4-6",
            input_tokens=0,
            output_tokens=0,
            cost_usd=Decimal("5"),
            ticker="TST",
        )
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=_cost_tracker,
        )
        with pytest.raises(CostLimitExceededError, match="extraction_module_A"):
            await coord.extract(_build_raw(), _wacc)

    @pytest.mark.asyncio
    async def test_cap_hit_between_modules_raises(
        self,
        _wacc: WACCInputs,
        _cost_tracker: CostTracker,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "llm_max_cost_per_company_usd", 5.0)

        class _PumpCost(ExtractionModule):
            module_id = "P"

            def __init__(self, tracker: CostTracker) -> None:
                self._tracker = tracker

            async def apply(self, context: ExtractionContext) -> ExtractionContext:
                self._tracker.record(
                    operation="bloat",
                    model="claude-sonnet-4-6",
                    input_tokens=0,
                    output_tokens=0,
                    cost_usd=Decimal("10"),
                    ticker=context.ticker,
                )
                return context

        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=_cost_tracker,
            modules=[
                _PumpCost(_cost_tracker),
                _RecordingModule("B", []),
            ],
        )
        with pytest.raises(CostLimitExceededError, match="extraction_module_B"):
            await coord.extract(_build_raw(), _wacc)


# ======================================================================
# 5. Parse fiscal period helper
# ======================================================================


class TestParseFiscalPeriod:
    def test_fy_label(self) -> None:
        fp = parse_fiscal_period("FY2024")
        assert fp.year == 2024
        assert fp.quarter is None
        assert fp.label == "FY2024"

    def test_quarter_label(self) -> None:
        fp = parse_fiscal_period("Q3 2024")
        assert fp.year == 2024
        assert fp.quarter == 3

    def test_unknown_label_falls_back_to_sentinel(self) -> None:
        fp = parse_fiscal_period("gibberish")
        assert fp.year == 1990
        assert fp.label == "gibberish"

    def test_empty_label_does_not_crash(self) -> None:
        fp = parse_fiscal_period("")
        assert fp.label == "unknown"
