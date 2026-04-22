"""Phase 1.5.9 regression tests — EBITA-basis NOPAT, sustainable margin,
projection schedule, two sensitivity grids, dispatcher.

Covers Concerns 1-4 in the Phase 1.5.9 spec:

- ``test_nopat_uses_ebita_basis`` — NOPAT = (EBIT + amortisation) × (1−t).
- ``test_nopat_fallback_ebit_no_amort_detected`` — falls back to EBIT
  and flags the methodology when no amortisation is findable.
- ``test_sustainable_margin_excludes_other_gains`` — non-recurring items
  excluded from the DCF projection base.
- ``test_fcff_hand_computed_year1`` — hand-computed year-1 FCFF matches.
- ``test_projection_schedule_persisted_in_snapshot`` — scenarios carry
  projection + terminal + EV breakdown + equity bridge.
- ``test_sensitivity_grids_computed`` — two 3×3 grids per scenario.
- ``test_dispatcher_selects_fcff_for_p1`` — P1 routes to FCFF.
- ``test_dispatcher_raises_for_unimplemented_profiles`` — P2/P3a/P3b
  stubs raise with a clear Phase-2-sprint message.
- ``test_pte_show_detail_renders_full_report`` — the ``--detail`` view
  includes every expected section.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_thesis_engine.extraction.analysis import (
    AnalysisDeriver,
    _sum_non_recurring_op,
)
from portfolio_thesis_engine.schemas.common import (
    Currency,
    FiscalPeriod,
    Profile,
)
from portfolio_thesis_engine.schemas.company import (
    AdjustmentsApplied,
    AnalysisDerived,
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
from portfolio_thesis_engine.schemas.raw_extraction import LineItem
from portfolio_thesis_engine.schemas.valuation import (
    MarketSnapshot,
    Scenario,
    ScenarioDrivers,
)
from portfolio_thesis_engine.schemas.wacc import (
    CapitalStructure,
    CostOfCapitalInputs,
    ScenarioDriversManual,
    WACCInputs,
)
from portfolio_thesis_engine.valuation.dcf import FCFFDCFEngine
from portfolio_thesis_engine.valuation.dispatcher import (
    DDMEngine,
    EmbeddedValueEngine,
    NAVEngine,
    ValuationDispatcher,
)
from portfolio_thesis_engine.valuation.scenarios import ScenarioComposer


# ----------------------------------------------------------------------
# Canonical-state factory
# ----------------------------------------------------------------------
def _period() -> FiscalPeriod:
    return FiscalPeriod(year=2024, label="FY2024")


def _canonical(
    *,
    revenue: Decimal = Decimal("1000"),
    core_op_income: Decimal = Decimal("100"),
    non_recurring: Decimal = Decimal("30"),
    depreciation: Decimal = Decimal("40"),
    amortisation: Decimal = Decimal("10"),
    capex: Decimal = Decimal("-40"),
    op_tax_rate: Decimal = Decimal("25"),
    profile: Profile = Profile.P1_INDUSTRIAL,
) -> CanonicalCompanyState:
    """Synthetic canonical state. Reported OI = core + non_recurring.
    Reported EBITA = reported OI + amort; NOPAT = EBITA × (1-t)."""
    period = _period()
    reported_oi = core_op_income + non_recurring
    ebita = reported_oi + amortisation
    ebitda = reported_oi + depreciation + amortisation
    operating_taxes = ebita * op_tax_rate / Decimal("100")
    nopat = ebita - operating_taxes
    return CanonicalCompanyState(
        extraction_id="ext1",
        extraction_date=datetime(2024, 12, 31, tzinfo=UTC),
        as_of_date="2024-12-31",
        identity=CompanyIdentity(
            ticker="TST",
            name="Test Co",
            reporting_currency=Currency.USD,
            profile=profile,
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
                    IncomeStatementLine(
                        label="Other gains, net", value=non_recurring
                    ),
                    IncomeStatementLine(
                        label="Operating profit", value=reported_oi
                    ),
                    IncomeStatementLine(label="Net income", value=Decimal("60")),
                ],
                balance_sheet=[],
                cash_flow=[
                    CashFlowLine(
                        label="Purchases of property, plant and equipment",
                        value=capex,
                        category="investing",
                    ),
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
                    amount=op_tax_rate,
                    affected_periods=[period],
                    rationale="test",
                )
            ],
        ),
        analysis=AnalysisDerived(
            invested_capital_by_period=[
                InvestedCapital(
                    period=period,
                    operating_assets=Decimal("800"),
                    operating_liabilities=Decimal("0"),
                    invested_capital=Decimal("800"),
                    financial_assets=Decimal("50"),
                    financial_liabilities=Decimal("150"),
                    bank_debt=Decimal("100"),
                    lease_liabilities=Decimal("50"),
                    operating_working_capital=Decimal("60"),
                    equity_claims=Decimal("700"),
                    cross_check_residual=Decimal("0"),
                )
            ],
            nopat_bridge_by_period=[
                NOPATBridge(
                    period=period,
                    ebitda=ebitda,
                    ebita=ebita if amortisation > 0 else None,
                    operating_income=reported_oi,
                    operating_income_sustainable=core_op_income,
                    non_recurring_operating_items=non_recurring,
                    depreciation=depreciation,
                    amortisation=amortisation,
                    nopat_methodology=(
                        "ebita_based" if amortisation > 0 else "ebit_based_no_amort_detected"
                    ),
                    operating_taxes=operating_taxes,
                    nopat=nopat,
                    financial_income=Decimal("0"),
                    financial_expense=Decimal("10"),
                    non_operating_items=Decimal("0"),
                    reported_net_income=Decimal("60"),
                )
            ],
            ratios_by_period=[KeyRatios(period=period)],
        ),
        validation=ValidationResults(
            universal_checksums=[
                ValidationResult(
                    check_id="V.0", name="s", status="PASS", detail="ok"
                )
            ],
            profile_specific_checksums=[],
            confidence_rating="MEDIUM",
        ),
        vintage=VintageAndCascade(),
        methodology=MethodologyMetadata(
            extraction_system_version="test",
            profile_applied=profile,
            protocols_activated=["A"],
        ),
    )


def _scenario_stub(
    cagr: Decimal = Decimal("5"),
    tg: Decimal = Decimal("2"),
    tm: Decimal = Decimal("15"),
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
# 1. NOPAT — EBITA basis (Bug A)
# ======================================================================


class TestBugA_NOPATFromEBITA:
    def test_nopat_uses_ebita_basis(self) -> None:
        """With OI 200 + amortisation 20 + tax 25 %:
        EBITA = 220; NOPAT = 220 × 0.75 = 165."""
        from tests.unit.conftest import build_raw, make_context

        wacc = _wacc_stub()
        is_lines = [
            {"order": 1, "label": "Revenue", "value": "1000"},
            {"order": 2, "label": "Operating profit",
             "value": "200", "is_subtotal": True},
            {"order": 3, "label": "Profit for the year",
             "value": "140", "is_subtotal": True},
        ]
        notes = [
            {
                "title": "Intangibles",
                "tables": [
                    {
                        "table_label": "Intangibles roll-forward 2024",
                        "columns": ["Item", "Total"],
                        "rows": [["Amortisation charge", "-20"]],
                    }
                ],
            },
            {
                "title": "Property, plant and equipment",
                "tables": [
                    {
                        "table_label": "PP&E roll-forward 2024",
                        "columns": ["Item", "Total"],
                        "rows": [["Depreciation charge", "-60"]],
                    }
                ],
            },
        ]
        raw = build_raw(is_lines=is_lines, notes=notes)
        ctx = make_context(raw, wacc)
        ctx.adjustments.append(
            ModuleAdjustment(
                module="A.1",
                description="op tax rate",
                amount=Decimal("25"),
                affected_periods=[parse_fp("FY2024")],
                rationale="",
            )
        )
        bridge = AnalysisDeriver().derive(ctx).nopat_bridge_by_period[0]
        assert bridge.operating_income == Decimal("200")
        assert bridge.depreciation == Decimal("60")
        assert bridge.amortisation == Decimal("20")
        assert bridge.ebita == Decimal("220")
        assert bridge.ebitda == Decimal("280")
        assert bridge.nopat_methodology == "ebita_based"
        assert bridge.operating_taxes == Decimal("55")
        assert bridge.nopat == Decimal("165")

    def test_nopat_fallback_ebit_no_amort_detected(self) -> None:
        """Without an intangibles note the engine falls back to EBIT
        and logs the methodology so the operator sees the gap."""
        from tests.unit.conftest import build_raw, make_context

        wacc = _wacc_stub()
        is_lines = [
            {"order": 1, "label": "Revenue", "value": "1000"},
            {"order": 2, "label": "Depreciation and amortisation",
             "value": "-80"},
            {"order": 3, "label": "Operating profit",
             "value": "200", "is_subtotal": True},
            {"order": 4, "label": "Profit for the year",
             "value": "140", "is_subtotal": True},
        ]
        raw = build_raw(is_lines=is_lines)
        ctx = make_context(raw, wacc)
        ctx.adjustments.append(
            ModuleAdjustment(
                module="A.1",
                description="op tax rate",
                amount=Decimal("25"),
                affected_periods=[parse_fp("FY2024")],
                rationale="",
            )
        )
        bridge = AnalysisDeriver().derive(ctx).nopat_bridge_by_period[0]
        assert bridge.amortisation == Decimal("0")
        assert bridge.depreciation == Decimal("80")
        assert bridge.nopat_methodology == "ebit_based_no_amort_detected"
        # NOPAT = EBIT × (1 − t) = 200 × 0.75 = 150.
        assert bridge.nopat == Decimal("150")


# ======================================================================
# 2. Sustainable margin — Bug B
# ======================================================================


class TestBugB_SustainableMargin:
    def test_sustainable_margin_excludes_other_gains(self) -> None:
        state = _canonical(
            revenue=Decimal("1000"),
            core_op_income=Decimal("100"),
            non_recurring=Decimal("30"),
            amortisation=Decimal("0"),
        )
        engine = FCFFDCFEngine(n_years=3)
        base = engine._extract_base_year(state)
        # Reported margin: 130 / 1000 = 13 %. Sustainable: 100 / 1000 = 10 %.
        assert base["reported_operating_margin_fraction"] == Decimal("0.13")
        assert base["base_operating_margin_fraction"] == Decimal("0.10")

    def test_sum_non_recurring_op_matches_vocab(self) -> None:
        items = [
            LineItem(order=1, label="Revenue", value=Decimal("1000")),
            LineItem(order=2, label="Other gains, net", value=Decimal("30")),
            LineItem(order=3, label="Government grants", value=Decimal("5")),
            LineItem(order=4, label="Gain on disposal of subsidiary",
                     value=Decimal("10")),
            LineItem(order=5, label="Administrative expenses",
                     value=Decimal("-200")),
            LineItem(order=6, label="Other operating expenses",
                     value=Decimal("-50")),
        ]
        total, labels = _sum_non_recurring_op(items)
        assert total == Decimal("45")
        assert "Administrative expenses" not in labels


# ======================================================================
# 3. FCFF hand-computed
# ======================================================================


class TestFCFFHandComputed:
    def test_fcff_hand_computed_year1(self) -> None:
        """Synthetic: revenue 1000, sustainable margin 10 %, CAGR 0,
        terminal margin 10 % (no interpolation), amortisation 10,
        depreciation 40, CapEx 40, tax 25 %, ΔWC 0.

        Year 1: revenue 1000, EBIT 100, EBITA 110, NOPAT 82.5,
                FCFF = 82.5 + 40 − 40 − 0 = 82.5.
        """
        state = _canonical(
            revenue=Decimal("1000"),
            core_op_income=Decimal("100"),
            non_recurring=Decimal("0"),
            depreciation=Decimal("40"),
            amortisation=Decimal("10"),
            capex=Decimal("-40"),
            op_tax_rate=Decimal("25"),
        )
        scenario = _scenario_stub(
            cagr=Decimal("0"), tg=Decimal("1"), tm=Decimal("10")
        )
        engine = FCFFDCFEngine(n_years=1)
        _, detail = engine.project_fcff(scenario, state)
        y1 = detail[1]
        assert y1["revenue"] == Decimal("1000")
        assert y1["ebit"] == Decimal("100.00")
        assert y1["amortisation"] == Decimal("10.00")
        assert y1["ebita"] == Decimal("110.00")
        assert y1["nopat"] == Decimal("82.5000")
        assert y1["depreciation"] == Decimal("40.00")
        assert y1["capex"] == Decimal("40.00")
        assert y1["fcff"] == Decimal("82.5000")


# ======================================================================
# 4. Projection schedule + EV breakdown + equity bridge persisted
# ======================================================================


class TestProjectionPersisted:
    def test_projection_schedule_persisted_in_snapshot(self) -> None:
        state = _canonical()
        wacc = _wacc_stub_with_bull_bear()
        composer = ScenarioComposer(dcf_engine=FCFFDCFEngine(n_years=3))
        scenarios = composer.compose(wacc_inputs=wacc, canonical_state=state)
        base = next(s for s in scenarios if s.label == "base")

        assert len(base.projection) == 4
        assert base.projection[0].year == 0
        assert base.projection[-1].year == 3
        # Year 0 shows both reported + sustainable margin when they differ.
        assert base.projection[0].operating_margin_sustainable is not None
        assert base.projection[0].operating_margin_reported is not None
        # Year 0 has no FCFF / discount factor (reference row only).
        assert base.projection[0].fcff is None
        assert base.projection[0].discount_factor is None
        # Forecast rows populated.
        for row in base.projection[1:]:
            assert row.fcff is not None
            assert row.pv_fcff is not None
            assert row.discount_factor is not None
            assert row.ebita is not None  # amortisation > 0 fixture
            assert row.amort_for_ebita is not None

        assert base.terminal is not None
        assert base.terminal.terminal_value > 0
        assert base.terminal.pv_terminal > 0

        # EV breakdown: total EV = sum_pv_explicit + pv_terminal.
        evb = base.enterprise_value_breakdown
        assert evb is not None
        assert abs(evb.total_ev - (evb.sum_pv_explicit + evb.pv_terminal)) < Decimal("0.01")

        # Equity bridge has the renamed fields; bank debt + lease
        # liabilities are populated separately.
        eq = base.equity_bridge
        assert eq is not None
        assert eq.enterprise_value == evb.total_ev
        assert eq.cash_and_equivalents == Decimal("50")
        assert eq.financial_debt == Decimal("100")
        assert eq.lease_liabilities == Decimal("50")


# ======================================================================
# 5. Sensitivity grids — WACC×g AND CAGR×margin
# ======================================================================


class TestSensitivityGrids:
    def test_sensitivity_grids_computed(self) -> None:
        state = _canonical()
        wacc = _wacc_stub_with_bull_bear()
        composer = ScenarioComposer(dcf_engine=FCFFDCFEngine(n_years=3))
        scenarios = composer.compose(wacc_inputs=wacc, canonical_state=state)
        base = next(s for s in scenarios if s.label == "base")

        # Two 3×3 grids per scenario.
        assert len(base.sensitivity_grids) == 2
        axes = {(g.axis_x, g.axis_y) for g in base.sensitivity_grids}
        assert ("wacc", "terminal_growth") in axes
        assert ("revenue_cagr", "terminal_margin") in axes

        for g in base.sensitivity_grids:
            assert len(g.x_values) == 3
            assert len(g.y_values) == 3
            assert len(g.target_per_share) == 3
            for row in g.target_per_share:
                assert len(row) == 3

    def test_wacc_g_grid_gordon_undefined_cells_zeroed(self) -> None:
        """Cells where WACC ≤ g produce target 0 (rendered as ``—``)."""
        state = _canonical()
        # Force WACC ≈ g so the low-WACC × high-g corner underflows.
        scenario = _scenario_stub(tg=Decimal("9"))
        engine = FCFFDCFEngine(n_years=3)
        from portfolio_thesis_engine.valuation.equity_bridge import EquityBridge

        grid = engine.compute_wacc_g_grid(
            scenario=scenario,
            canonical_state=state,
            base_wacc_pct=Decimal("9.25"),
            equity_bridge_fn=EquityBridge().compute,
        )
        # At least one cell is zero (Gordon undefined).
        zeros = sum(
            1 for row in grid["target_per_share"] for v in row if v == 0
        )
        assert zeros >= 1


# ======================================================================
# 6. Dispatcher — profile routing
# ======================================================================


class TestDispatcher:
    def test_dispatcher_selects_fcff_for_p1(self) -> None:
        state = _canonical(profile=Profile.P1_INDUSTRIAL)
        dispatcher = ValuationDispatcher()
        engine = dispatcher.select_engine(state)
        # Structural: must be the FCFF implementation (has n_years attr).
        assert isinstance(engine, FCFFDCFEngine)
        assert engine.describe().get("engine") == "FCFFDCFEngine"

    def test_dispatcher_raises_for_unimplemented_profiles(self) -> None:
        dispatcher = ValuationDispatcher()
        for profile, expected_stub in (
            (Profile.P2_BANKS, DDMEngine),
            (Profile.P3A_INSURANCE, EmbeddedValueEngine),
            (Profile.P3B_REITS, NAVEngine),
        ):
            engine = dispatcher.select_engine_for_profile(profile)
            assert isinstance(engine, expected_stub)
            meta = engine.describe()
            assert meta["implemented"] is False
            assert "Phase 2" in meta["target_sprint"]
            # compute() raises a descriptive NotImplementedError.
            market = MarketSnapshot(
                price=Decimal("1"),
                price_date="2024-12-31",
                currency=Currency.USD,
                wacc=Decimal("8"),
            )
            scenario = _scenario_stub()
            with pytest.raises(NotImplementedError, match="Phase 2"):
                engine.compute(
                    canonical_state=_canonical(profile=profile),
                    scenario=scenario,
                    market=market,
                )


# ======================================================================
# 7. `pte show --detail` renders full report
# ======================================================================


class TestShowDetailRender:
    def test_pte_show_detail_renders_full_report(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import io

        from rich.console import Console

        from portfolio_thesis_engine.cli import show_cmd
        from portfolio_thesis_engine.ficha import FichaBundle
        from portfolio_thesis_engine.schemas.common import (
            ConvictionLevel,
            GuardrailStatus,
        )
        from portfolio_thesis_engine.schemas.valuation import (
            Conviction,
            GuardrailCategory,
            GuardrailsStatus,
            ValuationSnapshot,
            WeightedOutputs,
        )

        state = _canonical()
        wacc = _wacc_stub_with_bull_bear()
        composer = ScenarioComposer(dcf_engine=FCFFDCFEngine(n_years=3))
        scenarios = composer.compose(wacc_inputs=wacc, canonical_state=state)
        sensitivities = composer.compose_sensitivity(
            wacc_inputs=wacc, canonical_state=state, labels=("base",)
        )
        market = MarketSnapshot(
            price=Decimal("10"),
            price_date="2024-12-31",
            shares_outstanding=Decimal("100"),
            market_cap=Decimal("1000"),
            wacc=Decimal("10"),
            currency=Currency.USD,
        )
        snapshot = ValuationSnapshot(
            version=1,
            created_at=datetime.now(UTC),
            created_by="test",
            snapshot_id="TST_TEST",
            ticker="TST",
            company_name="Test Co",
            profile=Profile.P1_INDUSTRIAL,
            valuation_date=datetime.now(UTC),
            based_on_extraction_id="ext1",
            based_on_extraction_date=datetime.now(UTC),
            market=market,
            scenarios=scenarios,
            weighted=WeightedOutputs(
                expected_value=Decimal("12"),
                expected_value_method_used="DCF_FCFF",
                fair_value_range_low=Decimal("8"),
                fair_value_range_high=Decimal("16"),
                upside_pct=Decimal("20"),
                asymmetry_ratio=Decimal("1"),
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
                        category="V",
                        total=1,
                        passed=1,
                        warned=0,
                        failed=0,
                        skipped=0,
                    )
                ],
                overall=GuardrailStatus.PASS,
            ),
            forecast_system_version="phase1.5.9",
            sensitivities=sensitivities,
        )

        bundle = FichaBundle(
            ticker="TST",
            canonical_state=state,
            valuation_snapshot=snapshot,
            ficha=None,
        )

        buf = io.StringIO()
        test_console = Console(file=buf, width=300, record=True)
        monkeypatch.setattr(show_cmd, "console", test_console)
        show_cmd._render_detail(bundle, scenario_filter=None)

        rendered = buf.getvalue()
        for marker in (
            "Identity",
            "Economic balance sheet",
            "NOPAT bridge",
            "Key ratios",
            "Scenarios",
            "Projection",
            "Terminal",
            "Enterprise value breakdown",
            "EV → equity bridge",
            "Sensitivity",
        ):
            assert marker in rendered, f"missing section {marker!r}"


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def parse_fp(label: str) -> FiscalPeriod:
    from portfolio_thesis_engine.extraction.base import parse_fiscal_period

    return parse_fiscal_period(label)


def _wacc_stub() -> WACCInputs:
    return WACCInputs(
        ticker="TST",
        profile=Profile.P1_INDUSTRIAL,
        valuation_date="2024-12-31",
        current_price=Decimal("10"),
        cost_of_capital=CostOfCapitalInputs(
            risk_free_rate=Decimal("3"),
            equity_risk_premium=Decimal("5"),
            beta=Decimal("1"),
            cost_of_debt_pretax=Decimal("5"),
            tax_rate_for_wacc=Decimal("25"),
        ),
        capital_structure=CapitalStructure(
            debt_weight=Decimal("30"),
            equity_weight=Decimal("70"),
        ),
        scenarios={
            "base": ScenarioDriversManual(
                probability=Decimal("100"),
                revenue_cagr_explicit_period=Decimal("5"),
                terminal_growth=Decimal("2"),
                terminal_operating_margin=Decimal("15"),
            )
        },
    )


def _wacc_stub_with_bull_bear() -> WACCInputs:
    wacc = _wacc_stub()
    return wacc.model_copy(
        update={
            "scenarios": {
                "bear": ScenarioDriversManual(
                    probability=Decimal("25"),
                    revenue_cagr_explicit_period=Decimal("2"),
                    terminal_growth=Decimal("1"),
                    terminal_operating_margin=Decimal("10"),
                ),
                "base": ScenarioDriversManual(
                    probability=Decimal("50"),
                    revenue_cagr_explicit_period=Decimal("5"),
                    terminal_growth=Decimal("2"),
                    terminal_operating_margin=Decimal("15"),
                ),
                "bull": ScenarioDriversManual(
                    probability=Decimal("25"),
                    revenue_cagr_explicit_period=Decimal("10"),
                    terminal_growth=Decimal("3"),
                    terminal_operating_margin=Decimal("20"),
                ),
            }
        }
    )
