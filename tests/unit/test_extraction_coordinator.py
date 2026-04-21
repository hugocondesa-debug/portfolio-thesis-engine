"""Unit tests for extraction.coordinator.ExtractionCoordinator."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
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
from portfolio_thesis_engine.schemas.wacc import (
    CapitalStructure,
    CostOfCapitalInputs,
    ScenarioDriversManual,
    WACCInputs,
)
from portfolio_thesis_engine.section_extractor.base import (
    ExtractionResult as SectionExtractionResult,
)
from portfolio_thesis_engine.section_extractor.base import StructuredSection
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


def _section_result(ticker: str = "TST", fp: str = "FY2024") -> SectionExtractionResult:
    is_section = StructuredSection(
        section_type="income_statement",
        title="IS",
        content="",
        parsed_data={
            "line_items": [
                {"label": "Revenue", "value_current": 1000, "category": "revenue"},
                {
                    "label": "Goodwill impairment",
                    "value_current": -50,
                    "category": "non_operating",
                },
            ],
        },
    )
    tax_section = StructuredSection(
        section_type="notes_taxes",
        title="Tax recon",
        content="",
        parsed_data={
            "effective_rate_pct": 20.0,
            "profit_before_tax": 200.0,
            "statutory_tax": 40.0,
            "reported_tax_expense": 40.0,
            "reconciling_items": [
                # Material non-op (5%+) → triggers A.2 branch
                {"label": "Prior-year true-up", "amount": 5.0, "category": "prior_year_adjustment"},
            ],
        },
    )
    return SectionExtractionResult(
        doc_id="doc",
        ticker=ticker,
        fiscal_period=fp,
        sections=[is_section, tax_section],
    )


# ======================================================================
# 1. Profile loading
# ======================================================================


class TestLoadModulesForProfile:
    def test_p1_loads_modules_a_and_b(self, _cost_tracker: CostTracker) -> None:
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=_cost_tracker,
        )
        ids = [m.module_id for m in coord.modules]
        assert ids == ["A", "B"]

    def test_unsupported_profile_raises(self, _cost_tracker: CostTracker) -> None:
        with pytest.raises(NotImplementedError, match="Phase 1"):
            ExtractionCoordinator(
                profile=Profile.P2_BANKS,
                llm=MagicMock(),
                cost_tracker=_cost_tracker,
            )

    def test_explicit_modules_override_profile(self, _cost_tracker: CostTracker) -> None:
        """Passing modules= skips profile loading — used by Sprint 7 and tests."""
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
    """Module that records the order of its call and what it sees."""

    def __init__(self, module_id: str, record: list[str]) -> None:
        self.module_id = module_id
        self._record = record

    async def apply(self, context: ExtractionContext) -> ExtractionContext:
        self._record.append(self.module_id)
        context.decision_log.append(f"{self.module_id}: saw {len(context.adjustments)} existing adj")
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
        result = await coord.extract(_section_result(), _wacc)
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
        result = await coord.extract(_section_result(), _wacc)
        # Second module should have seen the first one's adjustment
        assert "B: saw 1 existing adj" in result.decision_log


# ======================================================================
# 3. End-to-end with real Modules A + B
# ======================================================================


class TestEndToEndP1:
    @pytest.mark.asyncio
    async def test_p1_coordinator_produces_adjustments_from_sections(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=_cost_tracker,
        )
        result = await coord.extract(_section_result(), _wacc)

        assert result.ticker == "TST"
        assert result.fiscal_period_label == "FY2024"
        assert result.primary_period.year == 2024

        # Module A produced A.1 + A.2 adjustments
        a_mods = [a for a in result.adjustments if a.module.startswith("A.")]
        assert any(a.module == "A.1" for a in a_mods)
        assert any(a.module == "A.2" for a in a_mods)

        # Module B produced B.2.goodwill_impairment
        b_mods = [a for a in result.adjustments if a.module.startswith("B.2")]
        assert any("goodwill_impairment" in a.module for a in b_mods)

        assert result.modules_run == ["A", "B"]


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
        # Pre-populate log with ticker cost beyond the cap.
        monkeypatch.setattr(settings, "llm_max_cost_per_company_usd", 1.0)
        _cost_tracker.record(
            operation="section_parse_is",
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
            await coord.extract(_section_result(), _wacc)

    @pytest.mark.asyncio
    async def test_cap_hit_between_modules_raises(
        self,
        _wacc: WACCInputs,
        _cost_tracker: CostTracker,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Set cap high initially, then trip it mid-run via a module.
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
                _PumpCost(_cost_tracker),  # First module pumps cost past cap
                _RecordingModule("B", []),  # Never runs
            ],
        )
        with pytest.raises(CostLimitExceededError, match="extraction_module_B"):
            await coord.extract(_section_result(), _wacc)


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
        # Sentinel: year=1990, label preserved
        assert fp.year == 1990
        assert fp.label == "gibberish"

    def test_empty_label_does_not_crash(self) -> None:
        fp = parse_fiscal_period("")
        assert fp.label == "unknown"
