"""Unit tests for ficha.composer.FichaComposer."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_thesis_engine.ficha.composer import FichaComposer
from portfolio_thesis_engine.schemas.common import (
    ConvictionLevel,
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
    Conviction,
    GuardrailCategory,
    GuardrailsStatus,
    MarketSnapshot,
    Scenario,
    ScenarioDrivers,
    ValuationSnapshot,
    WeightedOutputs,
)
from portfolio_thesis_engine.storage.yaml_repo import CompanyRepository


def _identity() -> CompanyIdentity:
    return CompanyIdentity(
        ticker="1846.HK",
        name="EuroEyes",
        reporting_currency=Currency.HKD,
        profile=Profile.P1_INDUSTRIAL,
        fiscal_year_end_month=12,
        country_domicile="HK",
        exchange="HKEX",
        market_contexts=["eu-healthcare"],
    )


def _canonical() -> CanonicalCompanyState:
    period = FiscalPeriod(year=2024, label="FY2024")
    return CanonicalCompanyState(
        extraction_id="ext-1",
        extraction_date=datetime(2024, 12, 31, tzinfo=UTC),
        as_of_date="2024-12-31",
        identity=_identity(),
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
            protocols_activated=["A", "B", "C"],
        ),
        source_documents=["doc-1"],
    )


def _valuation_snapshot(valuation_date: datetime | None = None) -> ValuationSnapshot:
    vd = valuation_date or datetime.now(UTC)
    return ValuationSnapshot(
        version=1,
        created_at=vd,
        created_by="test",
        snapshot_id="snap-1",
        ticker="1846.HK",
        company_name="EuroEyes",
        profile=Profile.P1_INDUSTRIAL,
        valuation_date=vd,
        based_on_extraction_id="ext-1",
        based_on_extraction_date=datetime(2024, 12, 31, tzinfo=UTC),
        market=MarketSnapshot(
            price=Decimal("12.30"),
            price_date="2024-12-31",
            cost_of_equity=Decimal("9"),
            wacc=Decimal("8"),
            currency=Currency.HKD,
        ),
        scenarios=[
            Scenario(
                label="base",
                description="base",
                probability=Decimal("100"),
                horizon_years=3,
                drivers=ScenarioDrivers(),
            )
        ],
        weighted=WeightedOutputs(
            expected_value=Decimal("15"),
            expected_value_method_used="DCF",
            fair_value_range_low=Decimal("10"),
            fair_value_range_high=Decimal("20"),
            upside_pct=Decimal("22"),
            asymmetry_ratio=Decimal("2"),
        ),
        conviction=Conviction(
            forecast=ConvictionLevel.MEDIUM,
            valuation=ConvictionLevel.MEDIUM,
            asymmetry=ConvictionLevel.MEDIUM,
            timing_risk=ConvictionLevel.MEDIUM,
            liquidity_risk=ConvictionLevel.MEDIUM,
            governance_risk=ConvictionLevel.MEDIUM,
        ),
        guardrails=GuardrailsStatus(
            categories=[GuardrailCategory(category="x", total=0, passed=0, warned=0, failed=0, skipped=0)],
            overall=GuardrailStatus.PASS,
        ),
        forecast_system_version="test",
    )


# ======================================================================
# 1. Composition
# ======================================================================


class TestCompose:
    def test_identity_propagates(self) -> None:
        ficha = FichaComposer().compose(_canonical(), _valuation_snapshot())
        assert ficha.ticker == "1846.HK"
        assert ficha.identity.ticker == "1846.HK"
        assert ficha.identity.name == "EuroEyes"

    def test_current_ids_set(self) -> None:
        ficha = FichaComposer().compose(_canonical(), _valuation_snapshot())
        assert ficha.current_extraction_id == "ext-1"
        assert ficha.current_valuation_snapshot_id == "snap-1"

    def test_conviction_from_snapshot(self) -> None:
        ficha = FichaComposer().compose(_canonical(), _valuation_snapshot())
        assert ficha.conviction is not None
        assert ficha.conviction.valuation == ConvictionLevel.MEDIUM

    def test_market_contexts_from_identity(self) -> None:
        ficha = FichaComposer().compose(_canonical(), _valuation_snapshot())
        assert ficha.market_contexts == ["eu-healthcare"]

    def test_no_valuation_leaves_fields_empty(self) -> None:
        ficha = FichaComposer().compose(_canonical(), None)
        assert ficha.conviction is None
        assert ficha.current_valuation_snapshot_id is None
        assert ficha.snapshot_age_days is None
        assert ficha.is_stale is False

    def test_thesis_position_monitorables_are_stubs(self) -> None:
        ficha = FichaComposer().compose(_canonical(), _valuation_snapshot())
        assert ficha.thesis is None
        assert ficha.position is None
        assert ficha.monitorables == []


# ======================================================================
# 2. Staleness computation
# ======================================================================


class TestStaleness:
    def test_fresh_snapshot_not_stale(self) -> None:
        now = datetime.now(UTC)
        ficha = FichaComposer().compose(_canonical(), _valuation_snapshot(now), as_of=now)
        assert ficha.snapshot_age_days == 0
        assert ficha.is_stale is False

    def test_91_day_snapshot_is_stale(self) -> None:
        now = datetime(2025, 1, 1, tzinfo=UTC)
        vd = now - timedelta(days=91)
        ficha = FichaComposer().compose(_canonical(), _valuation_snapshot(vd), as_of=now)
        assert ficha.snapshot_age_days == 91
        assert ficha.is_stale is True

    def test_90_day_snapshot_at_threshold_not_stale(self) -> None:
        now = datetime(2025, 1, 1, tzinfo=UTC)
        vd = now - timedelta(days=90)
        ficha = FichaComposer().compose(_canonical(), _valuation_snapshot(vd), as_of=now)
        assert ficha.snapshot_age_days == 90
        assert ficha.is_stale is False

    def test_custom_threshold(self) -> None:
        now = datetime(2025, 1, 1, tzinfo=UTC)
        vd = now - timedelta(days=8)
        composer = FichaComposer(stale_threshold_days=7)
        ficha = composer.compose(_canonical(), _valuation_snapshot(vd), as_of=now)
        assert ficha.snapshot_age_days == 8
        assert ficha.is_stale is True

    def test_negative_age_clamped_at_zero(self) -> None:
        # Clock-skew: valuation_date in the future.
        now = datetime(2025, 1, 1, tzinfo=UTC)
        future = now + timedelta(days=3)
        ficha = FichaComposer().compose(_canonical(), _valuation_snapshot(future), as_of=now)
        assert ficha.snapshot_age_days == 0
        assert ficha.is_stale is False

    def test_naive_valuation_date_coerced(self) -> None:
        naive = datetime(2024, 6, 1)
        snap = _valuation_snapshot(naive)
        now = datetime(2025, 1, 1, tzinfo=UTC)
        ficha = FichaComposer().compose(_canonical(), snap, as_of=now)
        # Should not raise; age computed after tz normalisation
        assert ficha.snapshot_age_days is not None
        assert ficha.snapshot_age_days > 200

    def test_threshold_validation(self) -> None:
        with pytest.raises(ValueError, match="stale_threshold_days"):
            FichaComposer(stale_threshold_days=0)


# ======================================================================
# 3. compose_and_save
# ======================================================================


class TestComposeAndSave:
    def test_persists_via_company_repo(self, tmp_path: Path) -> None:
        repo = CompanyRepository(base_path=tmp_path)
        composer = FichaComposer()
        ficha = composer.compose_and_save(
            _canonical(),
            _valuation_snapshot(),
            repo,
        )
        loaded = repo.get("1846.HK")
        assert loaded is not None
        assert loaded.ticker == "1846.HK"
        assert loaded.current_extraction_id == ficha.current_extraction_id
