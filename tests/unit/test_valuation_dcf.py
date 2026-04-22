"""Unit tests for valuation.dcf.FCFFDCFEngine."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

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


# ======================================================================
# Phase 1.5.8 regression — label-regex base-year lookups on IFRS
# labels ("Operating profit", "Purchases of property plant and
# equipment") that the Phase-1 exact-string lookups missed.
# ======================================================================


class TestPhase1_5_8_IFRSLabels:
    """Regression: DCF engine must pick up Operating profit /
    Purchase[s] of property plant and equipment by label-regex, not
    exact string or Phase-1 category."""

    def test_operating_profit_label_matches(self) -> None:
        """Previously _sum_by_label("Operating income") returned 0 on
        IFRS filings that report "Operating profit" — collapsing
        base-margin to 0 and D&A ratio to (EBITDA − 0)/revenue."""
        state = _canonical()
        # Swap the "Operating income" label for IFRS "Operating profit".
        rs = state.reclassified_statements[0]
        new_is = [
            IncomeStatementLine(label="Revenue", value=Decimal("1000")),
            IncomeStatementLine(label="Operating profit", value=Decimal("200")),
            IncomeStatementLine(label="Net income", value=Decimal("50")),
        ]
        rs.income_statement.clear()
        rs.income_statement.extend(new_is)

        engine = FCFFDCFEngine(n_years=3)
        base = engine._extract_base_year(state)
        # Margin = 200 / 1000 = 0.20. Before Phase 1.5.8 would return 0.
        assert base["base_operating_margin_fraction"] == Decimal("0.2")

    def test_capex_label_purchases_plural(self) -> None:
        """EuroEyes reports "Purchases of property, plant and equipment"
        — Phase-1 `category == "capex"` missed it (category is now
        "investing" under the new schema). Regex accepts singular +
        plural."""
        state = _canonical()
        rs = state.reclassified_statements[0]
        rs.cash_flow.clear()
        rs.cash_flow.append(
            CashFlowLine(
                label="Purchases of property, plant and equipment",
                value=Decimal("-60"),
                category="investing",  # new schema category
            )
        )
        engine = FCFFDCFEngine(n_years=3)
        base = engine._extract_base_year(state)
        # CapEx ratio = 60 / 1000 = 0.06.
        assert base["capex_to_revenue_fraction"] == Decimal("0.06")

    def test_capex_label_singular(self) -> None:
        """Fixtures (and some filings) use "Purchase of property…"
        singular. Regex must match both."""
        state = _canonical()
        rs = state.reclassified_statements[0]
        rs.cash_flow.clear()
        rs.cash_flow.append(
            CashFlowLine(
                label="Purchase of property, plant and equipment",
                value=Decimal("-80"),
                category="investing",
            )
        )
        engine = FCFFDCFEngine(n_years=3)
        base = engine._extract_base_year(state)
        assert base["capex_to_revenue_fraction"] == Decimal("0.08")


class TestPhase1_5_8_FCFFComposition:
    """Phase 1.5.8 — FCFF must deduct CapEx from NOPAT (and add back
    D&A). Regression for the 'CapEx ratio = 0 → FCFF = NOPAT + D&A'
    inflation bug."""

    @staticmethod
    def _retag_capex_label(
        state: CanonicalCompanyState, new_label: str
    ) -> None:
        """The pre-existing _canonical() helper uses a Phase-1 label
        'CapEx' that Phase 1.5.8's label-regex doesn't match. Swap in
        a real-world label so the test exercises the regex path."""
        rs = state.reclassified_statements[0]
        old = rs.cash_flow[:]
        rs.cash_flow.clear()
        for ln in old:
            if ln.label == "CapEx":
                rs.cash_flow.append(
                    CashFlowLine(
                        label=new_label,
                        value=ln.value,
                        category=ln.category,
                    )
                )
            else:
                rs.cash_flow.append(ln)

    def test_fcff_includes_capex_deduction(self) -> None:
        """FCFF = NOPAT + D&A − CapEx − ΔWC (ΔWC = 0 in Phase 1).
        With revenue 1000, margin 20%, tax 25%, CapEx 60, D&A 80:
        NOPAT = 200 × 0.75 = 150; FCFF = 150 + 80 − 60 = 170."""
        state = _canonical(
            revenue=Decimal("1000"),
            op_income=Decimal("200"),
            d_and_a=Decimal("80"),
            capex=Decimal("-60"),
            op_tax_rate=Decimal("25"),
        )
        self._retag_capex_label(state, "Purchases of property, plant and equipment")
        # Use a flat scenario (no growth, margin stays at base).
        scenario = _scenario(cagr=Decimal("0"), tg=Decimal("1"), tm=Decimal("20"))
        engine = FCFFDCFEngine(n_years=1)
        projected, detail = engine.project_fcff(scenario, state)
        y1 = detail[1]
        # Y1: revenue 1000, margin 20%, EBITDA 200, NOPAT 150,
        # CapEx 60, D&A 80, reinvestment = 60 − 80 = −20, FCFF = 170.
        assert y1["capex"] == Decimal("60.00")
        assert y1["d_and_a"] == Decimal("80.00")
        assert y1["reinvestment"] == Decimal("-20.00")
        assert y1["fcff"] == Decimal("170.00")

    def test_fcff_drops_when_capex_ratio_increases(self) -> None:
        """Regression: earlier bug had CapEx = 0 always → FCFF = NOPAT
        + D&A (inflated). Two states, differing only in CapEx,
        must produce different FCFF values."""
        low_capex = _canonical(capex=Decimal("-20"))
        high_capex = _canonical(capex=Decimal("-100"))
        self._retag_capex_label(low_capex, "Purchases of property, plant and equipment")
        self._retag_capex_label(high_capex, "Purchases of property, plant and equipment")
        scenario = _scenario(cagr=Decimal("0"), tg=Decimal("1"), tm=Decimal("20"))
        engine = FCFFDCFEngine(n_years=1)
        low_fcff = engine.project_fcff(scenario, low_capex)[0][0]
        high_fcff = engine.project_fcff(scenario, high_capex)[0][0]
        # Higher CapEx → lower FCFF (80 difference in CapEx → 80
        # difference in FCFF).
        assert low_fcff - high_fcff == Decimal("80.00")


class TestPhase1_5_8_EquityBridgeLeases:
    """Lease liabilities flow through InvestedCapital.financial_liabilities
    in Phase 1.5.3+ (the AnalysisDeriver's classifier includes the
    /lease liabilit/ pattern). The equity bridge subtracts net_debt
    (financial_liabilities − financial_assets), so leases are
    subtracted from EV to reach equity."""

    def test_leases_in_net_debt_reduce_equity(self) -> None:
        """Two states: one with lease liability, one without (all else
        equal). Equity value differs by the lease amount."""
        from portfolio_thesis_engine.valuation.base import DCFResult
        from portfolio_thesis_engine.valuation.equity_bridge import EquityBridge

        def _with_lease(lease_liab: Decimal) -> CanonicalCompanyState:
            state = _canonical()
            period = state.analysis.invested_capital_by_period[0].period
            state.analysis.invested_capital_by_period.clear()
            state.analysis.invested_capital_by_period.append(
                InvestedCapital(
                    period=period,
                    operating_assets=Decimal("500"),
                    operating_liabilities=Decimal("0"),
                    invested_capital=Decimal("500"),
                    financial_assets=Decimal("50"),
                    # financial_liabilities includes debt + leases (same
                    # classification AnalysisDeriver uses).
                    financial_liabilities=Decimal("150") + lease_liab,
                    equity_claims=Decimal("400"),
                    cross_check_residual=Decimal("0"),
                )
            )
            return state

        dcf = DCFResult(
            enterprise_value=Decimal("2000"),
            pv_explicit=Decimal("500"),
            pv_terminal=Decimal("1500"),
            terminal_value=Decimal("1500"),
            wacc_used=Decimal("8"),
            implied_g=Decimal("2"),
            projected_fcff=(Decimal("100"),),
            n_years=1,
            projection_detail={},
        )
        no_leases = _with_lease(Decimal("0"))
        with_leases = _with_lease(Decimal("300"))
        eq_no = EquityBridge().compute(dcf, no_leases).equity_value
        eq_with = EquityBridge().compute(dcf, with_leases).equity_value
        # Equity with leases = equity_no_leases − 300 (leases counted
        # as debt-like claim on EV).
        assert eq_no - eq_with == Decimal("300")


class TestPhase1_5_8_EuroEyesRealisticRange:
    """End-to-end DCF on the real 4288-line EuroEyes extraction.
    After Phase 1.5.8, per-share targets fall in the user-predicted
    HK$ 3-12 range (vs pre-fix HK$ 13-27)."""

    _REAL_CLAUDE_AI_FIXTURE = (
        Path(__file__).parent.parent / "fixtures" / "euroeyes"
        / "raw_extraction_real_claude_ai_2025.yaml"
    )
    _WACC_FIXTURE = (
        Path(__file__).parent.parent / "fixtures" / "wacc" / "euroeyes_real.md"
    )

    @pytest.mark.asyncio
    async def test_dcf_euroeyes_base_scenario_in_realistic_range(self) -> None:
        """Base scenario per-share in HK$ 3-10 (architect's sanity
        check produced ~5.18; CLI uses n_years=5 vs architect's 3, so
        a slightly wider range is acceptable)."""
        from unittest.mock import MagicMock

        from portfolio_thesis_engine.extraction.coordinator import ExtractionCoordinator
        from portfolio_thesis_engine.ingestion.raw_extraction_parser import (
            parse_raw_extraction,
        )
        from portfolio_thesis_engine.ingestion.wacc_parser import parse_wacc_inputs
        from portfolio_thesis_engine.llm.cost_tracker import CostTracker
        from portfolio_thesis_engine.pipeline.coordinator import _identity_from
        from portfolio_thesis_engine.valuation.equity_bridge import EquityBridge
        from portfolio_thesis_engine.valuation.scenarios import ScenarioComposer

        raw = parse_raw_extraction(self._REAL_CLAUDE_AI_FIXTURE)
        wacc = parse_wacc_inputs(self._WACC_FIXTURE)
        identity = _identity_from(None, wacc, raw)
        tracker = CostTracker(log_path=Path("/tmp/t_p158.jsonl"))
        coord = ExtractionCoordinator(
            profile=Profile.P1_INDUSTRIAL,
            llm=MagicMock(),
            cost_tracker=tracker,
        )
        state = (
            await coord.extract_canonical(
                raw_extraction=raw, wacc_inputs=wacc, identity=identity
            )
        ).canonical_state
        assert state is not None

        engine = FCFFDCFEngine(n_years=5)
        composer = ScenarioComposer(dcf_engine=engine)
        scenarios = composer.compose(wacc_inputs=wacc, canonical_state=state)
        base = next(s for s in scenarios if s.label == "base")
        dcf = engine.compute_target(base, wacc.wacc, state)
        bridge = EquityBridge().compute(dcf, state)
        assert bridge.per_share is not None
        # Pre-1.5.8: ~HK$ 19.92 (inflated by ~3.8×). Post-fix: ~HK$ 7.66.
        # Assert the realistic range; catches if the bug reappears.
        assert Decimal("3") < bridge.per_share < Decimal("10"), (
            f"Base-scenario target HK${bridge.per_share} outside realistic "
            f"range [3, 10] — likely a DCF regression (CapEx=0, margin=0, "
            f"or D&A ratio wrong)."
        )
