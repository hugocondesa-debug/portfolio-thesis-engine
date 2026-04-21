"""Unit tests for ``pte show``."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from typer.testing import CliRunner

from portfolio_thesis_engine.cli.app import app
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

runner = CliRunner()


def _identity() -> CompanyIdentity:
    return CompanyIdentity(
        ticker="1846.HK",
        name="EuroEyes",
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
                income_statement=[IncomeStatementLine(label="Revenue", value=Decimal("580"))],
                balance_sheet=[
                    BalanceSheetLine(label="Cash", value=Decimal("450"), category="cash")
                ],
                cash_flow=[CashFlowLine(label="CFO", value=Decimal("135"), category="cfo")],
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
            ratios_by_period=[KeyRatios(period=period, roic=Decimal("12"))],
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
    )


def _valuation() -> ValuationSnapshot:
    now = datetime.now(UTC)
    return ValuationSnapshot(
        version=1,
        created_at=now,
        created_by="test",
        snapshot_id="demo-snap-1",
        ticker="1846.HK",
        company_name="EuroEyes",
        profile=Profile.P1_INDUSTRIAL,
        valuation_date=now,
        based_on_extraction_id="1846-HK_FY2024_demo",
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
                drivers=ScenarioDrivers(
                    revenue_cagr=Decimal("8"),
                    terminal_margin=Decimal("18"),
                    terminal_growth=Decimal("2"),
                ),
                targets={"dcf_fcff_per_share": Decimal("15")},
                irr_3y=Decimal("8"),
                upside_pct=Decimal("22"),
            )
        ],
        weighted=WeightedOutputs(
            expected_value=Decimal("15"),
            expected_value_method_used="DCF_FCFF",
            fair_value_range_low=Decimal("8"),
            fair_value_range_high=Decimal("18"),
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
            categories=[
                GuardrailCategory(
                    category="x", total=0, passed=0, warned=0, failed=0, skipped=0
                )
            ],
            overall=GuardrailStatus.PASS,
        ),
        forecast_system_version="test",
    )


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    data_dir = tmp_path / "data"
    monkeypatch.setattr(
        "portfolio_thesis_engine.shared.config.settings.data_dir", data_dir
    )
    return data_dir


def _populate(data_dir: Path) -> None:
    base = data_dir / "yamls" / "companies"
    CompanyStateRepository(base_path=base).save(_canonical())
    ValuationRepository(base_path=base).save(_valuation())
    FichaComposer().compose_and_save(
        _canonical(),
        _valuation(),
        CompanyRepository(base_path=base),
    )


# ======================================================================
# 1. Happy paths
# ======================================================================


class TestShowHappy:
    def test_rich_output(self, _isolated: Path) -> None:
        _populate(_isolated)
        result = runner.invoke(app, ["show", "1846.HK"])
        assert result.exit_code == 0, result.output
        assert "EuroEyes" in result.output
        assert "Identity" in result.output
        assert "Valuation" in result.output
        assert "Scenarios" in result.output

    def test_json_output(self, _isolated: Path) -> None:
        _populate(_isolated)
        result = runner.invoke(app, ["show", "1846.HK", "--json"])
        assert result.exit_code == 0
        # Rich's print_json adds ANSI-like padding; strip to find the JSON.
        # The output should contain valid JSON — parse the blob.
        start = result.output.find("{")
        end = result.output.rfind("}")
        assert start >= 0 and end > start
        payload = json.loads(result.output[start : end + 1])
        assert payload["ticker"] == "1846.HK"
        assert payload["valuation"]["expected_value"] == "15"

    def test_staleness_line_shown(self, _isolated: Path) -> None:
        _populate(_isolated)
        result = runner.invoke(app, ["show", "1846.HK"])
        assert "Valuation age" in result.output


# ======================================================================
# 2. Missing data
# ======================================================================


class TestShowMissing:
    def test_no_data_exits_1(self, _isolated: Path) -> None:
        result = runner.invoke(app, ["show", "1846.HK"])
        assert result.exit_code == 1
        assert "No data" in result.output

    def test_canonical_only_still_renders(self, _isolated: Path) -> None:
        base = _isolated / "yamls" / "companies"
        CompanyStateRepository(base_path=base).save(_canonical())
        result = runner.invoke(app, ["show", "1846.HK"])
        assert result.exit_code == 0
        assert "Identity" in result.output
        assert "Valuation" not in result.output.replace("Valuation age", "")


# ======================================================================
# 3. Help + flag plumbing
# ======================================================================


class TestShowHelp:
    def test_help_lists_json_flag(self) -> None:
        result = runner.invoke(app, ["show", "--help"])
        assert result.exit_code == 0
        assert "--json" in result.output
