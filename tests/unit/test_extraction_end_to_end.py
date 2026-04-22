"""End-to-end smoke for the extraction engine (Phase 1.5).

Starts from a :class:`RawExtraction` (what the pipeline loads from
``raw_extraction.yaml``) and runs the full
:class:`ExtractionCoordinator` path — Modules A, B, C plus
:class:`AnalysisDeriver` plus canonical-state construction — on the
EuroEyes fixture. Asserts the output is a valid
:class:`CanonicalCompanyState`.

No LLM is invoked: modules are deterministic, and the coordinator
doesn't call the LLM directly.
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

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "euroeyes" / "raw_extraction.yaml"


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
def _raw() -> RawExtraction:
    return parse_raw_extraction(_FIXTURE)


class TestEuroEyesEndToEnd:
    @pytest.mark.asyncio
    async def test_extract_canonical_produces_valid_state(
        self,
        _wacc: WACCInputs,
        _cost_tracker: CostTracker,
        _identity: CompanyIdentity,
        _raw: RawExtraction,
    ) -> None:
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=_cost_tracker,
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
        _raw: RawExtraction,
    ) -> None:
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=_cost_tracker,
        )
        result = await coord.extract_canonical(
            raw_extraction=_raw,
            wacc_inputs=_wacc,
            identity=_identity,
        )
        state = result.canonical_state
        assert state is not None

        # Adjustments routed to correct buckets
        assert len(state.adjustments.module_a_taxes) >= 1  # A.1 always emitted
        assert len(state.adjustments.module_c_leases) == 1  # C.3 lease additions
        # Module B: EuroEyes fixture has goodwill.impairment = -20M → one B.2
        assert len(state.adjustments.module_b_provisions) >= 1
        assert any(
            "goodwill_impairment" in adj.module
            for adj in state.adjustments.module_b_provisions
        )

        # Analysis block populated
        assert len(state.analysis.invested_capital_by_period) == 1
        ic = state.analysis.invested_capital_by_period[0]
        # Operating assets (EuroEyes FY2024 × 1M):
        # AR 120 + Inventory 80 + PP&E 950 + ROU 380 + Goodwill 600
        # + Intangibles 420 + Other NCA 200 = 2750 × 1M
        assert ic.operating_assets == Decimal("2750000000.0")
        # AP 95 + non_current_liabilities_other 105 = 200 × 1M
        assert ic.operating_liabilities == Decimal("200000000.0")
        assert ic.invested_capital == Decimal("2550000000.0")

        # NOPAT bridge
        bridge = state.analysis.nopat_bridge_by_period[0]
        # EBITDA = 110 + |−20| (D&A) = 130 × 1M
        assert bridge.ebitda == Decimal("130000000.0")
        assert bridge.ebita is None
        assert bridge.reported_net_income == Decimal("75000000.0")

        # Ratios
        ratios = state.analysis.ratios_by_period[0]
        # Op margin 110 / 580 ≈ 18.97%
        assert ratios.operating_margin is not None
        assert abs(ratios.operating_margin - Decimal("18.97")) < Decimal("0.05")

        # Reclassified statements carry the primary-period IS/BS/CF
        assert len(state.reclassified_statements) == 1
        rs = state.reclassified_statements[0]
        assert len(rs.income_statement) > 0
        assert len(rs.balance_sheet) > 0
        assert len(rs.cash_flow) > 0

        # Methodology records modules + Sprint label
        assert state.methodology.protocols_activated == ["A", "B", "C"]
        assert state.methodology.extraction_system_version == "phase1.5-sprint3"

    @pytest.mark.asyncio
    async def test_extract_without_canonical_still_works(
        self,
        _wacc: WACCInputs,
        _cost_tracker: CostTracker,
        _raw: RawExtraction,
    ) -> None:
        """``extract()`` (no identity) produces a result with
        ``canonical_state=None``."""
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=_cost_tracker,
        )
        result = await coord.extract(_raw, _wacc)
        assert result.canonical_state is None
        assert result.modules_run == ["A", "B", "C"]
