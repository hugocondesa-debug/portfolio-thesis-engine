"""Unit tests for the Streamlit Phase 1 Ficha UI.

Uses Streamlit's own :class:`AppTest` harness to render the script
without binding to a network port. Two flavours:

- **Empty-state tests**: freshly monkey-patched repositories return
  nothing; the UI should render the "no companies processed yet"
  message.
- **Populated-state tests**: stub repositories return a realistic
  :class:`FichaBundle` and the UI should render every section.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from portfolio_thesis_engine import __version__
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
    BalanceSheetLine,
    CanonicalCompanyState,
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

_APP_PATH = "src/portfolio_thesis_engine/ui/app.py"


# ----------------------------------------------------------------------
# Builders for the populated-state bundle
# ----------------------------------------------------------------------
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


def _canonical() -> CanonicalCompanyState:
    period = FiscalPeriod(year=2024, label="FY2024")
    return CanonicalCompanyState(
        extraction_id="1846-HK_FY2024_demo",
        extraction_date=datetime(2024, 12, 31, tzinfo=UTC),
        as_of_date="2024-12-31",
        identity=_identity(),
        reclassified_statements=[
            ReclassifiedStatements(
                period=period,
                income_statement=[
                    IncomeStatementLine(label="Revenue", value=Decimal("580")),
                    IncomeStatementLine(label="Operating income", value=Decimal("110")),
                    IncomeStatementLine(label="Net income", value=Decimal("75")),
                ],
                balance_sheet=[
                    BalanceSheetLine(label="Cash", value=Decimal("450"), category="cash"),
                    BalanceSheetLine(label="PP&E", value=Decimal("950"), category="operating_assets"),
                    BalanceSheetLine(
                        label="Debt", value=Decimal("580"), category="financial_liabilities"
                    ),
                    BalanceSheetLine(label="Equity", value=Decimal("1900"), category="equity"),
                ],
                cash_flow=[
                    CashFlowLine(label="CFO", value=Decimal("135"), category="cfo"),
                    CashFlowLine(label="CapEx", value=Decimal("-75"), category="capex"),
                ],
                bs_checksum_pass=True,
                is_checksum_pass=True,
                cf_checksum_pass=True,
            )
        ],
        adjustments=AdjustmentsApplied(),
        analysis=AnalysisDerived(
            invested_capital_by_period=[
                InvestedCapital(
                    period=period,
                    operating_assets=Decimal("950"),
                    operating_liabilities=Decimal("100"),
                    invested_capital=Decimal("850"),
                    financial_assets=Decimal("450"),
                    financial_liabilities=Decimal("580"),
                    equity_claims=Decimal("1900"),
                    cross_check_residual=Decimal("0"),
                )
            ],
            nopat_bridge_by_period=[
                NOPATBridge(
                    period=period,
                    ebitda=Decimal("130"),
                    operating_taxes=Decimal("28"),
                    nopat=Decimal("102"),
                    financial_income=Decimal("4"),
                    financial_expense=Decimal("18"),
                    non_operating_items=Decimal("0"),
                    reported_net_income=Decimal("75"),
                )
            ],
            ratios_by_period=[
                KeyRatios(
                    period=period,
                    roic=Decimal("12"),
                    roe=Decimal("4"),
                    operating_margin=Decimal("18.97"),
                    ebitda_margin=Decimal("22.4"),
                    net_debt_ebitda=Decimal("1.0"),
                    capex_revenue=Decimal("12.9"),
                )
            ],
        ),
        validation=ValidationResults(
            universal_checksums=[
                ValidationResult(
                    check_id="V.sprint7",
                    name="Placeholder",
                    status="PASS",
                    detail="ok",
                )
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
    )


def _valuation() -> ValuationSnapshot:
    now = datetime.now(UTC)
    scenario = Scenario(
        label="base",
        description="Base case",
        probability=Decimal("50"),
        horizon_years=3,
        drivers=ScenarioDrivers(
            revenue_cagr=Decimal("8"),
            terminal_growth=Decimal("2.5"),
            terminal_margin=Decimal("18"),
        ),
        targets={"dcf_fcff_per_share": Decimal("15"), "equity_value": Decimal("3000")},
        irr_3y=Decimal("8"),
        irr_decomposition={"fundamental": Decimal("4"), "rerating": Decimal("4"), "dividend": Decimal("0")},
        upside_pct=Decimal("22"),
    )
    return ValuationSnapshot(
        version=1,
        created_at=now,
        created_by="test",
        snapshot_id="demo-snap-1",
        ticker="1846.HK",
        company_name="EuroEyes Medical Group",
        profile=Profile.P1_INDUSTRIAL,
        valuation_date=now,
        based_on_extraction_id="1846-HK_FY2024_demo",
        based_on_extraction_date=datetime(2024, 12, 31, tzinfo=UTC),
        market=MarketSnapshot(
            price=Decimal("12.30"),
            price_date="2024-12-31",
            shares_outstanding=Decimal("200000000"),
            market_cap=Decimal("2460000000"),
            cost_of_equity=Decimal("9"),
            wacc=Decimal("8"),
            currency=Currency.HKD,
        ),
        scenarios=[scenario],
        weighted=WeightedOutputs(
            expected_value=Decimal("15"),
            expected_value_method_used="DCF_FCFF",
            fair_value_range_low=Decimal("8"),
            fair_value_range_high=Decimal("18"),
            upside_pct=Decimal("22"),
            asymmetry_ratio=Decimal("2.5"),
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
            categories=[
                GuardrailCategory(
                    category="valuation", total=0, passed=0, warned=0, failed=0, skipped=0
                )
            ],
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
        thesis=None,
        current_extraction_id="1846-HK_FY2024_demo",
        current_valuation_snapshot_id="demo-snap-1",
        position=None,
        conviction=Conviction(
            forecast=ConvictionLevel.MEDIUM,
            valuation=ConvictionLevel.MEDIUM,
            asymmetry=ConvictionLevel.MEDIUM,
            timing_risk=ConvictionLevel.MEDIUM,
            liquidity_risk=ConvictionLevel.MEDIUM,
            governance_risk=ConvictionLevel.MEDIUM,
        ),
        snapshot_age_days=0,
        is_stale=False,
    )


def _populate_repos(base: Path) -> None:
    """Write a realistic ficha + canonical state + valuation snapshot
    into ``base`` so the UI's real :class:`FichaLoader` picks them up."""
    from portfolio_thesis_engine.storage.yaml_repo import (
        CompanyRepository,
        CompanyStateRepository,
        ValuationRepository,
    )

    CompanyStateRepository(base_path=base).save(_canonical())
    ValuationRepository(base_path=base).save(_valuation())
    CompanyRepository(base_path=base).save(_ficha())


# ----------------------------------------------------------------------
# Fixtures — isolated data_dir per test
# ----------------------------------------------------------------------
@pytest.fixture(autouse=True)
def _isolated_data_dir(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(
        "portfolio_thesis_engine.shared.config.settings.data_dir", data_dir
    )
    return data_dir


# ======================================================================
# 1. Empty state
# ======================================================================


class TestEmptyState:
    def test_no_exception(self) -> None:
        at = AppTest.from_file(_APP_PATH)
        at.run()
        assert len(at.exception) == 0, [e.value for e in at.exception]

    def test_empty_state_info_shown(self) -> None:
        at = AppTest.from_file(_APP_PATH)
        at.run()
        info_values = [i.value for i in at.info]
        assert any("No companies processed yet" in v for v in info_values)

    def test_no_ticker_selector(self) -> None:
        at = AppTest.from_file(_APP_PATH)
        at.run()
        assert len(at.selectbox) == 0


# ======================================================================
# 2. Populated state — real repositories under tmp_path
# ======================================================================


class TestPopulatedState:
    def test_no_exception(self, _isolated_data_dir: Path) -> None:
        _populate_repos(_isolated_data_dir / "yamls" / "companies")
        at = AppTest.from_file(_APP_PATH)
        at.run()
        assert len(at.exception) == 0, [e.value for e in at.exception]

    def test_title_present(self, _isolated_data_dir: Path) -> None:
        _populate_repos(_isolated_data_dir / "yamls" / "companies")
        at = AppTest.from_file(_APP_PATH)
        at.run()
        assert any(t.value == "Portfolio Thesis Engine" for t in at.title)

    def test_ticker_selectbox_offers_processed_ticker(self, _isolated_data_dir: Path) -> None:
        _populate_repos(_isolated_data_dir / "yamls" / "companies")
        at = AppTest.from_file(_APP_PATH)
        at.run()
        assert len(at.selectbox) == 1
        # Ticker is stored normalised (1846.HK → 1846-HK) on disk
        assert "1846-HK" in list(at.selectbox[0].options) or "1846.HK" in list(
            at.selectbox[0].options
        )

    def test_all_five_sections_rendered(self, _isolated_data_dir: Path) -> None:
        _populate_repos(_isolated_data_dir / "yamls" / "companies")
        at = AppTest.from_file(_APP_PATH)
        at.run()
        subheaders = [sh.value for sh in at.subheader]
        assert "Identity" in subheaders
        assert "Valuation" in subheaders
        assert "Scenarios" in subheaders
        assert "Financials" in subheaders
        assert "Guardrails" in subheaders

    def test_sidebar_nav_disabled(self) -> None:
        at = AppTest.from_file(_APP_PATH)
        at.run()
        nav = at.sidebar.radio[0]
        assert nav.disabled is True
        assert list(nav.options) == ["Ficha", "Positions", "Watchlist", "Settings"]

    def test_version_caption_in_sidebar(self) -> None:
        at = AppTest.from_file(_APP_PATH)
        at.run()
        caps = [c.value for c in at.sidebar.caption]
        assert any(__version__ in c for c in caps)
