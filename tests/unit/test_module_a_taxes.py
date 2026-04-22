"""Unit tests for extraction.module_a_taxes.ModuleATaxes (Phase 1.5)."""

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
from portfolio_thesis_engine.extraction.module_a_taxes import ModuleATaxes
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
            risk_free_rate=Decimal("3.0"),
            equity_risk_premium=Decimal("5.0"),
            beta=Decimal("1.0"),
            cost_of_debt_pretax=Decimal("5.0"),
            tax_rate_for_wacc=Decimal("25.0"),  # statutory fallback
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
    tax_note: dict[str, Any] | None = None,
    income_tax: Decimal | None = None,
    income_before_tax: Decimal | None = None,
    cf_extensions: dict[str, Decimal] | None = None,
) -> RawExtraction:
    """Minimal numeric :class:`RawExtraction` with optional tax note."""
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
                "operating_income": Decimal("150"),
                "income_before_tax": income_before_tax,
                "income_tax": income_tax,
                "net_income": Decimal("80"),
            },
        },
        "balance_sheet": {
            "FY2024": {
                "total_assets": Decimal("500"),
                "total_equity": Decimal("300"),
            },
        },
        "cash_flow": {
            "FY2024": {
                "operating_cash_flow": Decimal("120"),
                "extensions": cf_extensions or {},
            },
        },
        "notes": {"taxes": tax_note} if tax_note is not None else {},
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
# 1. Happy path
# ======================================================================


class TestModuleAHappyPath:
    @pytest.mark.asyncio
    async def test_operating_rate_computed_from_non_operating_items(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            income_tax=Decimal("-20"),
            income_before_tax=Decimal("100"),
            tax_note={
                "effective_tax_rate_percent": Decimal("20.0"),
                "statutory_rate_percent": Decimal("16.5"),
                "reconciling_items": [
                    # Operating: permanent non-deductible
                    {
                        "description": "Non-deductible",
                        "amount": Decimal("0.5"),
                        "classification": "operational",
                    },
                    # Non-operating: prior-year, one-off
                    {
                        "description": "Prior year adjustment",
                        "amount": Decimal("3.0"),
                        "classification": "one_time",
                    },
                ],
            },
        )
        context = _make_context(_wacc, raw)
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)

        # Non-operating sum = 3.0; operating tax = 20 - 3 = 17; pbt = 100
        # → operating_tax_rate ≈ 17%
        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        assert len(a1) == 1
        assert abs(a1[0].amount - Decimal("17.00")) < Decimal("0.01")

        # One non-operating item → one A.2 adjustment
        a2 = [adj for adj in context.adjustments if adj.module == "A.2"]
        assert len(a2) == 1
        assert a2[0].amount == Decimal("3.0")
        assert "Prior year adjustment" in a2[0].description

    @pytest.mark.asyncio
    async def test_decision_log_records_counts_and_rates(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            income_tax=Decimal("-44"),
            income_before_tax=Decimal("200"),
            tax_note={
                "effective_tax_rate_percent": Decimal("22.0"),
                "statutory_rate_percent": Decimal("25.0"),
                "reconciling_items": [
                    {
                        "description": "R&D credit",
                        "amount": Decimal("-3.0"),
                        "classification": "operational",
                    },
                    # >5% of statutory_tax (50) ⇒ material ⇒ A.2 branch
                    {
                        "description": "Gain on disposal of subsidiary",
                        "amount": Decimal("-6.0"),
                        "classification": "non_operational",
                    },
                ],
            },
        )
        context = _make_context(_wacc, raw)
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)

        decisions = "\n".join(context.decision_log)
        assert "Module A.2" in decisions
        assert "Module A.5" in decisions  # BS treatment note always emitted
        assert "1 non-operating reconciling item" in decisions
        assert "1 operating reconciling item" in decisions


# ======================================================================
# 2. Materiality gate (A.2.0)
# ======================================================================


class TestModuleAMateriality:
    @pytest.mark.asyncio
    async def test_immaterial_non_op_items_keep_effective_rate(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        # statutory_tax = 1000 × 25% = 250; non-op item 2 is <1% of 250
        raw = _build_raw(
            income_tax=Decimal("-180"),
            income_before_tax=Decimal("1000"),
            tax_note={
                "effective_tax_rate_percent": Decimal("18.0"),
                "statutory_rate_percent": Decimal("25.0"),
                "reconciling_items": [
                    {
                        "description": "Prior year adjustment",
                        "amount": Decimal("2.0"),
                        "classification": "one_time",
                    },
                ],
            },
        )
        context = _make_context(_wacc, raw)
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)

        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        assert len(a1) == 1
        # Materiality triggered → use effective rate
        assert a1[0].amount == Decimal("18.0")
        assert any("A.2.0" in d for d in context.decision_log)
        assert any("below 5%" in d for d in context.decision_log)


# ======================================================================
# 3. Label heuristics for classification "unknown"
# ======================================================================


class TestModuleAUnknownClassification:
    @pytest.mark.asyncio
    async def test_goodwill_keyword_in_unknown_reclassed_as_non_op(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            income_tax=Decimal("-20"),
            income_before_tax=Decimal("100"),
            tax_note={
                "effective_tax_rate_percent": Decimal("20.0"),
                "statutory_rate_percent": Decimal("16.5"),
                "reconciling_items": [
                    # classification "unknown" but label says goodwill → non-op
                    {
                        "description": "Non-deductible goodwill impairment",
                        "amount": Decimal("4.0"),
                        "classification": "unknown",
                    },
                ],
            },
        )
        context = _make_context(_wacc, raw)
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)

        a2 = [adj for adj in context.adjustments if adj.module == "A.2"]
        assert len(a2) == 1

    @pytest.mark.asyncio
    async def test_neutral_unknown_label_stays_operating(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            income_tax=Decimal("-20"),
            income_before_tax=Decimal("100"),
            tax_note={
                "effective_tax_rate_percent": Decimal("20.0"),
                "statutory_rate_percent": Decimal("16.5"),
                "reconciling_items": [
                    {
                        "description": "Various other items",
                        "amount": Decimal("3.5"),
                        "classification": "unknown",
                    },
                ],
            },
        )
        context = _make_context(_wacc, raw)
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)

        # Label has no non-op keyword → operating → no A.2 adjustment
        a2 = [adj for adj in context.adjustments if adj.module == "A.2"]
        assert a2 == []


# ======================================================================
# 4. Fallback paths
# ======================================================================


class TestModuleAFallbacks:
    @pytest.mark.asyncio
    async def test_no_taxes_note_falls_back_to_statutory(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            income_tax=Decimal("-20"),
            income_before_tax=Decimal("100"),
            tax_note=None,
        )
        context = _make_context(_wacc, raw)
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)

        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        assert len(a1) == 1
        assert a1[0].amount == Decimal("25.0")
        assert any("statutory fallback" in d for d in context.decision_log)

    @pytest.mark.asyncio
    async def test_missing_effective_rate_falls_back(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            income_tax=Decimal("-20"),
            income_before_tax=Decimal("100"),
            tax_note={
                # no effective_tax_rate_percent
                "statutory_rate_percent": Decimal("16.5"),
                "reconciling_items": [],
            },
        )
        context = _make_context(_wacc, raw)
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)
        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        assert a1[0].amount == Decimal("25.0")

    @pytest.mark.asyncio
    async def test_missing_income_tax_falls_back(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        # No income_tax on the IS → can't anchor reported tax
        raw = _build_raw(
            income_tax=None,
            income_before_tax=Decimal("100"),
            tax_note={
                "effective_tax_rate_percent": Decimal("20.0"),
                "statutory_rate_percent": Decimal("16.5"),
                "reconciling_items": [],
            },
        )
        context = _make_context(_wacc, raw)
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)
        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        assert a1[0].amount == Decimal("25.0")

    @pytest.mark.asyncio
    async def test_pbt_derived_when_not_disclosed(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        # No income_before_tax → derive pbt = 20 / 0.20 = 100
        raw = _build_raw(
            income_tax=Decimal("-20"),
            income_before_tax=None,
            tax_note={
                "effective_tax_rate_percent": Decimal("20.0"),
                "statutory_rate_percent": Decimal("16.5"),
                "reconciling_items": [
                    {
                        "description": "Gain on disposal",
                        "amount": Decimal("-2.0"),
                        "classification": "non_operational",
                    },
                ],
            },
        )
        context = _make_context(_wacc, raw)
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)

        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        # Derived pbt = 100, operating tax = 20 - (-2) = 22, rate = 22%
        assert abs(a1[0].amount - Decimal("22.00")) < Decimal("0.01")
        assert any(
            "derived from reported_tax" in e for e in context.estimates_log
        )

    @pytest.mark.asyncio
    async def test_zero_effective_rate_forces_statutory_fallback(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            income_tax=Decimal("0"),
            income_before_tax=None,
            tax_note={
                "effective_tax_rate_percent": Decimal("0"),
                "statutory_rate_percent": Decimal("16.5"),
                "reconciling_items": [
                    # Material non-op → forces the A.2 branch
                    {
                        "description": "One-off",
                        "amount": Decimal("10.0"),
                        "classification": "non_operational",
                    },
                ],
            },
        )
        context = _make_context(_wacc, raw)
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)
        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        assert a1[0].amount == Decimal("25.0")
        assert any(
            "could not derive profit_before_tax" in e
            for e in context.estimates_log
        )


# ======================================================================
# 5. Cash taxes (A.4) + always-on A.5 note
# ======================================================================


class TestModuleANotes:
    @pytest.mark.asyncio
    async def test_cash_taxes_delta_logged_when_in_cf_extensions(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            income_tax=Decimal("-20"),
            income_before_tax=Decimal("100"),
            cf_extensions={"cash_taxes_paid": Decimal("18.0")},
            tax_note={
                "effective_tax_rate_percent": Decimal("20.0"),
                "statutory_rate_percent": Decimal("16.5"),
                "reconciling_items": [],
            },
        )
        context = _make_context(_wacc, raw)
        module = ModuleATaxes(MagicMock(), _cost_tracker)
        await module.apply(context)

        assert any(
            "A.4" in d and "cash taxes" in d for d in context.decision_log
        )

    @pytest.mark.asyncio
    async def test_a5_bs_note_always_emitted_when_note_parsed(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            income_tax=Decimal("-20"),
            income_before_tax=Decimal("100"),
            tax_note={
                "effective_tax_rate_percent": Decimal("20.0"),
                "statutory_rate_percent": Decimal("16.5"),
                "reconciling_items": [],
            },
        )
        context = _make_context(_wacc, raw)
        module = ModuleATaxes(MagicMock(), _cost_tracker)
        await module.apply(context)

        assert any("A.5" in d for d in context.decision_log)


# ======================================================================
# 6. Empty recon list
# ======================================================================


class TestModuleARobustness:
    @pytest.mark.asyncio
    async def test_empty_reconciling_items_still_emits_operating_rate(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        raw = _build_raw(
            income_tax=Decimal("-20"),
            income_before_tax=Decimal("100"),
            tax_note={
                "effective_tax_rate_percent": Decimal("20.0"),
                "statutory_rate_percent": Decimal("16.5"),
                "reconciling_items": [],
            },
        )
        context = _make_context(_wacc, raw)
        module = ModuleATaxes(MagicMock(), _cost_tracker)
        await module.apply(context)

        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        # No non-op items → operating_tax_rate == effective (20%)
        assert a1[0].amount == Decimal("20.0")
