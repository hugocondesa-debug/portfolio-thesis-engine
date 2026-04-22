"""Phase 1.5.9.1 regression tests — NOPAT consistency + minor fixes.

- ``test_nopat_bridge_uses_sustainable_as_primary`` — bridge ``nopat`` = sustainable;
  ``nopat_reported`` preserves the reported basis.
- ``test_nopat_bridge_exposes_both_reported_and_sustainable`` — both EBIT + NOPAT on both
  bases reachable from the schema.
- ``test_roic_computed_from_sustainable_nopat`` — primary ROIC anchors on
  sustainable NOPAT; ``roic_reported`` on reported.
- ``test_equity_bridge_separates_debt_from_leases`` — bank debt and lease
  liabilities are distinct fields in the equity bridge.
- ``test_wc_projection_uses_revenue_ratio`` — per-year ΔWC = (wc_ratio × revenue) delta.
- ``test_capex_revenue_ratio_computed`` — ``KeyRatios.capex_revenue`` populates with
  the plural "Purchases of ..." pattern.
- ``test_identity_name_populated_from_metadata`` — ``metadata.company_name`` wins over
  a stale SQLite row carrying the ticker.
"""

from __future__ import annotations

from decimal import Decimal

from portfolio_thesis_engine.extraction.analysis import AnalysisDeriver
from portfolio_thesis_engine.schemas.common import FiscalPeriod, Profile
from portfolio_thesis_engine.schemas.company import ModuleAdjustment
from portfolio_thesis_engine.schemas.wacc import WACCInputs
from portfolio_thesis_engine.valuation.dcf import FCFFDCFEngine

from .conftest import build_raw, make_context
from .test_phase1_5_9_transparency import (
    _canonical,
    _scenario_stub,
    _wacc_stub,
    _wacc_stub_with_bull_bear,
    parse_fp,
)


def _op_tax(amount: str = "25") -> ModuleAdjustment:
    return ModuleAdjustment(
        module="A.1",
        description="op tax rate",
        amount=Decimal(amount),
        affected_periods=[parse_fp("FY2024")],
        rationale="",
    )


# ======================================================================
# Issue 1 — NOPAT primary = sustainable
# ======================================================================


class TestNOPATSustainablePrimary:
    _IS_LINES = [
        {"order": 1, "label": "Revenue", "value": "1000"},
        {"order": 2, "label": "Administrative expenses", "value": "-600"},
        {"order": 3, "label": "Other gains, net", "value": "30"},
        {"order": 4, "label": "Operating profit", "value": "350",
         "is_subtotal": True},
        {"order": 5, "label": "Profit for the year", "value": "250",
         "is_subtotal": True},
    ]
    _NOTES = [
        {
            "title": "Intangibles",
            "tables": [
                {
                    "table_label": "Intangibles 2024",
                    "columns": ["Item", "Total"],
                    "rows": [["Amortisation charge", "-10"]],
                }
            ],
        },
        {
            "title": "Property, plant and equipment",
            "tables": [
                {
                    "table_label": "PP&E 2024",
                    "columns": ["Item", "Total"],
                    "rows": [["Depreciation charge", "-40"]],
                }
            ],
        },
    ]

    def test_nopat_bridge_uses_sustainable_as_primary(
        self, wacc_inputs: WACCInputs
    ) -> None:
        raw = build_raw(is_lines=self._IS_LINES, notes=self._NOTES)
        ctx = make_context(raw, wacc_inputs)
        ctx.adjustments.append(_op_tax("25"))
        bridge = AnalysisDeriver().derive(ctx).nopat_bridge_by_period[0]
        # Reported EBIT 350, sustainable EBIT 320 (after −30 non-recurring).
        # EBITA sustainable = 320 + 10 = 330; NOPAT = 330 × 0.75 = 247.5.
        assert bridge.which_used_for_nopat == "sustainable"
        assert bridge.operating_income == Decimal("350")
        assert bridge.operating_income_sustainable == Decimal("320")
        assert bridge.nopat == Decimal("247.50")
        # Reported basis preserved for reconciliation:
        # EBITA reported = 360; NOPAT reported = 270.
        assert bridge.nopat_reported == Decimal("270.00")

    def test_nopat_bridge_exposes_both_reported_and_sustainable(
        self, wacc_inputs: WACCInputs
    ) -> None:
        raw = build_raw(is_lines=self._IS_LINES, notes=self._NOTES)
        ctx = make_context(raw, wacc_inputs)
        ctx.adjustments.append(_op_tax("25"))
        bridge = AnalysisDeriver().derive(ctx).nopat_bridge_by_period[0]
        assert bridge.operating_income is not None
        assert bridge.operating_income_sustainable is not None
        assert bridge.operating_income != bridge.operating_income_sustainable
        assert bridge.nopat_reported is not None
        assert bridge.nopat != bridge.nopat_reported

    def test_no_non_recurring_leaves_reported_as_primary(
        self, wacc_inputs: WACCInputs
    ) -> None:
        is_lines = [
            {"order": 1, "label": "Revenue", "value": "1000"},
            {"order": 2, "label": "Operating profit", "value": "200",
             "is_subtotal": True},
            {"order": 3, "label": "Profit for the year", "value": "140",
             "is_subtotal": True},
        ]
        raw = build_raw(is_lines=is_lines)
        ctx = make_context(raw, wacc_inputs)
        ctx.adjustments.append(_op_tax("25"))
        bridge = AnalysisDeriver().derive(ctx).nopat_bridge_by_period[0]
        # No non-recurring items → "reported" stays primary.
        assert bridge.which_used_for_nopat == "reported"
        assert bridge.operating_income_sustainable is None
        # NOPAT = 200 × 0.75 = 150; reported matches primary.
        assert bridge.nopat == Decimal("150")
        assert bridge.nopat_reported == Decimal("150.00")


# ======================================================================
# ROIC — sustainable primary + reported secondary
# ======================================================================


class TestROICDual:
    _BS_LINES = [
        {"order": 1, "label": "Cash and cash equivalents",
         "value": "200", "section": "current_assets"},
        {"order": 2, "label": "Trade receivables",
         "value": "300", "section": "current_assets"},
        {"order": 3, "label": "Total current assets",
         "value": "500", "section": "current_assets", "is_subtotal": True},
        {"order": 4, "label": "Property, plant and equipment",
         "value": "700", "section": "non_current_assets"},
        {"order": 5, "label": "Total non-current assets",
         "value": "700", "section": "non_current_assets", "is_subtotal": True},
        {"order": 6, "label": "Total assets",
         "value": "1200", "section": "total_assets", "is_subtotal": True},
        {"order": 7, "label": "Trade payables",
         "value": "150", "section": "current_liabilities"},
        {"order": 8, "label": "Total current liabilities",
         "value": "150", "section": "current_liabilities", "is_subtotal": True},
        {"order": 9, "label": "Long-term borrowings",
         "value": "400", "section": "non_current_liabilities"},
        {"order": 10, "label": "Total non-current liabilities",
         "value": "400", "section": "non_current_liabilities",
         "is_subtotal": True},
        {"order": 11, "label": "Share capital",
         "value": "650", "section": "equity"},
        {"order": 12, "label": "Total equity",
         "value": "650", "section": "equity", "is_subtotal": True},
    ]

    def test_roic_computed_from_sustainable_nopat(
        self, wacc_inputs: WACCInputs
    ) -> None:
        is_lines = [
            {"order": 1, "label": "Revenue", "value": "1000"},
            {"order": 2, "label": "Other gains, net", "value": "30"},
            {"order": 3, "label": "Operating profit", "value": "350",
             "is_subtotal": True},
            {"order": 4, "label": "Profit for the year", "value": "140",
             "is_subtotal": True},
        ]
        raw = build_raw(is_lines=is_lines, bs_lines=self._BS_LINES)
        ctx = make_context(raw, wacc_inputs)
        ctx.adjustments.append(_op_tax("25"))
        derived = AnalysisDeriver().derive(ctx)
        ratios = derived.ratios_by_period[0]
        bridge = derived.nopat_bridge_by_period[0]
        ic = derived.invested_capital_by_period[0]

        # Primary ROIC anchors on sustainable NOPAT.
        expected_primary = bridge.nopat * Decimal("100") / ic.invested_capital
        assert abs(ratios.roic - expected_primary) < Decimal("0.01")
        # Reported ROIC on reported NOPAT.
        assert ratios.roic_reported is not None
        expected_reported = (
            bridge.nopat_reported * Decimal("100") / ic.invested_capital
        )
        assert abs(ratios.roic_reported - expected_reported) < Decimal("0.01")
        # Sanity: reported > primary (reported NOPAT is larger).
        assert ratios.roic_reported > ratios.roic


# ======================================================================
# Issue 2 — equity bridge debt vs leases
# ======================================================================


class TestEquityBridgeSplit:
    def test_invested_capital_separates_debt_from_leases(
        self, wacc_inputs: WACCInputs
    ) -> None:
        bs_lines = [
            {"order": 1, "label": "Cash and cash equivalents",
             "value": "100", "section": "current_assets"},
            {"order": 2, "label": "Bank loans (non-current)",
             "value": "200", "section": "non_current_liabilities"},
            {"order": 3, "label": "Lease liabilities (non-current)",
             "value": "300", "section": "non_current_liabilities"},
            {"order": 4, "label": "Lease liabilities (current)",
             "value": "50", "section": "current_liabilities"},
            {"order": 5, "label": "Total equity",
             "value": "400", "section": "equity", "is_subtotal": True},
        ]
        raw = build_raw(bs_lines=bs_lines)
        ctx = make_context(raw, wacc_inputs)
        ic = AnalysisDeriver().derive(ctx).invested_capital_by_period[0]
        assert ic.bank_debt == Decimal("200")
        assert ic.lease_liabilities == Decimal("350")
        # Total financial_liabilities stays the aggregate.
        assert ic.financial_liabilities == Decimal("550")

    def test_equity_bridge_separates_debt_from_leases(self) -> None:
        state = _canonical()
        ic = state.analysis.invested_capital_by_period[0]
        # Simulate real company with both debt and leases.
        state.analysis.invested_capital_by_period[0] = ic.model_copy(
            update={
                "bank_debt": Decimal("100"),
                "lease_liabilities": Decimal("50"),
                "financial_liabilities": Decimal("150"),
            }
        )
        wacc = _wacc_stub_with_bull_bear()
        from portfolio_thesis_engine.valuation.scenarios import ScenarioComposer

        composer = ScenarioComposer(dcf_engine=FCFFDCFEngine(n_years=3))
        scenarios = composer.compose(wacc_inputs=wacc, canonical_state=state)
        base = next(s for s in scenarios if s.label == "base")
        eq = base.equity_bridge
        assert eq is not None
        assert eq.financial_debt == Decimal("100")
        assert eq.lease_liabilities == Decimal("50")


# ======================================================================
# Issue 3 — WC projection
# ======================================================================


class TestWorkingCapitalProjection:
    def test_invested_capital_computes_operating_wc(
        self, wacc_inputs: WACCInputs
    ) -> None:
        bs_lines = [
            {"order": 1, "label": "Cash and cash equivalents",
             "value": "200", "section": "current_assets"},
            {"order": 2, "label": "Trade receivables",
             "value": "100", "section": "current_assets"},
            {"order": 3, "label": "Inventories",
             "value": "50", "section": "current_assets"},
            {"order": 4, "label": "Trade payables",
             "value": "80", "section": "current_liabilities"},
            {"order": 5, "label": "Total equity",
             "value": "270", "section": "equity", "is_subtotal": True},
        ]
        raw = build_raw(bs_lines=bs_lines)
        ctx = make_context(raw, wacc_inputs)
        ic = AnalysisDeriver().derive(ctx).invested_capital_by_period[0]
        # Operating WC = (receivables + inventory) − payables =
        # (100 + 50) − 80 = 70. Cash stays out.
        assert ic.operating_working_capital == Decimal("70")

    def test_wc_projection_uses_revenue_ratio(self) -> None:
        # Build a state with WC ratio 10 % of revenue.
        state = _canonical(
            revenue=Decimal("1000"),
            core_op_income=Decimal("100"),
            non_recurring=Decimal("0"),
            amortisation=Decimal("0"),
        )
        ic = state.analysis.invested_capital_by_period[0]
        state.analysis.invested_capital_by_period[0] = ic.model_copy(
            update={"operating_working_capital": Decimal("100")}
        )
        engine = FCFFDCFEngine(n_years=3)
        scenario = _scenario_stub(
            cagr=Decimal("10"), tg=Decimal("2"), tm=Decimal("10")
        )
        _, detail = engine.project_fcff(scenario, state)
        # Revenue grows 10 % → 1100 → 1210 → 1331.
        # WC at 10 % of revenue: 110 → 121 → 133.1.
        # ΔWC: 110 − 100 = 10; 121 − 110 = 11; 133.1 − 121 = 12.1.
        assert abs(detail[1]["wc_change"] - Decimal("10")) < Decimal("0.01")
        assert abs(detail[2]["wc_change"] - Decimal("11")) < Decimal("0.01")
        assert abs(detail[3]["wc_change"] - Decimal("12.1")) < Decimal("0.01")


# ======================================================================
# Issue 4 — CapEx/Revenue ratio
# ======================================================================


class TestCapExRatio:
    def test_capex_revenue_ratio_computed(
        self, wacc_inputs: WACCInputs
    ) -> None:
        """The analysis-side ``_CAPEX_CF`` regex must match "Purchases
        of property, plant and equipment" (plural), not just singular."""
        is_lines = [
            {"order": 1, "label": "Revenue", "value": "1000"},
            {"order": 2, "label": "Operating profit",
             "value": "150", "is_subtotal": True},
            {"order": 3, "label": "Profit for the year",
             "value": "100", "is_subtotal": True},
        ]
        cf_lines = [
            {"order": 1, "label": "Purchases of property, plant and equipment",
             "value": "-120", "section": "investing"},
        ]
        raw = build_raw(is_lines=is_lines, cf_lines=cf_lines)
        ctx = make_context(raw, wacc_inputs)
        ctx.adjustments.append(_op_tax("25"))
        ratios = AnalysisDeriver().derive(ctx).ratios_by_period[0]
        # 120 / 1000 × 100 = 12 %.
        assert ratios.capex_revenue is not None
        assert abs(ratios.capex_revenue - Decimal("12")) < Decimal("0.01")


# ======================================================================
# Issue 5 — identity.name
# ======================================================================


class TestIdentityName:
    def test_identity_name_populated_from_metadata(self) -> None:
        """Given a stale SQLite row whose ``name == ticker``, the
        pipeline must prefer ``metadata.company_name`` (the legal name
        from the extraction). Falls back to the row when the extraction
        omits the name; ticker only as a last resort."""
        from portfolio_thesis_engine.pipeline.coordinator import _identity_from
        from portfolio_thesis_engine.storage.sqlite_repo import CompanyRow

        raw = build_raw(ticker="1846.HK")
        # Stamp a legal name on the extraction metadata.
        raw.metadata.__pydantic_extra__ = getattr(raw.metadata, "__pydantic_extra__", {}) or {}
        raw.metadata.company_name = (
            "EuroEyes International Eye Clinic Limited"
        )
        # Stale SQLite row: name = ticker (common bootstrap state).
        row = CompanyRow(
            ticker="1846.HK",
            name="1846.HK",
            profile="P1",
            currency="HKD",
            exchange="HKEX",
        )
        from portfolio_thesis_engine.schemas.wacc import (
            CapitalStructure,
            CostOfCapitalInputs,
            ScenarioDriversManual,
        )

        wacc = WACCInputs(
            ticker="1846.HK",
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
        identity = _identity_from(row, wacc, raw)
        assert identity.name == "EuroEyes International Eye Clinic Limited"

    def test_identity_name_prefers_extraction_metadata(self) -> None:
        """Extraction metadata's legal name wins over a divergent
        SQLite row (prevents stale bootstrap data from overriding a
        freshly-extracted legal name)."""
        from portfolio_thesis_engine.pipeline.coordinator import _identity_from
        from portfolio_thesis_engine.schemas.wacc import (
            CapitalStructure,
            CostOfCapitalInputs,
            ScenarioDriversManual,
        )
        from portfolio_thesis_engine.storage.sqlite_repo import CompanyRow

        raw = build_raw(ticker="1846.HK")  # default company_name="Test Co"
        row = CompanyRow(
            ticker="1846.HK",
            name="Stale SQLite Name",
            profile="P1",
            currency="HKD",
            exchange="HKEX",
        )
        wacc = WACCInputs(
            ticker="1846.HK",
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
        identity = _identity_from(row, wacc, raw)
        # Metadata wins over the SQLite row.
        assert identity.name == "Test Co"
