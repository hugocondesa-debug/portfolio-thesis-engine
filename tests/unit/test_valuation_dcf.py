"""Unit tests for valuation.dcf.FCFFDCFEngine."""

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
    BalanceSheetLine,
    CanonicalCompanyState,
    CashFlowLine,
    CompanyIdentity,
    IncomeStatementLine,
    InvestedCapital,
    KeyRatios,
    MethodologyMetadata,
    ModuleAdjustment,
    NOPATBridge,
    ReclassifiedStatements,
    ValidationResult,
    ValidationResults,
    VintageAndCascade,
)
from portfolio_thesis_engine.schemas.valuation import Scenario, ScenarioDrivers
from portfolio_thesis_engine.valuation.dcf import FCFFDCFEngine


def _period() -> FiscalPeriod:
    return FiscalPeriod(year=2024, label="FY2024")


def _canonical(
    *,
    revenue: Decimal = Decimal("1000"),
    op_income: Decimal = Decimal("200"),
    d_and_a: Decimal = Decimal("80"),
    capex: Decimal = Decimal("-60"),
    op_tax_rate: Decimal = Decimal("25"),
) -> CanonicalCompanyState:
    """Build a synthetic canonical state with known values for the
    DCF tests. EBITDA = op_income + |d_and_a| = 280."""
    ebitda = op_income + abs(d_and_a)
    period = _period()
    tax_adjustment = ModuleAdjustment(
        module="A.1",
        description="Operating tax rate",
        amount=op_tax_rate,
        affected_periods=[period],
        rationale="test",
    )
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
            shares_outstanding=Decimal("100"),
        ),
        reclassified_statements=[
            ReclassifiedStatements(
                period=period,
                income_statement=[
                    IncomeStatementLine(label="Revenue", value=revenue),
                    IncomeStatementLine(label="Operating income", value=op_income),
                    IncomeStatementLine(label="Net income", value=Decimal("50")),
                ],
                balance_sheet=[
                    BalanceSheetLine(label="Cash", value=Decimal("50"), category="cash"),
                    BalanceSheetLine(
                        label="PP&E", value=Decimal("500"), category="operating_assets"
                    ),
                    BalanceSheetLine(
                        label="Debt",
                        value=Decimal("150"),
                        category="financial_liabilities",
                    ),
                    BalanceSheetLine(label="Equity", value=Decimal("400"), category="equity"),
                ],
                cash_flow=[
                    CashFlowLine(label="CapEx", value=capex, category="capex"),
                ],
                bs_checksum_pass=True,
                is_checksum_pass=True,
                cf_checksum_pass=True,
            )
        ],
        adjustments=AdjustmentsApplied(module_a_taxes=[tax_adjustment]),
        analysis=AnalysisDerived(
            invested_capital_by_period=[
                InvestedCapital(
                    period=period,
                    operating_assets=Decimal("500"),
                    operating_liabilities=Decimal("0"),
                    invested_capital=Decimal("500"),
                    financial_assets=Decimal("50"),
                    financial_liabilities=Decimal("150"),
                    equity_claims=Decimal("400"),
                    cross_check_residual=Decimal("0"),
                )
            ],
            nopat_bridge_by_period=[
                NOPATBridge(
                    period=period,
                    ebitda=ebitda,
                    operating_taxes=ebitda * op_tax_rate / Decimal("100"),
                    nopat=ebitda - ebitda * op_tax_rate / Decimal("100"),
                    financial_income=Decimal("0"),
                    financial_expense=Decimal("10"),
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
            protocols_activated=["A", "B", "C"],
        ),
    )


def _scenario(
    cagr: Decimal = Decimal("5"),
    tg: Decimal = Decimal("2"),
    tm: Decimal = Decimal("20"),
) -> Scenario:
    return Scenario(
        label="base",
        description="test",
        probability=Decimal("100"),
        horizon_years=3,
        drivers=ScenarioDrivers(
            revenue_cagr=cagr,
            terminal_growth=tg,
            terminal_margin=tm,
        ),
    )


# ======================================================================
# Projection
# ======================================================================


class TestProjection:
    def test_revenue_grows_at_cagr(self) -> None:
        engine = FCFFDCFEngine(n_years=3)
        projected, detail = engine.project_fcff(
            _scenario(cagr=Decimal("10")), _canonical()
        )
        # Revenue 1000 → 1100 → 1210 → 1331
        assert detail[1]["revenue"] == Decimal("1100.0")
        assert detail[2]["revenue"] == Decimal("1210.00")
        assert detail[3]["revenue"] == Decimal("1331.000")

    def test_margin_interpolates_to_terminal(self) -> None:
        engine = FCFFDCFEngine(n_years=2)
        # Base margin = 200/1000 = 20%; terminal = 30%. Year 1 interp = 0.5 → 25%. Year 2 = 30%.
        _, detail = engine.project_fcff(
            _scenario(tm=Decimal("30")), _canonical()
        )
        assert abs(detail[1]["margin"] - Decimal("0.25")) < Decimal("0.0001")
        assert abs(detail[2]["margin"] - Decimal("0.30")) < Decimal("0.0001")

    def test_all_years_produce_fcff(self) -> None:
        engine = FCFFDCFEngine(n_years=5)
        projected, _ = engine.project_fcff(_scenario(), _canonical())
        assert len(projected) == 5
        # All positive given base-year is cash-generative
        for fcff in projected:
            assert fcff > 0

    def test_projection_uses_a1_tax_rate(self) -> None:
        engine = FCFFDCFEngine(n_years=1)
        _, d = engine.project_fcff(_scenario(), _canonical(op_tax_rate=Decimal("30")))
        # Year 1 taxes = EBITDA × 30%
        ebitda = d[1]["ebitda"]
        taxes = d[1]["taxes"]
        assert abs(taxes - ebitda * Decimal("0.3")) < Decimal("0.01")


# ======================================================================
# Terminal value
# ======================================================================


class TestTerminal:
    def test_gordon_growth(self) -> None:
        engine = FCFFDCFEngine(n_years=1)
        # FCFF_N = 100, g=2%, WACC=10% → FCFF_{N+1} = 102, TV = 102/0.08 = 1275
        tv = engine.compute_terminal(
            Decimal("100"), _scenario(tg=Decimal("2")), Decimal("10")
        )
        assert abs(tv - Decimal("1275")) < Decimal("0.01")

    def test_wacc_leq_g_raises(self) -> None:
        engine = FCFFDCFEngine(n_years=1)
        with pytest.raises(ValueError, match="Gordon"):
            engine.compute_terminal(
                Decimal("100"), _scenario(tg=Decimal("10")), Decimal("9")
            )


# ======================================================================
# EV (discounting)
# ======================================================================


class TestDiscounting:
    def test_mid_year_discounting(self) -> None:
        # Flat FCFF 100 for 2 years, TV = 500, WACC = 10%
        engine = FCFFDCFEngine(n_years=2)
        pv_explicit, pv_terminal = engine.compute_ev(
            [Decimal("100"), Decimal("100")],
            terminal_value=Decimal("500"),
            wacc_pct=Decimal("10"),
        )
        # Year 1 exponent 0.5: 100 / 1.1^0.5 ≈ 95.35
        # Year 2 exponent 1.5: 100 / 1.1^1.5 ≈ 86.68
        # pv_explicit ≈ 182.03
        assert abs(pv_explicit - Decimal("182.03")) < Decimal("0.1"), pv_explicit
        # TV exponent 2: 500 / 1.21 ≈ 413.22
        assert abs(pv_terminal - Decimal("413.22")) < Decimal("0.1"), pv_terminal


# ======================================================================
# End-to-end compute_target
# ======================================================================


class TestComputeTarget:
    def test_returns_dcf_result_with_all_fields(self) -> None:
        engine = FCFFDCFEngine(n_years=3)
        result = engine.compute_target(
            scenario=_scenario(),
            wacc_pct=Decimal("8"),
            canonical_state=_canonical(),
        )
        assert result.enterprise_value > 0
        assert result.pv_explicit > 0
        assert result.pv_terminal > 0
        assert result.terminal_value > 0
        assert result.n_years == 3
        assert len(result.projected_fcff) == 3
        assert result.wacc_used == Decimal("8")
        assert result.implied_g == Decimal("2")
        assert len(result.projection_detail) == 3

    def test_no_reclassified_statements_raises(self) -> None:
        state = _canonical()
        # Force empty reclassified_statements by rebuilding
        state = state.model_copy(update={"reclassified_statements": []})
        engine = FCFFDCFEngine(n_years=3)
        with pytest.raises(ValueError, match="reclassified_statements"):
            engine.compute_target(
                scenario=_scenario(),
                wacc_pct=Decimal("8"),
                canonical_state=state,
            )


# ======================================================================
# Config guardrails
# ======================================================================


class TestEngineConfig:
    def test_n_years_zero_raises(self) -> None:
        with pytest.raises(ValueError, match="n_years"):
            FCFFDCFEngine(n_years=0)

    def test_describe(self) -> None:
        assert FCFFDCFEngine(n_years=7).describe() == {
            "engine": "FCFFDCFEngine",
            "n_years": 7,
        }
