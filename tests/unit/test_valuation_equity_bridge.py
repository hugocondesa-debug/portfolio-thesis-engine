"""Unit tests for valuation.equity_bridge.EquityBridge."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

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
    InvestedCapital,
    KeyRatios,
    MethodologyMetadata,
    NOPATBridge,
    ReclassifiedStatements,
    ValidationResult,
    ValidationResults,
    VintageAndCascade,
)
from portfolio_thesis_engine.valuation.base import DCFResult
from portfolio_thesis_engine.valuation.equity_bridge import EquityBridge


def _period() -> FiscalPeriod:
    return FiscalPeriod(year=2024, label="FY2024")


def _canonical(
    *,
    financial_assets: Decimal = Decimal("100"),
    financial_liabilities: Decimal = Decimal("500"),
    nci_claims: Decimal = Decimal("0"),
    shares: Decimal | None = Decimal("1000"),
) -> CanonicalCompanyState:
    period = _period()
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
            shares_outstanding=shares,
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
            invested_capital_by_period=[
                InvestedCapital(
                    period=period,
                    operating_assets=Decimal("1000"),
                    operating_liabilities=Decimal("100"),
                    invested_capital=Decimal("900"),
                    financial_assets=financial_assets,
                    financial_liabilities=financial_liabilities,
                    equity_claims=Decimal("500"),
                    nci_claims=nci_claims,
                    cross_check_residual=Decimal("0"),
                )
            ],
            nopat_bridge_by_period=[
                NOPATBridge(
                    period=period,
                    ebitda=Decimal("100"),
                    operating_taxes=Decimal("20"),
                    nopat=Decimal("80"),
                    financial_income=Decimal("0"),
                    financial_expense=Decimal("0"),
                    non_operating_items=Decimal("0"),
                    reported_net_income=Decimal("50"),
                )
            ],
            ratios_by_period=[KeyRatios(period=period)],
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


def _dcf(ev: Decimal = Decimal("10000")) -> DCFResult:
    return DCFResult(
        enterprise_value=ev,
        pv_explicit=ev / Decimal("2"),
        pv_terminal=ev / Decimal("2"),
        terminal_value=ev,
        wacc_used=Decimal("8"),
        implied_g=Decimal("2"),
        projected_fcff=(Decimal("100"),),
        n_years=1,
    )


# ======================================================================
# Core bridge math
# ======================================================================


class TestEquityBridge:
    def test_ev_to_equity_with_net_debt_and_shares(self) -> None:
        result = EquityBridge().compute(
            _dcf(Decimal("10000")),
            _canonical(),
        )
        # Net debt = 500 - 100 = 400
        assert result.net_debt == Decimal("400")
        # Equity = EV 10000 - 400 - 0 - 0 = 9600
        assert result.equity_value == Decimal("9600")
        # Per share = 9600 / 1000 = 9.6
        assert result.per_share == Decimal("9.6")

    def test_preferred_equity_subtracted(self) -> None:
        result = EquityBridge().compute(
            _dcf(Decimal("10000")),
            _canonical(),
            preferred_equity=Decimal("500"),
        )
        # Equity = 10000 - 400 - 500 - 0 = 9100
        assert result.equity_value == Decimal("9100")
        assert result.preferred_equity == Decimal("500")

    def test_nci_subtracted(self) -> None:
        result = EquityBridge().compute(
            _dcf(Decimal("10000")),
            _canonical(nci_claims=Decimal("200")),
        )
        # Equity = 10000 - 400 - 0 - 200 = 9400
        assert result.equity_value == Decimal("9400")
        assert result.nci == Decimal("200")

    def test_leases_stay_in_ev(self) -> None:
        """Lease liabilities are NOT in InvestedCapital.financial_liabilities
        per Sprint 7 convention, so they shouldn't affect the bridge math.
        Test verifies the bridge reads financial_liabilities only."""
        state = _canonical(financial_liabilities=Decimal("500"))
        # financial_liabilities already excludes leases; bridge should
        # subtract exactly 500 - financial_assets.
        result = EquityBridge().compute(_dcf(Decimal("10000")), state)
        assert result.net_debt == state.analysis.invested_capital_by_period[0].financial_liabilities \
            - state.analysis.invested_capital_by_period[0].financial_assets

    def test_no_shares_yields_none_per_share(self) -> None:
        result = EquityBridge().compute(_dcf(), _canonical(shares=None))
        assert result.shares_outstanding is None
        assert result.per_share is None

    def test_zero_shares_yields_none_per_share(self) -> None:
        result = EquityBridge().compute(_dcf(), _canonical(shares=Decimal("0")))
        assert result.per_share is None

    def test_missing_ic_yields_zero_net_debt(self) -> None:
        state = _canonical()
        state = state.model_copy(
            update={
                "analysis": state.analysis.model_copy(
                    update={"invested_capital_by_period": []}
                )
            }
        )
        result = EquityBridge().compute(_dcf(Decimal("10000")), state)
        assert result.net_debt == Decimal("0")
        assert result.equity_value == Decimal("10000")

    def test_describe(self) -> None:
        assert EquityBridge().describe() == {"engine": "EquityBridge"}


# ======================================================================
# Round-trip — ev preserved
# ======================================================================


class TestEnterpriseValuePreserved:
    def test_ev_field_matches_dcf_input(self) -> None:
        dcf = _dcf(Decimal("7777"))
        result = EquityBridge().compute(dcf, _canonical())
        assert result.enterprise_value == Decimal("7777")
