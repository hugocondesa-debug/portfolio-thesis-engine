"""End-to-end smoke for the extraction engine.

Starts from a :class:`SectionExtractionResult` (what the section
extractor would produce in production) and runs the full
:class:`ExtractionCoordinator` path — Modules A, B, C plus
:class:`AnalysisDeriver` plus canonical-state construction — over
synthetic EuroEyes numbers. Asserts the output is a valid
:class:`CanonicalCompanyState`.

No LLM is invoked: Modules A/B/C are deterministic, and the
coordinator doesn't call the LLM directly. The section-extractor
layer (which _does_ call the LLM) has its own tests in
``test_section_parsers.py``.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from portfolio_thesis_engine.extraction import ExtractionCoordinator
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.common import Currency, Profile
from portfolio_thesis_engine.schemas.company import CanonicalCompanyState, CompanyIdentity
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

# ======================================================================
# EuroEyes synthetic data (mirrors tests/fixtures/euroeyes/*, HKD m)
# ======================================================================

_IS = {
    "fiscal_period": "FY2024",
    "currency": "HKD",
    "currency_unit": "millions",
    "line_items": [
        {"label": "Revenue", "value_current": 580.0, "category": "revenue"},
        {"label": "Cost of sales", "value_current": -290.0, "category": "cost_of_sales"},
        {"label": "D&A", "value_current": -20.0, "category": "d_and_a"},
        {"label": "Operating income", "value_current": 110.0, "category": "operating_income"},
        {"label": "Finance income", "value_current": 4.0, "category": "finance_income"},
        {"label": "Finance expense", "value_current": -18.0, "category": "finance_expense"},
        {"label": "Income tax expense", "value_current": -21.0, "category": "tax"},
        {"label": "Net income", "value_current": 75.0, "category": "net_income"},
    ],
}

_BS = {
    "as_of_date": "2024-12-31",
    "currency": "HKD",
    "currency_unit": "millions",
    "line_items": [
        {"label": "Cash and equivalents", "value_current": 450.0, "category": "cash"},
        {"label": "Trade receivables", "value_current": 320.0, "category": "operating_assets"},
        {"label": "Inventories", "value_current": 180.0, "category": "operating_assets"},
        {"label": "PP&E", "value_current": 1800.0, "category": "operating_assets"},
        {"label": "Goodwill", "value_current": 450.0, "category": "intangibles"},
        {"label": "Trade payables", "value_current": 210.0, "category": "operating_liabilities"},
        {"label": "Long-term debt", "value_current": 580.0, "category": "financial_liabilities"},
        {"label": "Lease liabilities", "value_current": 260.0, "category": "lease_liabilities"},
        {"label": "Total equity", "value_current": 1900.0, "category": "equity"},
    ],
}

_CF = {
    "fiscal_period": "FY2024",
    "currency": "HKD",
    "currency_unit": "millions",
    "line_items": [
        {"label": "CFO", "value_current": 135.0, "category": "cfo"},
        {"label": "CapEx", "value_current": -75.0, "category": "capex"},
        {"label": "Lease principal repayments", "value_current": -45.0, "category": "lease_payments"},
    ],
}

_TAXES = {
    "fiscal_period": "FY2024",
    "statutory_rate_pct": 16.5,
    "effective_rate_pct": 21.88,  # 21 / 96
    "profit_before_tax": 96.0,
    "statutory_tax": 15.84,
    "reported_tax_expense": 21.0,
    "reconciling_items": [
        {"label": "Non-deductible expenses", "amount": 2.5, "category": "non_deductible"},
        {
            "label": "Rate differential Germany (30%) vs HK (16.5%)",
            "amount": 3.7,
            "category": "rate_diff_jurisdiction",
        },
        {
            "label": "Prior-year adjustment",
            "amount": -1.0,
            "category": "prior_year_adjustment",
        },
    ],
}

_LEASES = {
    "fiscal_period": "FY2024",
    "currency": "HKD",
    "currency_unit": "millions",
    "rou_assets_by_category": [
        {"category": "Medical clinics", "value_current": 240.0},
        {"category": "Office space", "value_current": 35.0},
    ],
    "lease_liability_movement": {
        "opening_balance": 245.0,
        "additions": 60.0,
        "depreciation_of_rou": 40.0,
        "interest_expense": 12.0,
        "principal_payments": 45.0,
        "closing_balance": 260.0,
    },
}


@pytest.fixture
def _cost_tracker(tmp_path: Path) -> CostTracker:
    return CostTracker(log_path=tmp_path / "costs.jsonl")


@pytest.fixture
def _wacc() -> WACCInputs:
    return WACCInputs(
        ticker="1846.HK",
        profile=Profile.P1_INDUSTRIAL,
        valuation_date="2024-12-31",
        current_price=Decimal("12.30"),
        cost_of_capital=CostOfCapitalInputs(
            risk_free_rate=Decimal("2.5"),
            equity_risk_premium=Decimal("5.5"),
            beta=Decimal("1.1"),
            cost_of_debt_pretax=Decimal("4.0"),
            tax_rate_for_wacc=Decimal("16.5"),
        ),
        capital_structure=CapitalStructure(
            debt_weight=Decimal("25"),
            equity_weight=Decimal("75"),
        ),
        scenarios={
            "base": ScenarioDriversManual(
                probability=Decimal("100"),
                revenue_cagr_explicit_period=Decimal("8"),
                terminal_growth=Decimal("3"),
                terminal_operating_margin=Decimal("20"),
            )
        },
    )


@pytest.fixture
def _identity() -> CompanyIdentity:
    return CompanyIdentity(
        ticker="1846.HK",
        name="EuroEyes Medical Group",
        reporting_currency=Currency.HKD,
        profile=Profile.P1_INDUSTRIAL,
        fiscal_year_end_month=12,
        country_domicile="HK",
        exchange="HKEX",
        shares_outstanding=Decimal("200000000"),
    )


@pytest.fixture
def _section_result() -> SectionExtractionResult:
    sections = [
        StructuredSection("income_statement", "IS", "", parsed_data=_IS),
        StructuredSection("balance_sheet", "BS", "", parsed_data=_BS),
        StructuredSection("cash_flow", "CF", "", parsed_data=_CF),
        StructuredSection("notes_taxes", "Taxes", "", parsed_data=_TAXES),
        StructuredSection("notes_leases", "Leases", "", parsed_data=_LEASES),
    ]
    return SectionExtractionResult(
        doc_id="1846-HK/annual_report/2024",
        ticker="1846.HK",
        fiscal_period="FY2024",
        sections=sections,
    )


# ======================================================================
# E2E smoke
# ======================================================================


class TestEuroEyesEndToEnd:
    @pytest.mark.asyncio
    async def test_extract_canonical_produces_valid_state(
        self,
        _wacc: WACCInputs,
        _cost_tracker: CostTracker,
        _identity: CompanyIdentity,
        _section_result: SectionExtractionResult,
    ) -> None:
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=_cost_tracker,
        )
        result = await coord.extract_canonical(
            section_result=_section_result,
            wacc_inputs=_wacc,
            identity=_identity,
            source_documents=["1846-HK/annual_report/2024"],
        )
        state = result.canonical_state
        assert state is not None
        assert isinstance(state, CanonicalCompanyState)

        # Round-trip through YAML — the strongest validation test.
        dumped = state.to_yaml()
        roundtripped = CanonicalCompanyState.from_yaml(dumped)
        assert roundtripped.identity.ticker == "1846.HK"

    @pytest.mark.asyncio
    async def test_canonical_state_contents(
        self,
        _wacc: WACCInputs,
        _cost_tracker: CostTracker,
        _identity: CompanyIdentity,
        _section_result: SectionExtractionResult,
    ) -> None:
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=_cost_tracker,
        )
        result = await coord.extract_canonical(
            section_result=_section_result,
            wacc_inputs=_wacc,
            identity=_identity,
        )
        state = result.canonical_state
        assert state is not None

        # Adjustments routed to correct buckets
        assert len(state.adjustments.module_a_taxes) >= 1  # A.1 always emitted
        assert len(state.adjustments.module_c_leases) == 1  # C.3 lease additions
        # Module B: no goodwill/restructuring lines in the EuroEyes IS
        # → no B.2 adjustments in this fixture
        assert state.adjustments.module_b_provisions == []

        # Analysis block populated
        assert len(state.analysis.invested_capital_by_period) == 1
        ic = state.analysis.invested_capital_by_period[0]
        # Op assets = 320 + 180 + 1800 + 450 (goodwill in intangibles) = 2750
        assert ic.operating_assets == Decimal("2750.0")
        # Op liab = 210
        assert ic.operating_liabilities == Decimal("210.0")
        assert ic.invested_capital == Decimal("2540.0")

        # NOPAT bridge
        bridge = state.analysis.nopat_bridge_by_period[0]
        # EBITA = 110 + 20 (D&A) = 130
        assert bridge.ebita == Decimal("130.0")
        # Reported NI matches fixture
        assert bridge.reported_net_income == Decimal("75.0")

        # Ratios
        ratios = state.analysis.ratios_by_period[0]
        # Op margin 110/580 ≈ 18.97%
        assert ratios.operating_margin is not None
        assert abs(ratios.operating_margin - Decimal("18.97")) < Decimal("0.05")

        # Reclassified statements carry the IS/BS/CF
        assert len(state.reclassified_statements) == 1
        rs = state.reclassified_statements[0]
        assert len(rs.income_statement) == len(_IS["line_items"])
        assert len(rs.balance_sheet) == len(_BS["line_items"])
        assert len(rs.cash_flow) == len(_CF["line_items"])

        # Methodology records modules
        assert state.methodology.protocols_activated == ["A", "B", "C"]
        assert state.methodology.extraction_system_version == "phase1-sprint7"

    @pytest.mark.asyncio
    async def test_extract_without_canonical_still_works(
        self,
        _wacc: WACCInputs,
        _cost_tracker: CostTracker,
        _section_result: SectionExtractionResult,
    ) -> None:
        """``extract()`` (no identity) produces a result with
        ``canonical_state=None`` — the low-level path used by tests."""
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=_cost_tracker,
        )
        result = await coord.extract(_section_result, _wacc)
        assert result.canonical_state is None
        assert result.modules_run == ["A", "B", "C"]
