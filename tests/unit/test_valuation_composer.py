"""Unit tests for valuation.composer.ValuationComposer."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from portfolio_thesis_engine.schemas.common import (
    Currency,
    FiscalPeriod,
    GuardrailStatus,
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
from portfolio_thesis_engine.schemas.valuation import (
    MarketSnapshot,
    Scenario,
    ScenarioDrivers,
    ValuationSnapshot,
)
from portfolio_thesis_engine.valuation.composer import ValuationComposer


def _canonical() -> CanonicalCompanyState:
    period = FiscalPeriod(year=2024, label="FY2024")
    return CanonicalCompanyState(
        extraction_id="ext1",
        extraction_date=datetime(2024, 12, 31, tzinfo=UTC),
        as_of_date="2024-12-31",
        identity=CompanyIdentity(
            ticker="1846.HK",
            name="EuroEyes",
            reporting_currency=Currency.HKD,
            profile=Profile.P1_INDUSTRIAL,
            fiscal_year_end_month=12,
            country_domicile="HK",
            exchange="HKEX",
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


def _scenario(
    label: str,
    probability: Decimal,
    per_share: Decimal,
) -> Scenario:
    return Scenario(
        label=label,
        description=label,
        probability=probability,
        horizon_years=3,
        drivers=ScenarioDrivers(
            revenue_cagr=Decimal("5"),
            terminal_growth=Decimal("2"),
            terminal_margin=Decimal("18"),
        ),
        targets={"dcf_fcff_per_share": per_share, "equity_value": per_share * Decimal("1000")},
        irr_3y=Decimal("8"),
        upside_pct=Decimal("5"),
    )


def _market(price: Decimal = Decimal("10")) -> MarketSnapshot:
    return MarketSnapshot(
        price=price,
        price_date="2024-12-31",
        shares_outstanding=Decimal("1000"),
        market_cap=price * Decimal("1000"),
        cost_of_equity=Decimal("9"),
        wacc=Decimal("8"),
        currency=Currency.HKD,
    )


# ======================================================================
# Weighted outputs
# ======================================================================


class TestWeightedOutputs:
    def test_expected_value_probability_weighted(self) -> None:
        scenarios = [
            _scenario("bear", Decimal("25"), Decimal("8")),
            _scenario("base", Decimal("50"), Decimal("12")),
            _scenario("bull", Decimal("25"), Decimal("18")),
        ]
        snap = ValuationComposer().compose(_canonical(), scenarios, _market(Decimal("10")))
        # E[V] = 0.25*8 + 0.50*12 + 0.25*18 = 12.5
        assert abs(snap.weighted.expected_value - Decimal("12.5")) < Decimal("0.001")

    def test_fair_value_range(self) -> None:
        scenarios = [
            _scenario("bear", Decimal("25"), Decimal("8")),
            _scenario("base", Decimal("50"), Decimal("12")),
            _scenario("bull", Decimal("25"), Decimal("18")),
        ]
        snap = ValuationComposer().compose(_canonical(), scenarios, _market())
        assert snap.weighted.fair_value_range_low == Decimal("8")
        assert snap.weighted.fair_value_range_high == Decimal("18")

    def test_upside_pct_vs_current_price(self) -> None:
        scenarios = [
            _scenario("bear", Decimal("25"), Decimal("8")),
            _scenario("base", Decimal("50"), Decimal("12")),
            _scenario("bull", Decimal("25"), Decimal("18")),
        ]
        snap = ValuationComposer().compose(_canonical(), scenarios, _market(Decimal("10")))
        # (12.5 - 10) / 10 * 100 = 25%
        assert abs(snap.weighted.upside_pct - Decimal("25")) < Decimal("0.001")

    def test_asymmetry_ratio(self) -> None:
        scenarios = [
            _scenario("bear", Decimal("25"), Decimal("8")),
            _scenario("base", Decimal("50"), Decimal("12")),
            _scenario("bull", Decimal("25"), Decimal("18")),
        ]
        snap = ValuationComposer().compose(_canonical(), scenarios, _market(Decimal("10")))
        # upside (18-10)=8, downside (10-8)=2 → 4.0
        assert abs(snap.weighted.asymmetry_ratio - Decimal("4")) < Decimal("0.001")

    def test_weighted_irr(self) -> None:
        scenarios = [
            _scenario("bear", Decimal("50"), Decimal("8")),
            _scenario("base", Decimal("50"), Decimal("12")),
        ]
        snap = ValuationComposer().compose(_canonical(), scenarios, _market())
        # All scenarios have irr_3y=8, weighted avg = 8
        assert snap.weighted.weighted_irr_3y == Decimal("8")

    def test_entire_range_upside_asymmetry_large(self) -> None:
        # Bear above current → downside = 0 → ratio clamps to 999
        scenarios = [
            _scenario("bear", Decimal("25"), Decimal("20")),
            _scenario("base", Decimal("50"), Decimal("30")),
            _scenario("bull", Decimal("25"), Decimal("40")),
        ]
        snap = ValuationComposer().compose(_canonical(), scenarios, _market(Decimal("10")))
        assert snap.weighted.asymmetry_ratio == Decimal("999")


# ======================================================================
# Degenerate / edge cases
# ======================================================================


class TestEdgeCases:
    def test_no_scenarios_raises(self) -> None:
        with pytest.raises(ValueError, match="at least one scenario"):
            ValuationComposer().compose(_canonical(), [], _market())

    def test_no_per_share_targets_falls_back_to_price(self) -> None:
        # Scenario without dcf_fcff_per_share target
        scenario = Scenario(
            label="base",
            description="x",
            probability=Decimal("100"),
            horizon_years=3,
            drivers=ScenarioDrivers(),
            targets={},
        )
        snap = ValuationComposer().compose(_canonical(), [scenario], _market(Decimal("10")))
        # Falls back to current price
        assert snap.weighted.expected_value == Decimal("10")
        assert snap.weighted.upside_pct == Decimal("0")


# ======================================================================
# Snapshot shape
# ======================================================================


class TestValuationSnapshot:
    def test_snapshot_builds_and_validates(self) -> None:
        scenarios = [
            _scenario("bear", Decimal("25"), Decimal("8")),
            _scenario("base", Decimal("50"), Decimal("12")),
            _scenario("bull", Decimal("25"), Decimal("18")),
        ]
        snap = ValuationComposer().compose(_canonical(), scenarios, _market(Decimal("10")))
        assert isinstance(snap, ValuationSnapshot)
        assert snap.ticker == "1846.HK"
        assert snap.profile == Profile.P1_INDUSTRIAL
        assert snap.based_on_extraction_id == "ext1"
        assert len(snap.scenarios) == 3
        assert snap.forecast_system_version == "phase1-sprint9"
        assert snap.guardrails.overall == GuardrailStatus.PASS

    def test_yaml_roundtrip(self) -> None:
        scenarios = [
            _scenario("base", Decimal("100"), Decimal("12")),
        ]
        snap = ValuationComposer().compose(_canonical(), scenarios, _market())
        payload = snap.to_yaml()
        round_tripped = ValuationSnapshot.from_yaml(payload)
        assert round_tripped.ticker == snap.ticker
        assert round_tripped.weighted.expected_value == snap.weighted.expected_value
