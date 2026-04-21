"""Unit tests for valuation.irr.IRRDecomposer."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from portfolio_thesis_engine.schemas.common import (
    Currency,
    FiscalPeriod,
    Profile,
)
from portfolio_thesis_engine.schemas.company import (
    AdjustmentsApplied,
    AnalysisDerived,
    CanonicalCompanyState,
    CompanyIdentity,
    MethodologyMetadata,
    ReclassifiedStatements,
    ValidationResult,
    ValidationResults,
    VintageAndCascade,
)
from portfolio_thesis_engine.schemas.valuation import Scenario, ScenarioDrivers
from portfolio_thesis_engine.valuation.irr import IRRDecomposer


def _canonical() -> CanonicalCompanyState:
    period = FiscalPeriod(year=2024, label="FY2024")
    return CanonicalCompanyState(
        extraction_id="ext1",
        extraction_date=datetime(2024, 12, 31, tzinfo=UTC),
        as_of_date="2024-12-31",
        identity=CompanyIdentity(
            ticker="TST",
            name="Test Co",
            reporting_currency=Currency.USD,
            profile=Profile.P1_INDUSTRIAL,
            fiscal_year_end_month=12,
            country_domicile="US",
            exchange="NYSE",
        ),
        reclassified_statements=[
            ReclassifiedStatements(
                period=period,
                income_statement=[],
                balance_sheet=[],
                cash_flow=[],
                bs_checksum_pass=True,
                is_checksum_pass=True,
                cf_checksum_pass=True,
            )
        ],
        adjustments=AdjustmentsApplied(),
        analysis=AnalysisDerived(
            invested_capital_by_period=[],
            nopat_bridge_by_period=[],
            ratios_by_period=[],
        ),
        validation=ValidationResults(
            universal_checksums=[
                ValidationResult(check_id="V.0", name="s", status="PASS", detail="ok")
            ],
            profile_specific_checksums=[],
            confidence_rating="MEDIUM",
        ),
        vintage=VintageAndCascade(),
        methodology=MethodologyMetadata(
            extraction_system_version="test",
            profile_applied=Profile.P1_INDUSTRIAL,
            protocols_activated=[],
        ),
    )


def _scenario(cagr: Decimal = Decimal("8")) -> Scenario:
    return Scenario(
        label="base",
        description="test",
        probability=Decimal("100"),
        horizon_years=3,
        drivers=ScenarioDrivers(revenue_cagr=cagr, terminal_growth=Decimal("2"), terminal_margin=Decimal("20")),
    )


class TestIRRMath:
    def test_total_irr_from_target_vs_current(self) -> None:
        # target = 133.1, current = 100, horizon = 3 → IRR = 10 %
        result = IRRDecomposer().decompose(
            target_price=Decimal("133.1"),
            current_price=Decimal("100"),
            scenario=_scenario(cagr=Decimal("5")),
            canonical_state=_canonical(),
            horizon_years=3,
        )
        assert abs(result.total_p_a - Decimal("0.10")) < Decimal("0.001")

    def test_decomposition_sums_to_total(self) -> None:
        result = IRRDecomposer().decompose(
            target_price=Decimal("133.1"),
            current_price=Decimal("100"),
            scenario=_scenario(cagr=Decimal("5")),
            canonical_state=_canonical(),
        )
        # fundamental + rerating + dividend = total (Phase 1: dividend=0)
        assert (
            abs(
                result.fundamental_p_a
                + result.rerating_p_a
                + result.dividend_yield_p_a
                - result.total_p_a
            )
            < Decimal("0.0001")
        )

    def test_fundamental_equals_revenue_cagr(self) -> None:
        # revenue_cagr=5 → fundamental=0.05
        result = IRRDecomposer().decompose(
            target_price=Decimal("120"),
            current_price=Decimal("100"),
            scenario=_scenario(cagr=Decimal("5")),
            canonical_state=_canonical(),
        )
        assert result.fundamental_p_a == Decimal("0.05")

    def test_phase1_dividend_yield_zero(self) -> None:
        result = IRRDecomposer().decompose(
            target_price=Decimal("120"),
            current_price=Decimal("100"),
            scenario=_scenario(),
            canonical_state=_canonical(),
        )
        assert result.dividend_yield_p_a == Decimal("0")


class TestIRREdgeCases:
    def test_zero_current_price_raises(self) -> None:
        with pytest.raises(ValueError, match="current_price"):
            IRRDecomposer().decompose(
                target_price=Decimal("100"),
                current_price=Decimal("0"),
                scenario=_scenario(),
                canonical_state=_canonical(),
            )

    def test_zero_horizon_raises(self) -> None:
        with pytest.raises(ValueError, match="horizon_years"):
            IRRDecomposer().decompose(
                target_price=Decimal("120"),
                current_price=Decimal("100"),
                scenario=_scenario(),
                canonical_state=_canonical(),
                horizon_years=0,
            )

    def test_negative_upside_yields_negative_irr(self) -> None:
        result = IRRDecomposer().decompose(
            target_price=Decimal("80"),
            current_price=Decimal("100"),
            scenario=_scenario(),
            canonical_state=_canonical(),
        )
        assert result.total_p_a < Decimal("0")

    def test_no_cagr_fundamental_zero(self) -> None:
        scenario = Scenario(
            label="base",
            description="test",
            probability=Decimal("100"),
            horizon_years=3,
            drivers=ScenarioDrivers(),  # no drivers set
        )
        result = IRRDecomposer().decompose(
            target_price=Decimal("120"),
            current_price=Decimal("100"),
            scenario=scenario,
            canonical_state=_canonical(),
        )
        assert result.fundamental_p_a == Decimal("0")

    def test_describe(self) -> None:
        assert IRRDecomposer().describe() == {"engine": "IRRDecomposer"}
