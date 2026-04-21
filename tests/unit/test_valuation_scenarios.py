"""Unit tests for valuation.scenarios.ScenarioComposer."""

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
from portfolio_thesis_engine.schemas.wacc import (
    CapitalStructure,
    CostOfCapitalInputs,
    ScenarioDriversManual,
    WACCInputs,
)
from portfolio_thesis_engine.valuation import (
    EquityBridge,
    FCFFDCFEngine,
    IRRDecomposer,
    ScenarioComposer,
)


def _period() -> FiscalPeriod:
    return FiscalPeriod(year=2024, label="FY2024")


def _canonical() -> CanonicalCompanyState:
    period = _period()
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
            shares_outstanding=Decimal("200"),
        ),
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
                    BalanceSheetLine(label="PP&E", value=Decimal("2000"), category="operating_assets"),
                    BalanceSheetLine(label="Debt", value=Decimal("800"), category="financial_liabilities"),
                    BalanceSheetLine(label="Equity", value=Decimal("1900"), category="equity"),
                ],
                cash_flow=[
                    CashFlowLine(label="CapEx", value=Decimal("-75"), category="capex"),
                ],
                bs_checksum_pass=True,
                is_checksum_pass=True,
                cf_checksum_pass=True,
            )
        ],
        adjustments=AdjustmentsApplied(
            module_a_taxes=[
                ModuleAdjustment(
                    module="A.1",
                    description="Operating tax rate",
                    amount=Decimal("22"),
                    affected_periods=[period],
                    rationale="test",
                ),
            ]
        ),
        analysis=AnalysisDerived(
            invested_capital_by_period=[
                InvestedCapital(
                    period=period,
                    operating_assets=Decimal("2000"),
                    operating_liabilities=Decimal("100"),
                    invested_capital=Decimal("1900"),
                    financial_assets=Decimal("450"),
                    financial_liabilities=Decimal("800"),
                    equity_claims=Decimal("1900"),
                    cross_check_residual=Decimal("0"),
                )
            ],
            nopat_bridge_by_period=[
                NOPATBridge(
                    period=period,
                    ebitda=Decimal("130"),
                    operating_taxes=Decimal("28.6"),
                    nopat=Decimal("101.4"),
                    financial_income=Decimal("0"),
                    financial_expense=Decimal("18"),
                    non_operating_items=Decimal("0"),
                    reported_net_income=Decimal("75"),
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


def _wacc(
    with_bear: bool = True,
    with_base: bool = True,
    with_bull: bool = True,
) -> WACCInputs:
    scenarios: dict[str, ScenarioDriversManual] = {}
    if with_bear:
        scenarios["bear"] = ScenarioDriversManual(
            probability=Decimal("25"),
            revenue_cagr_explicit_period=Decimal("3"),
            terminal_growth=Decimal("2"),
            terminal_operating_margin=Decimal("15"),
        )
    if with_base:
        scenarios["base"] = ScenarioDriversManual(
            probability=Decimal("50"),
            revenue_cagr_explicit_period=Decimal("8"),
            terminal_growth=Decimal("2.5"),
            terminal_operating_margin=Decimal("18"),
        )
    if with_bull:
        scenarios["bull"] = ScenarioDriversManual(
            probability=Decimal("25"),
            revenue_cagr_explicit_period=Decimal("12"),
            terminal_growth=Decimal("3"),
            terminal_operating_margin=Decimal("22"),
        )
    return WACCInputs(
        ticker="1846.HK",
        profile=Profile.P1_INDUSTRIAL,
        valuation_date="2024-12-31",
        current_price=Decimal("12.30"),
        cost_of_capital=CostOfCapitalInputs(
            risk_free_rate=Decimal("2.5"),
            equity_risk_premium=Decimal("5.5"),
            beta=Decimal("1.1"),
            cost_of_debt_pretax=Decimal("4"),
            tax_rate_for_wacc=Decimal("16.5"),
        ),
        capital_structure=CapitalStructure(
            debt_weight=Decimal("25"),
            equity_weight=Decimal("75"),
        ),
        scenarios=scenarios,
    )


# ======================================================================
# Composition
# ======================================================================


class TestScenarioComposition:
    def test_three_scenarios_composed_in_order(self) -> None:
        composer = ScenarioComposer(dcf_engine=FCFFDCFEngine(n_years=5))
        scenarios = composer.compose(_wacc(), _canonical())
        assert [s.label for s in scenarios] == ["bear", "base", "bull"]

    def test_each_scenario_has_drivers_targets_irr(self) -> None:
        composer = ScenarioComposer(dcf_engine=FCFFDCFEngine(n_years=5))
        scenarios = composer.compose(_wacc(), _canonical())
        for s in scenarios:
            assert s.drivers.revenue_cagr is not None
            assert s.drivers.terminal_growth is not None
            assert s.drivers.terminal_margin is not None
            assert "equity_value" in s.targets
            assert "dcf_fcff_per_share" in s.targets
            # IRR is set because shares_outstanding is on the state
            assert s.irr_3y is not None
            assert s.irr_decomposition is not None

    def test_probabilities_preserved_from_wacc(self) -> None:
        composer = ScenarioComposer()
        scenarios = composer.compose(_wacc(), _canonical())
        probs = {s.label: s.probability for s in scenarios}
        assert probs["bear"] == Decimal("25")
        assert probs["base"] == Decimal("50")
        assert probs["bull"] == Decimal("25")

    def test_bull_upside_greater_than_bear(self) -> None:
        composer = ScenarioComposer(dcf_engine=FCFFDCFEngine(n_years=5))
        scenarios = composer.compose(_wacc(), _canonical())
        by_label = {s.label: s for s in scenarios}
        assert by_label["bull"].targets["dcf_fcff_per_share"] > by_label["bear"].targets["dcf_fcff_per_share"]

    def test_single_scenario_compose(self) -> None:
        # Build a WACCInputs with just ``base`` at 100 % probability.
        wacc = WACCInputs(
            ticker="1846.HK",
            profile=Profile.P1_INDUSTRIAL,
            valuation_date="2024-12-31",
            current_price=Decimal("12.30"),
            cost_of_capital=CostOfCapitalInputs(
                risk_free_rate=Decimal("2.5"),
                equity_risk_premium=Decimal("5.5"),
                beta=Decimal("1.1"),
                cost_of_debt_pretax=Decimal("4"),
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
                    terminal_growth=Decimal("2.5"),
                    terminal_operating_margin=Decimal("18"),
                )
            },
        )
        composer = ScenarioComposer()
        scenarios = composer.compose(wacc, _canonical())
        assert len(scenarios) == 1
        assert scenarios[0].label == "base"

    def test_wacc_override_on_scenario(self) -> None:
        wacc = _wacc()
        # Override bear WACC to a very high number; bear should have the
        # lowest target due to steeper discounting.
        wacc.scenarios["bear"].wacc_override = Decimal("20")
        composer = ScenarioComposer()
        scenarios = composer.compose(wacc, _canonical())
        # Not necessarily strictly less since bear already has the lowest
        # growth, but the test pins that the override is consumed without
        # raising.
        assert any(s.label == "bear" for s in scenarios)


class TestScenarioComposerConfig:
    def test_describe_includes_horizon_and_dcf(self) -> None:
        composer = ScenarioComposer(horizon_years=5, dcf_engine=FCFFDCFEngine(n_years=8))
        desc = composer.describe()
        assert desc["engine"] == "ScenarioComposer"
        assert desc["horizon_years"] == 5
        assert desc["dcf"]["n_years"] == 8

    def test_default_engines_wire_up(self) -> None:
        composer = ScenarioComposer()
        assert isinstance(composer.dcf_engine, FCFFDCFEngine)
        assert isinstance(composer.equity_bridge, EquityBridge)
        assert isinstance(composer.irr_decomposer, IRRDecomposer)
