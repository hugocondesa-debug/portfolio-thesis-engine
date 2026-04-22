"""Unit tests for extraction.module_c_leases.ModuleCLeases (Phase 1.5)."""

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


def _build_raw(leases: dict[str, Any] | None) -> RawExtraction:
    notes: dict[str, Any] = {}
    if leases is not None:
        notes["leases"] = leases
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
        "income_statement": {
            "FY2024": {
                "revenue": Decimal("1000"),
                "net_income": Decimal("80"),
            },
        },
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


class TestModuleCDisclosed:
    @pytest.mark.asyncio
    async def test_disclosed_additions_field_used_directly(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            {
                "rou_assets_opening": Decimal("400"),
                "rou_assets_closing": Decimal("440"),
                "rou_assets_additions": Decimal("120"),
                "rou_assets_depreciation": Decimal("80"),
                "lease_liabilities_opening": Decimal("400"),
                "lease_liabilities_closing": Decimal("430"),
                "lease_interest_expense": Decimal("20"),
                "lease_principal_payments": Decimal("90"),
            }
        )
        context = _make_context(_wacc, raw)
        module = ModuleCLeases(MagicMock(), _cost_tracker)

        await module.apply(context)

        c3 = [a for a in context.adjustments if a.module == "C.3"]
        assert len(c3) == 1
        assert c3[0].amount == Decimal("120")
        assert "Lease additions for FCFF" in c3[0].description

        decisions = "\n".join(context.decision_log)
        assert "C.1" in decisions
        assert "C.2" in decisions
        assert "C.3" in decisions


class TestModuleCDerived:
    @pytest.mark.asyncio
    async def test_additions_derived_from_movement(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        # No rou_assets_additions → back out from
        # closing - opening + principal_payments = 430 - 400 + 90 = 120
        raw = _build_raw(
            {
                "lease_liabilities_opening": Decimal("400"),
                "lease_liabilities_closing": Decimal("430"),
                "lease_principal_payments": Decimal("90"),
            }
        )
        context = _make_context(_wacc, raw)
        module = ModuleCLeases(MagicMock(), _cost_tracker)

        await module.apply(context)

        c3 = [a for a in context.adjustments if a.module == "C.3"]
        assert len(c3) == 1
        assert c3[0].amount == Decimal("120")
        assert any("derived" in e for e in context.estimates_log)


class TestModuleCApplicability:
    @pytest.mark.asyncio
    async def test_no_leases_note_skips(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(None)
        context = _make_context(_wacc, raw)
        module = ModuleCLeases(MagicMock(), _cost_tracker)

        await module.apply(context)

        assert context.adjustments == []
        assert any("C.0" in d for d in context.decision_log)

    @pytest.mark.asyncio
    async def test_missing_movement_skips_additions(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            {
                "rou_assets_closing": Decimal("100"),
                # No lease_liabilities_opening/closing
            }
        )
        context = _make_context(_wacc, raw)
        module = ModuleCLeases(MagicMock(), _cost_tracker)

        await module.apply(context)

        assert [a for a in context.adjustments if a.module == "C.3"] == []
        assert any("C.1" in d for d in context.decision_log)
        assert any("could not be derived" in e for e in context.estimates_log)


class TestModuleCExtras:
    @pytest.mark.asyncio
    async def test_interest_and_depreciation_logged_when_present(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            {
                "lease_liabilities_opening": Decimal("100"),
                "lease_liabilities_closing": Decimal("120"),
                "rou_assets_additions": Decimal("30"),
                "lease_interest_expense": Decimal("5"),
                "rou_assets_depreciation": Decimal("25"),
                "lease_principal_payments": Decimal("10"),
            }
        )
        context = _make_context(_wacc, raw)
        module = ModuleCLeases(MagicMock(), _cost_tracker)
        await module.apply(context)

        decisions = "\n".join(context.decision_log)
        assert "interest on lease liabilities" in decisions
        assert "ROU depreciation" in decisions
