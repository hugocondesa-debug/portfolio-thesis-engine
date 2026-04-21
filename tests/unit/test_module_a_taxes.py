"""Unit tests for extraction.module_a_taxes.ModuleATaxes."""

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
from portfolio_thesis_engine.extraction.raw_extraction_adapter import StructuredSection
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.common import Profile
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


def _make_context(
    wacc: WACCInputs,
    sections: list[StructuredSection],
    ticker: str = "TST",
    label: str = "FY2024",
) -> ExtractionContext:
    return ExtractionContext(
        ticker=ticker,
        fiscal_period_label=label,
        primary_period=parse_fiscal_period(label),
        sections=sections,
        wacc_inputs=wacc,
    )


def _tax_section(parsed: dict[str, Any] | None) -> StructuredSection:
    return StructuredSection(
        section_type="notes_taxes",
        title="Note 7 — Income Tax Reconciliation",
        content="",
        parsed_data=parsed,
    )


# ======================================================================
# 1. Happy path — tax recon with mixed operating + non-operating items
# ======================================================================


class TestModuleAHappyPath:
    @pytest.mark.asyncio
    async def test_operating_rate_computed_from_non_operating_items(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "fiscal_period": "FY2024",
            "statutory_rate_pct": 16.5,
            "effective_rate_pct": 20.0,
            "profit_before_tax": 100.0,
            "statutory_tax": 16.5,
            "reported_tax_expense": 20.0,
            "reconciling_items": [
                # Operating: permanent non-deductible expenses affecting core
                {"label": "Non-deductible", "amount": 0.5, "category": "non_deductible"},
                # Non-operating: prior-year true-up, one-off
                {
                    "label": "Prior year adjustment",
                    "amount": 3.0,
                    "category": "prior_year_adjustment",
                },
            ],
        }
        context = _make_context(_wacc, [_tax_section(parsed)])
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)

        # Non-operating sum = 3.0; operating tax = 20 - 3 = 17; pbt = 100
        # → operating_tax_rate ≈ 17%
        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        assert len(a1) == 1
        rate = a1[0].amount
        assert abs(rate - Decimal("17.00")) < Decimal("0.01"), rate

        # One non-operating item → one A.2 adjustment
        a2 = [adj for adj in context.adjustments if adj.module == "A.2"]
        assert len(a2) == 1
        assert a2[0].amount == Decimal("3.0")
        assert "Prior year adjustment" in a2[0].description

    @pytest.mark.asyncio
    async def test_decision_log_records_counts_and_rates(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "effective_rate_pct": 22.0,
            "profit_before_tax": 200.0,
            "statutory_tax": 50.0,
            "reported_tax_expense": 44.0,
            "reconciling_items": [
                {"label": "R&D credit", "amount": -3.0, "category": "tax_credit"},
                # >5% of statutory_tax (50) ⇒ material ⇒ A.2 branch taken
                {
                    "label": "Gain on disposal of subsidiary (tax-exempt)",
                    "amount": -6.0,
                    "category": "non_operating",
                },
            ],
        }
        context = _make_context(_wacc, [_tax_section(parsed)])
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)

        decisions = "\n".join(context.decision_log)
        assert "Module A.2" in decisions
        assert "Module A.5" in decisions  # BS treatment note always emitted
        # 1 non-op item, 1 operating item recorded
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
        parsed = {
            "effective_rate_pct": 18.0,
            "profit_before_tax": 1000.0,
            "statutory_tax": 250.0,  # Large statutory tax
            "reported_tax_expense": 180.0,
            "reconciling_items": [
                {
                    "label": "Prior year adjustment",
                    "amount": 2.0,  # Tiny vs statutory_tax 250
                    "category": "prior_year_adjustment",
                },
            ],
        }
        context = _make_context(_wacc, [_tax_section(parsed)])
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)

        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        assert len(a1) == 1
        # Materiality triggered → use effective rate
        assert a1[0].amount == Decimal("18.0")
        assert any("A.2.0" in d for d in context.decision_log)
        assert any("below 5%" in d for d in context.decision_log)


# ======================================================================
# 3. Label heuristics for category "other"
# ======================================================================


class TestModuleACategoryOther:
    @pytest.mark.asyncio
    async def test_goodwill_keyword_in_other_reclassed_as_non_op(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "effective_rate_pct": 20.0,
            "profit_before_tax": 100.0,
            "statutory_tax": 16.5,
            "reported_tax_expense": 20.0,
            "reconciling_items": [
                # category = "other" but label says goodwill → non-operating
                {
                    "label": "Non-deductible goodwill impairment",
                    "amount": 4.0,
                    "category": "other",
                },
            ],
        }
        context = _make_context(_wacc, [_tax_section(parsed)])
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)

        a2 = [adj for adj in context.adjustments if adj.module == "A.2"]
        assert len(a2) == 1  # Was reclassified

    @pytest.mark.asyncio
    async def test_neutral_other_label_stays_operating(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "effective_rate_pct": 20.0,
            "profit_before_tax": 100.0,
            "statutory_tax": 16.5,
            "reported_tax_expense": 20.0,
            "reconciling_items": [
                {
                    "label": "Various other items",
                    "amount": 3.5,
                    "category": "other",
                },
            ],
        }
        context = _make_context(_wacc, [_tax_section(parsed)])
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
    async def test_no_notes_taxes_falls_back_to_statutory(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        context = _make_context(_wacc, sections=[])
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)

        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        assert len(a1) == 1
        # Falls back to 25% from WACCInputs
        assert a1[0].amount == Decimal("25.0")
        assert any("statutory fallback" in d for d in context.decision_log)

    @pytest.mark.asyncio
    async def test_notes_taxes_without_parsed_data_is_fallback(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        # parsed_data=None (Pass 2 didn't run or returned empty)
        context = _make_context(_wacc, [_tax_section(None)])
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)

        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        assert a1[0].amount == Decimal("25.0")

    @pytest.mark.asyncio
    async def test_missing_effective_rate_falls_back(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            # No effective_rate_pct → can't compute; fallback
            "reported_tax_expense": 20.0,
            "reconciling_items": [],
        }
        context = _make_context(_wacc, [_tax_section(parsed)])
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)
        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        assert a1[0].amount == Decimal("25.0")

    @pytest.mark.asyncio
    async def test_pbt_derived_when_not_disclosed(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "effective_rate_pct": 20.0,
            "reported_tax_expense": 20.0,
            "statutory_tax": 16.5,
            # No profit_before_tax → derive pbt = 20 / 0.20 = 100
            "reconciling_items": [
                {"label": "Gain on disposal", "amount": -2.0, "category": "non_operating"},
            ],
        }
        context = _make_context(_wacc, [_tax_section(parsed)])
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)

        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        # Derived pbt = 100, operating tax = 20 - (-2) = 22, rate = 22%
        assert abs(a1[0].amount - Decimal("22.00")) < Decimal("0.01"), a1[0].amount
        assert any("derived from reported_tax" in e for e in context.estimates_log)


# ======================================================================
# 5. A.3 / A.4 / A.5 notes
# ======================================================================


class TestModuleANotes:
    @pytest.mark.asyncio
    async def test_dta_dtl_logged_when_present(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "effective_rate_pct": 20.0,
            "profit_before_tax": 100.0,
            "statutory_tax": 16.5,
            "reported_tax_expense": 20.0,
            "reconciling_items": [],
            "deferred_tax_asset": 30.0,
            "deferred_tax_liability": 12.0,
        }
        context = _make_context(_wacc, [_tax_section(parsed)])
        module = ModuleATaxes(MagicMock(), _cost_tracker)
        await module.apply(context)

        assert any("A.3" in d and "DTA=30" in d for d in context.decision_log)

    @pytest.mark.asyncio
    async def test_cash_taxes_delta_logged_when_present(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "effective_rate_pct": 20.0,
            "profit_before_tax": 100.0,
            "statutory_tax": 16.5,
            "reported_tax_expense": 20.0,
            "reconciling_items": [],
            "cash_taxes_paid": 18.0,
        }
        context = _make_context(_wacc, [_tax_section(parsed)])
        module = ModuleATaxes(MagicMock(), _cost_tracker)
        await module.apply(context)

        assert any("A.4" in d and "cash taxes" in d for d in context.decision_log)

    @pytest.mark.asyncio
    async def test_a5_bs_note_always_emitted_when_section_parsed(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "effective_rate_pct": 20.0,
            "profit_before_tax": 100.0,
            "statutory_tax": 16.5,
            "reported_tax_expense": 20.0,
            "reconciling_items": [],
        }
        context = _make_context(_wacc, [_tax_section(parsed)])
        module = ModuleATaxes(MagicMock(), _cost_tracker)
        await module.apply(context)

        assert any("A.5" in d for d in context.decision_log)


# ======================================================================
# 6. Robustness — malformed input
# ======================================================================


class TestModuleARobustness:
    @pytest.mark.asyncio
    async def test_reconciling_item_with_unparseable_amount_ignored(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "effective_rate_pct": 20.0,
            "profit_before_tax": 100.0,
            "statutory_tax": 16.5,
            "reported_tax_expense": 20.0,
            "reconciling_items": [
                {"label": "Valid op", "amount": 1.0, "category": "non_deductible"},
                {"label": "Malformed", "amount": "not-a-number", "category": "other"},
                {"label": "Nulled", "amount": None, "category": "other"},
            ],
        }
        context = _make_context(_wacc, [_tax_section(parsed)])
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)

        # Only the valid operating item is counted; module doesn't crash
        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        assert a1  # didn't fall back

    @pytest.mark.asyncio
    async def test_zero_effective_rate_forces_statutory_fallback(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        # Effective rate 0 and no PBT → can't derive PBT → fallback.
        parsed = {
            "effective_rate_pct": 0.0,
            "reported_tax_expense": 0.0,
            "statutory_tax": 16.5,
            "reconciling_items": [
                # Material enough to take the non-fallback branch
                {"label": "One-off", "amount": 10.0, "category": "non_operating"},
            ],
        }
        context = _make_context(_wacc, [_tax_section(parsed)])
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)
        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        # Fallback to 25% statutory
        assert a1[0].amount == Decimal("25.0")
        assert any("could not derive profit_before_tax" in e for e in context.estimates_log)

    @pytest.mark.asyncio
    async def test_empty_reconciling_items_still_emits_operating_rate(
        self, _wacc: WACCInputs, _cost_tracker: CostTracker
    ) -> None:
        parsed = {
            "effective_rate_pct": 20.0,
            "profit_before_tax": 100.0,
            "statutory_tax": 16.5,
            "reported_tax_expense": 20.0,
            "reconciling_items": [],
        }
        context = _make_context(_wacc, [_tax_section(parsed)])
        module = ModuleATaxes(MagicMock(), _cost_tracker)

        await module.apply(context)

        a1 = [adj for adj in context.adjustments if adj.module == "A.1"]
        # No non-op items → operating_tax_rate == effective
        assert a1[0].amount == Decimal("20.0")
