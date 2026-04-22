"""Unit tests for extraction.module_b_provisions.ModuleBProvisions (Phase 1.5)."""

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
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.common import Currency, Profile
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


def _build_raw(
    *,
    is_extras: dict[str, Decimal] | None = None,
    provisions: list[dict[str, Any]] | None = None,
    goodwill: dict[str, Any] | None = None,
    discontinued_ops: dict[str, Any] | None = None,
) -> RawExtraction:
    is_fields: dict[str, Any] = {
        "revenue": Decimal("1000"),
        "operating_income": Decimal("150"),
        "net_income": Decimal("80"),
    }
    if is_extras:
        is_fields.update(is_extras)
    notes: dict[str, Any] = {}
    if provisions is not None:
        notes["provisions"] = provisions
    if goodwill is not None:
        notes["goodwill"] = goodwill
    if discontinued_ops is not None:
        notes["discontinued_ops"] = discontinued_ops
    payload: dict[str, Any] = {
        "metadata": {
            "ticker": "TST",
            "company_name": "Test Co",
            "document_type": DocumentType.ANNUAL_REPORT,
            "extraction_type": ExtractionType.NUMERIC,
            "reporting_currency": Currency.USD,
            "unit_scale": "units",
            "fiscal_year": 2024,
            "extraction_date": "2025-01-01",
            "fiscal_periods": [
                {"period": "FY2024", "end_date": "2024-12-31", "is_primary": True},
            ],
        },
        "income_statement": {"FY2024": is_fields},
        "balance_sheet": {
            "FY2024": {
                "total_assets": Decimal("500"),
                "total_equity": Decimal("300"),
            },
        },
        "notes": notes,
    }
    return RawExtraction.model_validate(payload)


def _make_context(wacc: WACCInputs, raw: RawExtraction) -> ExtractionContext:
    return ExtractionContext(
        ticker=raw.metadata.ticker,
        fiscal_period_label="FY2024",
        primary_period=parse_fiscal_period("FY2024"),
        raw_extraction=raw,
        wacc_inputs=wacc,
    )


# ======================================================================
# 1. Goodwill impairment (from notes.goodwill.impairment)
# ======================================================================


class TestModuleBGoodwill:
    @pytest.mark.asyncio
    async def test_goodwill_impairment_surfaces_as_adjustment(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            goodwill={
                "opening": Decimal("100"),
                "impairment": Decimal("-50"),
                "closing": Decimal("50"),
            },
        )
        context = _make_context(_wacc, raw)
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)

        adj = [a for a in context.adjustments if a.module == "B.2.goodwill_impairment"]
        assert len(adj) == 1
        assert adj[0].amount == Decimal("-50")

    @pytest.mark.asyncio
    async def test_zero_goodwill_impairment_no_adjustment(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            goodwill={
                "opening": Decimal("100"),
                "impairment": Decimal("0"),
                "closing": Decimal("100"),
            },
        )
        context = _make_context(_wacc, raw)
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)

        assert [
            a for a in context.adjustments if a.module == "B.2.goodwill_impairment"
        ] == []


# ======================================================================
# 2. Provisions classification vocabulary
# ======================================================================


class TestModuleBProvisions:
    @pytest.mark.asyncio
    async def test_restructuring_provision_surfaces(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            provisions=[
                {
                    "description": "Site closure restructuring",
                    "amount": Decimal("-30"),
                    "classification": "restructuring",
                },
            ],
        )
        context = _make_context(_wacc, raw)
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)

        adj = [a for a in context.adjustments if a.module == "B.2.restructuring"]
        assert len(adj) == 1

    @pytest.mark.asyncio
    async def test_impairment_provision_surfaces(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            provisions=[
                {
                    "description": "PP&E impairment",
                    "amount": Decimal("-40"),
                    "classification": "impairment",
                },
            ],
        )
        context = _make_context(_wacc, raw)
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)

        adj = [a for a in context.adjustments if a.module == "B.2.asset_impairment"]
        assert len(adj) == 1

    @pytest.mark.asyncio
    async def test_operating_provisions_ignored(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            provisions=[
                {
                    "description": "Warranty",
                    "amount": Decimal("5"),
                    "classification": "operating",
                },
                {
                    "description": "Other",
                    "amount": Decimal("3"),
                    "classification": "other",
                },
            ],
        )
        context = _make_context(_wacc, raw)
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)
        b2 = [a for a in context.adjustments if a.module.startswith("B.2")]
        assert b2 == []

    @pytest.mark.asyncio
    async def test_non_operating_classification_surfaces(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            provisions=[
                {
                    "description": "Litigation",
                    "amount": Decimal("-20"),
                    "classification": "non_operating",
                },
            ],
        )
        context = _make_context(_wacc, raw)
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)
        adj = [
            a for a in context.adjustments if a.module == "B.2.non_operating_other"
        ]
        assert len(adj) == 1


# ======================================================================
# 3. IS non-operating fields
# ======================================================================


class TestModuleBISFields:
    @pytest.mark.asyncio
    async def test_non_operating_income_surfaces(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(is_extras={"non_operating_income": Decimal("12")})
        context = _make_context(_wacc, raw)
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)
        adj = [
            a for a in context.adjustments if a.module == "B.2.non_operating_other"
        ]
        assert len(adj) == 1
        assert adj[0].amount == Decimal("12")

    @pytest.mark.asyncio
    async def test_share_of_associates_surfaces(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(is_extras={"share_of_associates": Decimal("5")})
        context = _make_context(_wacc, raw)
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)
        adj = [a for a in context.adjustments if a.module == "B.2.associates"]
        assert len(adj) == 1

    @pytest.mark.asyncio
    async def test_discontinued_ops_surfaces(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            is_extras={"net_income_from_discontinued": Decimal("-8")},
            discontinued_ops={"net_income": Decimal("-8")},
        )
        context = _make_context(_wacc, raw)
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)
        adj = [a for a in context.adjustments if a.module == "B.2.discontinued"]
        assert len(adj) == 1
        # Discontinued-ops note presence logged
        assert any("discontinued-ops note" in d for d in context.decision_log)

    @pytest.mark.asyncio
    async def test_zero_is_fields_no_adjustments(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            is_extras={
                "non_operating_income": Decimal("0"),
                "share_of_associates": Decimal("0"),
            },
        )
        context = _make_context(_wacc, raw)
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)
        assert [a for a in context.adjustments if a.module.startswith("B.2")] == []


# ======================================================================
# 4. B.0 applicability — nothing in extraction
# ======================================================================


class TestModuleBApplicability:
    @pytest.mark.asyncio
    async def test_no_non_op_fields_logs_b1_noop(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw()
        context = _make_context(_wacc, raw)
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)

        assert context.adjustments == []
        assert any(
            "B.1" in d and "no non-operating" in d for d in context.decision_log
        )


# ======================================================================
# 5. Combined: multiple sources
# ======================================================================


class TestModuleBCombined:
    @pytest.mark.asyncio
    async def test_goodwill_and_is_and_provisions_all_surface(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            is_extras={
                "non_operating_income": Decimal("8"),
                "share_of_associates": Decimal("4"),
            },
            goodwill={"impairment": Decimal("-30")},
            provisions=[
                {
                    "description": "Restructuring",
                    "amount": Decimal("-15"),
                    "classification": "restructuring",
                },
            ],
        )
        context = _make_context(_wacc, raw)
        module = ModuleBProvisions(MagicMock(), _cost_tracker)

        await module.apply(context)

        b2 = [a for a in context.adjustments if a.module.startswith("B.2")]
        assert len(b2) == 4
        modules = {a.module for a in b2}
        assert "B.2.goodwill_impairment" in modules
        assert "B.2.restructuring" in modules
        assert "B.2.non_operating_other" in modules
        assert "B.2.associates" in modules
