"""End-to-end smoke for the extraction engine (Phase 1.5.3).

Starts from the EuroEyes ``raw_extraction.yaml`` fixture, runs
Modules A/B/C + AnalysisDeriver + CanonicalCompanyState construction,
asserts the output is valid.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from portfolio_thesis_engine.extraction import ExtractionCoordinator
from portfolio_thesis_engine.ingestion.raw_extraction_parser import (
    parse_raw_extraction,
)
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.common import Currency, Profile
from portfolio_thesis_engine.schemas.company import (
    CanonicalCompanyState,
    CompanyIdentity,
)
from portfolio_thesis_engine.schemas.raw_extraction import RawExtraction
from portfolio_thesis_engine.schemas.wacc import (
    CapitalStructure,
    CostOfCapitalInputs,
    ScenarioDriversManual,
    WACCInputs,
)

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "euroeyes" / "raw_extraction_ar_2024.yaml"


@pytest.fixture
def _tracker(tmp_path: Path) -> CostTracker:
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
def _raw() -> RawExtraction:
    return parse_raw_extraction(_FIXTURE)


class TestEuroEyesEndToEnd:
    @pytest.mark.asyncio
    async def test_canonical_round_trips(
        self,
        _wacc: WACCInputs,
        _tracker: CostTracker,
        _identity: CompanyIdentity,
        _raw: RawExtraction,
    ) -> None:
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=_tracker,
        )
        result = await coord.extract_canonical(
            raw_extraction=_raw,
            wacc_inputs=_wacc,
            identity=_identity,
            source_documents=["1846-HK/annual_report/2024"],
        )
        state = result.canonical_state
        assert state is not None
        assert isinstance(state, CanonicalCompanyState)
        dumped = state.to_yaml()
        reloaded = CanonicalCompanyState.from_yaml(dumped)
        assert reloaded.identity.ticker == "1846.HK"

    @pytest.mark.asyncio
    async def test_state_contents(
        self,
        _wacc: WACCInputs,
        _tracker: CostTracker,
        _identity: CompanyIdentity,
        _raw: RawExtraction,
    ) -> None:
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=_tracker,
        )
        result = await coord.extract_canonical(
            raw_extraction=_raw,
            wacc_inputs=_wacc,
            identity=_identity,
        )
        state = result.canonical_state
        assert state is not None

        # Module A always emits A.1; Module B surfaces goodwill impairment
        assert len(state.adjustments.module_a_taxes) >= 1
        assert any(
            "goodwill_impairment" in adj.module
            for adj in state.adjustments.module_b_provisions
        )
        assert len(state.adjustments.module_c_leases) == 1  # C.3

        # Analysis present
        assert len(state.analysis.invested_capital_by_period) == 1
        ic = state.analysis.invested_capital_by_period[0]
        assert ic.invested_capital > Decimal("0")
        bridge = state.analysis.nopat_bridge_by_period[0]
        assert bridge.ebitda > Decimal("0")
        # Op margin sanity check (EuroEyes fixture: 110/580 ≈ 18.97%)
        ratios = state.analysis.ratios_by_period[0]
        assert ratios.operating_margin is not None
        assert Decimal("15") < ratios.operating_margin < Decimal("25")

        # Methodology marker
        assert state.methodology.extraction_system_version == "phase1.5.3"
        assert state.methodology.protocols_activated == ["A", "B", "C"]

        # Reclassified statements carry verbatim line_items
        rs = state.reclassified_statements[0]
        assert len(rs.income_statement) > 0
        assert len(rs.balance_sheet) > 0
        assert len(rs.cash_flow) > 0

    @pytest.mark.asyncio
    async def test_extract_without_canonical(
        self,
        _wacc: WACCInputs,
        _tracker: CostTracker,
        _raw: RawExtraction,
    ) -> None:
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=_tracker,
        )
        result = await coord.extract(_raw, _wacc)
        assert result.canonical_state is None
        assert result.modules_run == ["A", "B", "C"]
