"""Shared pytest fixtures for Portfolio Thesis Engine tests.

Provides small reusable sample objects for each top-level schema so
tests focus on what they're verifying instead of constructor plumbing.
"""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from portfolio_thesis_engine.schemas.common import (
    ConfidenceTag,
    ConvictionLevel,
    Currency,
    FiscalPeriod,
    GuardrailStatus,
    Profile,
    Source,
)
from portfolio_thesis_engine.schemas.company import (
    AdjustmentsApplied,
    AnalysisDerived,
    BalanceSheetLine,
    CanonicalCompanyState,
    CapitalAllocationHistory,
    CashFlowLine,
    CompanyIdentity,
    IncomeStatementLine,
    InvestedCapital,
    KeyRatios,
    MethodologyMetadata,
    NOPATBridge,
    ReclassifiedStatements,
    ValidationResult,
    ValidationResults,
    VintageAndCascade,
)
from portfolio_thesis_engine.schemas.ficha import Ficha, Monitorable, ThesisStatement
from portfolio_thesis_engine.schemas.market_context import (
    MarketCatalyst,
    MarketContext,
    MarketDimension,
    MarketParticipant,
)
from portfolio_thesis_engine.schemas.peer import Peer, PeerExtractionLevel
from portfolio_thesis_engine.schemas.position import (
    Position,
    PositionCurrentState,
    PositionStatus,
    PositionTransaction,
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


@pytest.fixture
def sample_fiscal_period() -> FiscalPeriod:
    return FiscalPeriod(year=2024, label="FY2024")


@pytest.fixture
def sample_source() -> Source:
    return Source(
        document="Annual Report 2024",
        page=42,
        confidence=ConfidenceTag.REPORTED,
        url=None,
        accessed="2025-03-01",
    )


@pytest.fixture
def sample_identity() -> CompanyIdentity:
    return CompanyIdentity(
        ticker="ACME",
        isin="US0000000001",
        name="Acme Industrial plc",
        legal_name="Acme Industrial Corp.",
        reporting_currency=Currency.USD,
        profile=Profile.P1_INDUSTRIAL,
        sector_gics="Industrials",
        industry_gics="Machinery",
        fiscal_year_end_month=12,
        country_domicile="US",
        exchange="NYSE",
        shares_outstanding=Decimal("1000000"),
        market_contexts=["us_industrials"],
    )


@pytest.fixture
def sample_reclassified_statements(
    sample_fiscal_period: FiscalPeriod,
) -> ReclassifiedStatements:
    return ReclassifiedStatements(
        period=sample_fiscal_period,
        income_statement=[
            IncomeStatementLine(label="Revenue", value=Decimal("1000.00")),
            IncomeStatementLine(label="EBITA", value=Decimal("180.00")),
        ],
        balance_sheet=[
            BalanceSheetLine(
                label="Operating assets",
                value=Decimal("800.00"),
                category="operating_assets",
            ),
        ],
        cash_flow=[
            CashFlowLine(label="CFO", value=Decimal("150.00"), category="CFO"),
        ],
        bs_checksum_pass=True,
        is_checksum_pass=True,
        cf_checksum_pass=True,
    )


@pytest.fixture
def sample_company_state(
    sample_identity: CompanyIdentity,
    sample_reclassified_statements: ReclassifiedStatements,
    sample_fiscal_period: FiscalPeriod,
) -> CanonicalCompanyState:
    return CanonicalCompanyState(
        extraction_id="ext_2024_12_31_acme_001",
        extraction_date=datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
        as_of_date="2024-12-31",
        identity=sample_identity,
        reclassified_statements=[sample_reclassified_statements],
        adjustments=AdjustmentsApplied(),
        analysis=AnalysisDerived(
            invested_capital_by_period=[
                InvestedCapital(
                    period=sample_fiscal_period,
                    operating_assets=Decimal("800.00"),
                    operating_liabilities=Decimal("200.00"),
                    invested_capital=Decimal("600.00"),
                    financial_assets=Decimal("50.00"),
                    financial_liabilities=Decimal("250.00"),
                    equity_claims=Decimal("400.00"),
                    cross_check_residual=Decimal("0.00"),
                )
            ],
            nopat_bridge_by_period=[
                NOPATBridge(
                    period=sample_fiscal_period,
                    ebitda=Decimal("180.00"),
                    operating_taxes=Decimal("45.00"),
                    nopat=Decimal("135.00"),
                    financial_income=Decimal("2.00"),
                    financial_expense=Decimal("15.00"),
                    non_operating_items=Decimal("3.00"),
                    reported_net_income=Decimal("125.00"),
                )
            ],
            ratios_by_period=[
                KeyRatios(
                    period=sample_fiscal_period,
                    roic=Decimal("22.5"),
                    operating_margin=Decimal("18.0"),
                )
            ],
            capital_allocation=CapitalAllocationHistory(
                periods=[sample_fiscal_period],
                cfo_total=Decimal("150.00"),
                capex_total=Decimal("40.00"),
                acquisitions_total=Decimal("0.00"),
                dividends_total=Decimal("30.00"),
                buybacks_total=Decimal("20.00"),
                debt_change=Decimal("-10.00"),
                equity_issuance=Decimal("0.00"),
            ),
        ),
        validation=ValidationResults(
            universal_checksums=[
                ValidationResult(
                    check_id="V.1",
                    name="BS checksum",
                    status="PASS",
                    detail="Balances match.",
                )
            ],
            profile_specific_checksums=[],
            confidence_rating="HIGH",
        ),
        vintage=VintageAndCascade(),
        methodology=MethodologyMetadata(
            extraction_system_version="1.4",
            profile_applied=Profile.P1_INDUSTRIAL,
            protocols_activated=[],
            total_api_cost_usd=Decimal("3.25"),
        ),
    )


@pytest.fixture
def sample_scenario() -> Scenario:
    return Scenario(
        label="base",
        description="Base case: steady growth, margins stable",
        probability=Decimal("50"),
        horizon_years=5,
        drivers=ScenarioDrivers(
            revenue_cagr=Decimal("5.0"),
            terminal_growth=Decimal("2.5"),
            terminal_margin=Decimal("18.0"),
            terminal_roic=Decimal("20.0"),
            terminal_wacc=Decimal("8.5"),
        ),
        targets={"DCF": Decimal("120.00")},
        irr_3y=Decimal("12.0"),
        upside_pct=Decimal("15.0"),
    )


@pytest.fixture
def sample_valuation_snapshot(sample_scenario: Scenario) -> ValuationSnapshot:
    return ValuationSnapshot(
        version=1,
        created_at=datetime(2025, 1, 20, 9, 0, tzinfo=UTC),
        created_by="claude-sonnet-4-6",
        snapshot_id="val_2025_01_20_acme_001",
        ticker="ACME",
        company_name="Acme Industrial plc",
        profile=Profile.P1_INDUSTRIAL,
        valuation_date=datetime(2025, 1, 20, 9, 0, tzinfo=UTC),
        based_on_extraction_id="ext_2024_12_31_acme_001",
        based_on_extraction_date=datetime(2025, 1, 15, 10, 0, tzinfo=UTC),
        market=MarketSnapshot(
            price=Decimal("105.50"),
            price_date="2025-01-20",
            shares_outstanding=Decimal("1000000"),
            market_cap=Decimal("105500000"),
            cost_of_equity=Decimal("9.0"),
            wacc=Decimal("8.5"),
            currency=Currency.USD,
        ),
        scenarios=[sample_scenario],
        weighted=WeightedOutputs(
            expected_value=Decimal("118.00"),
            expected_value_method_used="DCF",
            fair_value_range_low=Decimal("95.00"),
            fair_value_range_high=Decimal("140.00"),
            upside_pct=Decimal("11.85"),
            asymmetry_ratio=Decimal("2.1"),
        ),
        conviction=Conviction(
            forecast=ConvictionLevel.HIGH,
            valuation=ConvictionLevel.MEDIUM,
            asymmetry=ConvictionLevel.HIGH,
            timing_risk=ConvictionLevel.LOW,
            liquidity_risk=ConvictionLevel.LOW,
            governance_risk=ConvictionLevel.LOW,
        ),
        guardrails=GuardrailsStatus(
            categories=[
                GuardrailCategory(
                    category="D_valuation",
                    total=10,
                    passed=9,
                    warned=1,
                    failed=0,
                    skipped=0,
                )
            ],
            overall=GuardrailStatus.WARN,
        ),
        forecast_system_version="2.0",
    )


@pytest.fixture
def sample_position() -> Position:
    return Position(
        ticker="ACME",
        company_name="Acme Industrial plc",
        status=PositionStatus.ACTIVE,
        currency=Currency.USD,
        transactions=[
            PositionTransaction(
                date="2024-06-01",
                type="open",
                quantity=Decimal("100"),
                price=Decimal("90.00"),
                currency=Currency.USD,
                rationale="Initial entry near valuation range low.",
            )
        ],
        current=PositionCurrentState(
            quantity=Decimal("100"),
            avg_cost=Decimal("90.00"),
            last_price=Decimal("105.50"),
            last_price_date="2025-01-20",
            market_value=Decimal("10550.00"),
            unrealized_pnl=Decimal("1550.00"),
            unrealized_pnl_pct=Decimal("17.22"),
            weight_pct=Decimal("3.5"),
        ),
        tags=["industrial", "mid-cap"],
    )


@pytest.fixture
def sample_peer() -> Peer:
    return Peer(
        ticker="PEER",
        name="Peer Industrial Inc",
        profile=Profile.P1_INDUSTRIAL,
        currency=Currency.USD,
        exchange="NYSE",
        peer_of_ticker="ACME",
        extraction_level=PeerExtractionLevel.LEVEL_C,
        last_update=datetime(2025, 1, 10, 12, 0, tzinfo=UTC),
        market_data={"pe": Decimal("18.5"), "ev_ebitda": Decimal("12.0")},
        reported_metrics={"revenue": Decimal("2500.00")},
    )


@pytest.fixture
def sample_market_context() -> MarketContext:
    return MarketContext(
        cluster_id="us_industrials",
        name="US Industrials",
        description="Mid-cap US industrial machinery companies.",
        companies=["ACME", "PEER"],
        dimensions=[
            MarketDimension(
                name="North America",
                description="Primary market",
                total_market_value=Decimal("50000.00"),
                unit="USD_m",
                year=2024,
                cagr=Decimal("4.5"),
                participants=[
                    MarketParticipant(
                        ticker="ACME",
                        name="Acme Industrial plc",
                        market_share_pct=Decimal("2.5"),
                        position="challenger",
                    )
                ],
            )
        ],
        catalysts=[
            MarketCatalyst(
                date_approx="H2 2025",
                event="Infrastructure bill renewal",
                impact_direction="positive",
                affected_companies=["ACME"],
            )
        ],
        last_updated=datetime(2025, 1, 15, 12, 0, tzinfo=UTC),
    )


@pytest.fixture
def sample_ficha(sample_identity: CompanyIdentity, sample_position: Position) -> Ficha:
    return Ficha(
        ticker="ACME",
        identity=sample_identity,
        thesis=ThesisStatement(
            text="Acme is a best-in-class industrial compounder.",
            written_at=datetime(2025, 1, 20, 9, 0, tzinfo=UTC),
        ),
        current_extraction_id="ext_2024_12_31_acme_001",
        current_valuation_snapshot_id="val_2025_01_20_acme_001",
        position=sample_position,
        monitorables=[
            Monitorable(
                metric="Operating margin",
                on_track_condition=">= 17%",
                warning_condition="< 15%",
                last_observed="18.0%",
                last_observed_date="2024-12-31",
                status="on_track",
            )
        ],
        tags=["industrial"],
        market_contexts=["us_industrials"],
    )
