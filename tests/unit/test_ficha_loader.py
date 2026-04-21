"""Unit tests for ficha.loader.FichaLoader."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_thesis_engine.ficha.loader import FichaBundle, FichaLoader
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
from portfolio_thesis_engine.schemas.ficha import Ficha
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
from portfolio_thesis_engine.storage.yaml_repo import (
    CompanyRepository,
    CompanyStateRepository,
    ValuationRepository,
)


def _identity() -> CompanyIdentity:
    return CompanyIdentity(
        ticker="1846.HK",
        name="EuroEyes",
        reporting_currency=Currency.HKD,
        profile=Profile.P1_INDUSTRIAL,
        fiscal_year_end_month=12,
        country_domicile="HK",
        exchange="HKEX",
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
            protocols_activated=[],
        ),
    )


def _valuation() -> ValuationSnapshot:
    now = datetime.now(UTC)
    return ValuationSnapshot(
        version=1,
        created_at=now,
        created_by="test",
        snapshot_id="snap-1",
        ticker="1846.HK",
        company_name="EuroEyes",
        profile=Profile.P1_INDUSTRIAL,
        valuation_date=now,
        based_on_extraction_id="ext-1",
        based_on_extraction_date=datetime(2024, 12, 31, tzinfo=UTC),
        market=MarketSnapshot(
            price=Decimal("10"),
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
            expected_value=Decimal("12"),
            expected_value_method_used="DCF",
            fair_value_range_low=Decimal("10"),
            fair_value_range_high=Decimal("14"),
            upside_pct=Decimal("20"),
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


def _ficha() -> Ficha:
    now = datetime.now(UTC)
    return Ficha(
        version=1,
        created_at=now,
        created_by="test",
        ticker="1846.HK",
        identity=_identity(),
        current_extraction_id="ext-1",
        current_valuation_snapshot_id="snap-1",
    )


# ======================================================================
# Fixtures
# ======================================================================


@pytest.fixture
def _repos(tmp_path: Path) -> tuple[CompanyRepository, CompanyStateRepository, ValuationRepository]:
    return (
        CompanyRepository(base_path=tmp_path),
        CompanyStateRepository(base_path=tmp_path),
        ValuationRepository(base_path=tmp_path),
    )


# ======================================================================
# 1. load()
# ======================================================================


class TestLoad:
    def test_empty_repos_yield_empty_bundle(
        self,
        _repos: tuple[CompanyRepository, CompanyStateRepository, ValuationRepository],
    ) -> None:
        loader = FichaLoader(*_repos)
        bundle = loader.load("1846.HK")
        assert bundle.ticker == "1846.HK"
        assert bundle.ficha is None
        assert bundle.canonical_state is None
        assert bundle.valuation_snapshot is None
        assert bundle.has_data is False

    def test_full_bundle(
        self,
        _repos: tuple[CompanyRepository, CompanyStateRepository, ValuationRepository],
    ) -> None:
        company_repo, state_repo, val_repo = _repos
        company_repo.save(_ficha())
        state_repo.save(_canonical())
        val_repo.save(_valuation())

        bundle = FichaLoader(*_repos).load("1846.HK")
        assert bundle.ficha is not None
        assert bundle.canonical_state is not None
        assert bundle.valuation_snapshot is not None
        assert bundle.has_data is True

    def test_partial_bundle_canonical_only(
        self,
        _repos: tuple[CompanyRepository, CompanyStateRepository, ValuationRepository],
    ) -> None:
        company_repo, state_repo, val_repo = _repos
        state_repo.save(_canonical())
        bundle = FichaLoader(*_repos).load("1846.HK")
        assert bundle.ficha is None
        assert bundle.canonical_state is not None
        assert bundle.has_data is True  # canonical_state is the threshold

    def test_ticker_normalisation(
        self,
        _repos: tuple[CompanyRepository, CompanyStateRepository, ValuationRepository],
    ) -> None:
        company_repo, state_repo, _ = _repos
        state_repo.save(_canonical())
        # Input "1846.HK" — normalised to 1846-HK on disk; load should
        # resolve both forms.
        assert FichaLoader(*_repos).load("1846.HK").canonical_state is not None
        assert FichaLoader(*_repos).load("1846-HK").canonical_state is not None


# ======================================================================
# 2. list_tickers()
# ======================================================================


class TestListTickers:
    def test_empty(
        self,
        _repos: tuple[CompanyRepository, CompanyStateRepository, ValuationRepository],
    ) -> None:
        assert FichaLoader(*_repos).list_tickers() == []

    def test_deduped_across_repos(
        self,
        _repos: tuple[CompanyRepository, CompanyStateRepository, ValuationRepository],
    ) -> None:
        company_repo, state_repo, val_repo = _repos
        company_repo.save(_ficha())
        state_repo.save(_canonical())
        val_repo.save(_valuation())
        # Same ticker in all three repos — de-duped to single entry.
        tickers = FichaLoader(*_repos).list_tickers()
        assert tickers == ["1846-HK"]

    def test_sorted(
        self,
        _repos: tuple[CompanyRepository, CompanyStateRepository, ValuationRepository],
    ) -> None:
        company_repo, state_repo, val_repo = _repos
        # Canonical only — we need a second ticker
        state_repo.save(_canonical())
        other = _canonical()
        other = other.model_copy(
            update={
                "identity": other.identity.model_copy(update={"ticker": "ABC"}),
            }
        )
        state_repo.save(other)
        tickers = FichaLoader(*_repos).list_tickers()
        assert tickers == sorted(tickers)


# ======================================================================
# 3. FichaBundle has_data semantics
# ======================================================================


class TestBundleHasData:
    def test_has_data_only_when_canonical_present(self) -> None:
        # Only ficha (no canonical) — can't render core views
        ficha_only = FichaBundle(
            ticker="X", ficha=_ficha(), canonical_state=None, valuation_snapshot=None
        )
        assert ficha_only.has_data is False

        canonical_only = FichaBundle(
            ticker="X", ficha=None, canonical_state=_canonical(), valuation_snapshot=None
        )
        assert canonical_only.has_data is True
