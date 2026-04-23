"""Phase 2 Sprint 2A regression tests — analytical layer.

Scope (49 tests):

Part A — Comparative period unpacking (8):
- ``test_comparative_records_flagged_as_comparative``
- ``test_comparative_records_have_revenue_from_is_lines``
- ``test_no_comparative_when_single_reclassified_statement``
- ``test_dedupe_primary_beats_comparative_same_period``
- ``test_dedupe_preserves_only_one_record_per_period``
- ``test_comparative_record_skipped_for_economic_bs``
- ``test_comparative_audit_status_inherited_from_primary_state``
- ``test_comparative_source_ids_reference_parent_state``

Part B — Economic Balance Sheet (7):
- ``test_economic_bs_builder_extracts_ppe``
- ``test_economic_bs_builder_computes_working_capital``
- ``test_economic_bs_builder_ifrs16_lease_operating_treatment``
- ``test_economic_bs_builder_nfp_excludes_leases``
- ``test_economic_bs_builder_separates_goodwill_from_intangibles``
- ``test_economic_bs_builder_returns_none_without_bs_lines``
- ``test_economic_bs_builder_uses_invested_capital_from_analysis``

Part C — DuPont 3-way (5):
- ``test_dupont_returns_none_missing_inputs``
- ``test_dupont_3way_arithmetic``
- ``test_dupont_reconciliation_delta_near_zero``
- ``test_dupont_roe_reported_matches_ni_over_equity``
- ``test_roe_attribution_sums_to_delta_within_cross_residual``

Part D — ROIC decomposition (5):
- ``test_roic_decomposition_returns_none_without_ic``
- ``test_roic_decomposition_two_way_arithmetic``
- ``test_roic_spread_classification_boundaries``
- ``test_roic_wacc_spread_computed_in_bps``
- ``test_roic_attribution_captures_margin_vs_turnover``

Part E — Restatement severity (3):
- ``test_restatement_severity_negligible_threshold``
- ``test_restatement_severity_five_levels``
- ``test_restatement_event_stores_period_relations``

Part F — Trend detection (6):
- ``test_compute_trends_returns_none_under_two_records``
- ``test_compute_trends_revenue_cagr_values``
- ``test_compute_trends_revenue_trajectory_accelerating``
- ``test_compute_trends_margin_delta_in_bps``
- ``test_compute_trends_roic_trajectory_improving``
- ``test_compute_trends_ignores_comparative_records``

Part G — Quality of Earnings (8):
- ``test_qoe_returns_component_scores``
- ``test_qoe_weighted_composite``
- ``test_qoe_missing_component_rescaled_weights``
- ``test_qoe_accruals_flag_when_weak``
- ``test_qoe_cfo_lags_ni_flag``
- ``test_qoe_audit_numeric_mapping``
- ``test_qoe_non_recurring_share_score_boundary``
- ``test_qoe_exposes_all_component_ratios``

Part H — CLI (3):
- ``test_analyze_cli_renders_sections``
- ``test_analyze_cli_exits_when_no_states``
- ``test_analyze_cli_markdown_export_writes_file``

Integration (4):
- ``test_normalize_attaches_analytical_artefacts_on_records``
- ``test_normalize_emits_trends_when_multi_year``
- ``test_normalize_emits_investment_signal``
- ``test_normalize_enriches_economic_bs_for_primary_only``
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from portfolio_thesis_engine.analytical.analyze import (
    _classify_roic_spread,
    attribute_roe_change,
    attribute_roic_change,
    compute_dupont_3way,
    compute_qoe,
    compute_roic_decomposition,
    compute_trends,
    synthesise_investment_signal,
)
from portfolio_thesis_engine.analytical.economic_bs import EconomicBSBuilder
from portfolio_thesis_engine.analytical.historicals import (
    HistoricalNormalizer,
    _classify_restatement_severity,
    _compare_records,
    _dedupe_with_restatements,
)
from portfolio_thesis_engine.cli import analyze_cmd
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
from portfolio_thesis_engine.schemas.historicals import (
    DuPont3Way,
    HistoricalPeriodType,
    HistoricalRecord,
    ROICDecomposition,
)
from portfolio_thesis_engine.schemas.raw_extraction import AuditStatus


# ======================================================================
# Fixtures
# ======================================================================
def _bs_lines(
    *,
    ppe: Decimal = Decimal("500"),
    rou: Decimal = Decimal("100"),
    goodwill: Decimal = Decimal("50"),
    intangibles: Decimal = Decimal("70"),
    ar: Decimal = Decimal("120"),
    inventory: Decimal = Decimal("80"),
    ap: Decimal = Decimal("60"),
    lease_liab: Decimal = Decimal("105"),
    lt_debt: Decimal = Decimal("150"),
    equity_parent: Decimal = Decimal("700"),
) -> list[BalanceSheetLine]:
    return [
        BalanceSheetLine(
            label="Property, plant and equipment",
            value=ppe,
            category="operating",
        ),
        BalanceSheetLine(
            label="Right-of-use assets",
            value=rou,
            category="operating",
        ),
        BalanceSheetLine(
            label="Goodwill",
            value=goodwill,
            category="operating",
        ),
        BalanceSheetLine(
            label="Intangible assets",
            value=intangibles,
            category="operating",
        ),
        BalanceSheetLine(
            label="Trade receivables",
            value=ar,
            category="operating",
        ),
        BalanceSheetLine(
            label="Inventory",
            value=inventory,
            category="operating",
        ),
        BalanceSheetLine(
            label="Trade payables",
            value=ap,
            category="operating",
        ),
        BalanceSheetLine(
            label="Lease liabilities",
            value=lease_liab,
            category="financial",
        ),
        BalanceSheetLine(
            label="Long-term borrowings",
            value=lt_debt,
            category="financial",
        ),
        BalanceSheetLine(
            label="Equity attributable to owners of the parent",
            value=equity_parent,
            category="equity",
            is_adjusted=True,
        ),
    ]


def _canonical_state(
    *,
    ticker: str = "TST.HK",
    period_label: str = "FY2024",
    period_end: date = date(2024, 12, 31),
    revenue: Decimal = Decimal("1000"),
    operating_income: Decimal = Decimal("200"),
    net_income: Decimal = Decimal("140"),
    nopat: Decimal = Decimal("150"),
    total_assets: Decimal = Decimal("1200"),
    total_equity: Decimal = Decimal("700"),
    invested_capital: Decimal = Decimal("870"),
    financial_assets: Decimal = Decimal("50"),
    bank_debt: Decimal = Decimal("150"),
    audit_status: str = "audited",
    document_type: str = "annual_report",
    extraction_suffix: str = "x1",
    comparative_periods: list[tuple[str, date, Decimal, Decimal, Decimal]] | None = None,
    include_bs_lines: bool = True,
) -> CanonicalCompanyState:
    period = FiscalPeriod(year=period_end.year, label=period_label)
    is_lines = [
        IncomeStatementLine(label="Revenue", value=revenue),
        IncomeStatementLine(
            label="Operating profit", value=operating_income
        ),
        IncomeStatementLine(
            label="Profit for the year", value=net_income
        ),
    ]
    bs_lines = _bs_lines() if include_bs_lines else []
    # Add total assets/equity lines for record builder's _first_matching_line
    bs_lines_full = bs_lines + [
        BalanceSheetLine(
            label="Total assets",
            value=total_assets,
            category="subtotal",
            is_adjusted=True,
        ),
        BalanceSheetLine(
            label="Total equity",
            value=total_equity,
            category="subtotal",
            is_adjusted=True,
        ),
    ]
    reclassified = [
        ReclassifiedStatements(
            period=period,
            income_statement=is_lines,
            balance_sheet=bs_lines_full,
            cash_flow=[],
            bs_checksum_pass=True,
            is_checksum_pass=True,
            cf_checksum_pass=True,
        )
    ]
    # Add comparative periods if requested.
    if comparative_periods:
        for (
            comp_label,
            comp_end,
            comp_rev,
            comp_oi,
            comp_ni,
        ) in comparative_periods:
            comp_period = FiscalPeriod(year=comp_end.year, label=comp_label)
            reclassified.append(
                ReclassifiedStatements(
                    period=comp_period,
                    income_statement=[
                        IncomeStatementLine(
                            label="Revenue", value=comp_rev
                        ),
                        IncomeStatementLine(
                            label="Operating profit", value=comp_oi
                        ),
                        IncomeStatementLine(
                            label="Profit for the year", value=comp_ni
                        ),
                    ],
                    balance_sheet=[
                        BalanceSheetLine(
                            label="Total assets",
                            value=total_assets - Decimal("100"),
                            category="subtotal",
                            is_adjusted=True,
                        ),
                        BalanceSheetLine(
                            label="Total equity",
                            value=total_equity - Decimal("50"),
                            category="subtotal",
                            is_adjusted=True,
                        ),
                    ],
                    cash_flow=[],
                    bs_checksum_pass=True,
                    is_checksum_pass=True,
                    cf_checksum_pass=True,
                )
            )
    return CanonicalCompanyState(
        extraction_id=f"{ticker}_{period_label}_{extraction_suffix}",
        extraction_date=datetime(2025, 1, 1, tzinfo=UTC),
        as_of_date=period_end.isoformat(),
        identity=CompanyIdentity(
            ticker=ticker,
            name="Test Co",
            reporting_currency=Currency.HKD,
            profile=Profile.P1_INDUSTRIAL,
            fiscal_year_end_month=period_end.month,
            country_domicile="HK",
            exchange="HKEX",
        ),
        reclassified_statements=reclassified,
        adjustments=AdjustmentsApplied(),
        analysis=AnalysisDerived(
            invested_capital_by_period=[
                InvestedCapital(
                    period=period,
                    operating_assets=total_assets - financial_assets,
                    operating_liabilities=Decimal("0"),
                    invested_capital=invested_capital,
                    financial_assets=financial_assets,
                    financial_liabilities=bank_debt,
                    bank_debt=bank_debt,
                    lease_liabilities=Decimal("105"),
                    equity_claims=total_equity,
                    cross_check_residual=Decimal("0"),
                )
            ],
            nopat_bridge_by_period=[
                NOPATBridge(
                    period=period,
                    ebitda=operating_income + Decimal("50"),
                    operating_income=operating_income,
                    operating_taxes=Decimal("50"),
                    nopat=nopat,
                    financial_income=Decimal("0"),
                    financial_expense=Decimal("10"),
                    non_operating_items=Decimal("0"),
                    reported_net_income=net_income,
                )
            ],
            ratios_by_period=[
                KeyRatios(
                    period=period,
                    roic=Decimal("17.24"),
                    roe=Decimal("20.00"),
                    operating_margin=Decimal("20"),
                    ebitda_margin=Decimal("25"),
                )
            ],
        ),
        validation=ValidationResults(
            universal_checksums=[
                ValidationResult(
                    check_id="V.0",
                    name="ok",
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
            protocols_activated=["A"],
            audit_status=audit_status,
            source_document_type=document_type,
        ),
    )


def _stub_repo(states: list[CanonicalCompanyState]) -> MagicMock:
    repo = MagicMock()
    repo.list_versions = MagicMock(
        return_value=[s.extraction_id for s in states]
    )
    state_map = {s.extraction_id: s for s in states}
    repo.get_version = MagicMock(
        side_effect=lambda ticker, version: state_map.get(version)
    )
    return repo


def _record(
    *,
    period: str = "FY2024",
    period_end: date = date(2024, 12, 31),
    period_type: HistoricalPeriodType = HistoricalPeriodType.ANNUAL,
    period_relation: str = "primary",
    audit_status: AuditStatus = AuditStatus.AUDITED,
    revenue: Decimal | None = Decimal("1000"),
    operating_income: Decimal | None = Decimal("200"),
    net_income: Decimal | None = Decimal("140"),
    total_assets: Decimal | None = Decimal("1200"),
    total_equity: Decimal | None = Decimal("700"),
    nopat: Decimal | None = Decimal("150"),
    invested_capital: Decimal | None = Decimal("870"),
    roic_primary: Decimal | None = Decimal("17.24"),
    operating_margin_reported: Decimal | None = Decimal("20"),
    cash_and_equivalents: Decimal | None = Decimal("50"),
    financial_debt: Decimal | None = Decimal("150"),
    source_id: str = "cs1",
) -> HistoricalRecord:
    return HistoricalRecord(
        period=period,
        period_start=date(period_end.year, 1, 1),
        period_end=period_end,
        period_type=period_type,
        period_relation=period_relation,  # type: ignore[arg-type]
        fiscal_year_basis=f"calendar_{period_end.month:02d}",
        audit_status=audit_status,
        source_canonical_state_id=source_id,
        source_document_type="annual_report",
        source_document_date=period_end,
        revenue=revenue,
        operating_income=operating_income,
        net_income=net_income,
        total_assets=total_assets,
        total_equity=total_equity,
        nopat=nopat,
        invested_capital=invested_capital,
        roic_primary=roic_primary,
        operating_margin_reported=operating_margin_reported,
        cash_and_equivalents=cash_and_equivalents,
        financial_debt=financial_debt,
    )


# ======================================================================
# Part A — Comparative period unpacking
# ======================================================================
class TestComparativeUnpacking:
    def test_comparative_records_flagged_as_comparative(self) -> None:
        state = _canonical_state(
            period_label="FY2024",
            comparative_periods=[
                ("FY2023", date(2023, 12, 31), Decimal("900"), Decimal("170"), Decimal("120")),
            ],
        )
        repo = _stub_repo([state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        # Primary + comparative.
        assert {r.period for r in ts.records} >= {"FY2024", "FY2023"}
        fy2023 = next(r for r in ts.records if r.period == "FY2023")
        assert fy2023.period_relation == "comparative"

    def test_comparative_records_have_revenue_from_is_lines(self) -> None:
        state = _canonical_state(
            period_label="FY2024",
            comparative_periods=[
                ("FY2023", date(2023, 12, 31), Decimal("900"), Decimal("170"), Decimal("120")),
            ],
        )
        repo = _stub_repo([state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        fy2023 = next(r for r in ts.records if r.period == "FY2023")
        assert fy2023.revenue == Decimal("900")
        assert fy2023.operating_income == Decimal("170")
        assert fy2023.net_income == Decimal("120")

    def test_no_comparative_when_single_reclassified_statement(self) -> None:
        state = _canonical_state(period_label="FY2024")
        repo = _stub_repo([state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        assert len(ts.records) == 1
        assert ts.records[0].period_relation == "primary"

    def test_dedupe_primary_beats_comparative_same_period(self) -> None:
        """Comparative from later-year's AR loses to primary record
        emitted by the ``FY2023`` AR itself."""
        state_2024 = _canonical_state(
            ticker="TST.HK",
            period_label="FY2024",
            extraction_suffix="ar2024",
            comparative_periods=[
                ("FY2023", date(2023, 12, 31),
                 Decimal("850"), Decimal("160"), Decimal("110")),
            ],
        )
        state_2023 = _canonical_state(
            ticker="TST.HK",
            period_label="FY2023",
            period_end=date(2023, 12, 31),
            revenue=Decimal("900"),  # primary value (differs from comparative)
            operating_income=Decimal("170"),
            net_income=Decimal("120"),
            extraction_suffix="ar2023",
        )
        repo = _stub_repo([state_2024, state_2023])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        fy2023 = next(r for r in ts.records if r.period == "FY2023")
        # Primary wins → revenue 900, not 850.
        assert fy2023.period_relation == "primary"
        assert fy2023.revenue == Decimal("900")

    def test_dedupe_preserves_only_one_record_per_period(self) -> None:
        state_2024 = _canonical_state(
            period_label="FY2024",
            extraction_suffix="ar2024",
            comparative_periods=[
                ("FY2023", date(2023, 12, 31),
                 Decimal("850"), Decimal("160"), Decimal("110")),
            ],
        )
        state_2023 = _canonical_state(
            period_label="FY2023",
            period_end=date(2023, 12, 31),
            revenue=Decimal("900"),
            extraction_suffix="ar2023",
        )
        repo = _stub_repo([state_2024, state_2023])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        periods = [r.period for r in ts.records]
        assert periods.count("FY2023") == 1
        assert periods.count("FY2024") == 1

    def test_comparative_record_skipped_for_economic_bs(self) -> None:
        """Sprint 2A.1 — comparatives with no BS data keep
        ``economic_balance_sheet = None``. Comparatives with BS line
        items get a BS-only view (see
        ``test_economic_bs_built_for_comparative_when_bs_present``).
        """
        # Build a state whose comparative has empty BS lines.
        state = _canonical_state(period_label="FY2024")
        # Attach an empty-BS comparative manually.
        period_fy23 = FiscalPeriod(year=2023, label="FY2023")
        comparative_rs = ReclassifiedStatements(
            period=period_fy23,
            income_statement=[
                IncomeStatementLine(label="Revenue", value=Decimal("900")),
                IncomeStatementLine(label="Operating profit", value=Decimal("170")),
                IncomeStatementLine(label="Profit for the year", value=Decimal("120")),
            ],
            balance_sheet=[],
            cash_flow=[],
            bs_checksum_pass=True,
            is_checksum_pass=True,
            cf_checksum_pass=True,
        )
        state_with_empty_comp_bs = CanonicalCompanyState(
            **{
                **state.model_dump(),
                "reclassified_statements": [
                    state.reclassified_statements[0],
                    comparative_rs,
                ],
            }
        )
        repo = _stub_repo([state_with_empty_comp_bs])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        fy2023 = next(r for r in ts.records if r.period == "FY2023")
        assert fy2023.period_relation == "comparative"
        assert fy2023.economic_balance_sheet is None

    def test_comparative_audit_status_inherited_from_primary_state(
        self,
    ) -> None:
        state = _canonical_state(
            period_label="FY2024",
            audit_status="audited",
            comparative_periods=[
                ("FY2023", date(2023, 12, 31), Decimal("900"),
                 Decimal("170"), Decimal("120")),
            ],
        )
        repo = _stub_repo([state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        fy2023 = next(r for r in ts.records if r.period == "FY2023")
        assert fy2023.audit_status == AuditStatus.AUDITED

    def test_comparative_source_ids_reference_parent_state(self) -> None:
        state = _canonical_state(
            period_label="FY2024",
            extraction_suffix="parent-id",
            comparative_periods=[
                ("FY2023", date(2023, 12, 31), Decimal("900"),
                 Decimal("170"), Decimal("120")),
            ],
        )
        repo = _stub_repo([state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        fy2023 = next(r for r in ts.records if r.period == "FY2023")
        assert fy2023.source_canonical_state_id == state.extraction_id


# ======================================================================
# Part B — Economic Balance Sheet
# ======================================================================
class TestEconomicBalanceSheet:
    def _state(self, **kwargs: object) -> CanonicalCompanyState:
        return _canonical_state(**kwargs)  # type: ignore[arg-type]

    def test_economic_bs_builder_extracts_ppe(self) -> None:
        state = self._state()
        bs = EconomicBSBuilder().build(state)
        assert bs is not None
        assert bs.operating_ppe_net == Decimal("500")

    def test_economic_bs_builder_computes_working_capital(self) -> None:
        state = self._state()
        bs = EconomicBSBuilder().build(state)
        assert bs is not None
        # WC = AR + Inventory − AP = 120 + 80 − 60 = 140.
        assert bs.working_capital == Decimal("140")

    def test_economic_bs_builder_ifrs16_lease_operating_treatment(
        self,
    ) -> None:
        """ROU assets should surface as operating, lease liabilities
        exposed separately (NOT in NFP)."""
        state = self._state()
        bs = EconomicBSBuilder().build(state)
        assert bs is not None
        assert bs.rou_assets == Decimal("100")
        assert bs.lease_liabilities == Decimal("105")

    def test_economic_bs_builder_nfp_excludes_leases(self) -> None:
        state = self._state()
        bs = EconomicBSBuilder().build(state)
        assert bs is not None
        # NFP = cash − financial_debt = 50 − 150 = -100. Leases NOT
        # included.
        assert bs.net_financial_position == Decimal("-100")

    def test_economic_bs_builder_separates_goodwill_from_intangibles(
        self,
    ) -> None:
        """Sprint 2B Part B fix — when "Goodwill" and "Intangible
        assets" are distinct BS rows, the intangibles aggregator must
        exclude goodwill (not double-subtract it)."""
        state = self._state()
        bs = EconomicBSBuilder().build(state)
        assert bs is not None
        assert bs.goodwill == Decimal("50")
        # operating_intangibles = 70 (Intangible assets only; goodwill
        # excluded by regex since it's on a separate row).
        assert bs.operating_intangibles == Decimal("70")

    def test_economic_bs_builder_returns_none_without_bs_lines(self) -> None:
        state = _canonical_state(include_bs_lines=False)
        # Strip the subtotal lines too.
        # Use a fresh state with completely empty BS.
        state = CanonicalCompanyState(
            **{
                **state.model_dump(),
                "reclassified_statements": [
                    ReclassifiedStatements(
                        period=FiscalPeriod(year=2024, label="FY2024"),
                        income_statement=[],
                        balance_sheet=[],
                        cash_flow=[],
                        bs_checksum_pass=True,
                        is_checksum_pass=True,
                        cf_checksum_pass=True,
                    )
                ],
            }
        )
        assert EconomicBSBuilder().build(state) is None

    def test_economic_bs_builder_uses_invested_capital_from_analysis(
        self,
    ) -> None:
        state = self._state(invested_capital=Decimal("999"))
        bs = EconomicBSBuilder().build(state)
        assert bs is not None
        assert bs.invested_capital == Decimal("999")


# ======================================================================
# Part C — DuPont 3-way
# ======================================================================
class TestDuPont3Way:
    def test_dupont_returns_none_missing_inputs(self) -> None:
        r = _record(total_assets=None)
        assert compute_dupont_3way(r) is None

    def test_dupont_3way_arithmetic(self) -> None:
        r = _record(
            revenue=Decimal("1000"),
            net_income=Decimal("140"),
            total_assets=Decimal("1200"),
            total_equity=Decimal("700"),
        )
        d = compute_dupont_3way(r)
        assert d is not None
        # net_margin = 140/1000 = 14 %
        assert d.net_margin == Decimal("14")
        # asset_turnover = 1000/1200 ≈ 0.8333
        assert d.asset_turnover is not None
        assert abs(d.asset_turnover - Decimal("0.8333")) < Decimal("0.001")
        # leverage = 1200/700 ≈ 1.7142
        assert d.financial_leverage is not None
        assert abs(d.financial_leverage - Decimal("1.7142")) < Decimal("0.001")

    def test_dupont_reconciliation_delta_near_zero(self) -> None:
        r = _record(
            revenue=Decimal("1000"),
            net_income=Decimal("140"),
            total_assets=Decimal("1200"),
            total_equity=Decimal("700"),
        )
        d = compute_dupont_3way(r)
        assert d is not None
        assert d.reconciliation_delta is not None
        assert abs(d.reconciliation_delta) < Decimal("0.01")

    def test_dupont_roe_reported_matches_ni_over_equity(self) -> None:
        r = _record(
            revenue=Decimal("1000"),
            net_income=Decimal("140"),
            total_assets=Decimal("1200"),
            total_equity=Decimal("700"),
        )
        d = compute_dupont_3way(r)
        # 140/700 = 20 %
        assert d is not None
        assert d.roe_reported == Decimal("20")

    def test_roe_attribution_sums_to_delta_within_cross_residual(
        self,
    ) -> None:
        r_a = _record(
            period="FY2023",
            revenue=Decimal("900"),
            net_income=Decimal("100"),
            total_assets=Decimal("1000"),
            total_equity=Decimal("650"),
        )
        r_b = _record(
            period="FY2024",
            revenue=Decimal("1000"),
            net_income=Decimal("140"),
            total_assets=Decimal("1200"),
            total_equity=Decimal("700"),
        )
        d_a = compute_dupont_3way(r_a)
        d_b = compute_dupont_3way(r_b)
        assert d_a is not None and d_b is not None
        attr = attribute_roe_change(d_a, d_b)
        assert attr is not None
        # margin + turnover + leverage + cross_residual == delta
        total = (
            attr.margin_contribution_bps
            + attr.turnover_contribution_bps
            + attr.leverage_contribution_bps
            + attr.cross_residual_bps
        )
        assert abs(total - attr.roe_delta_bps) < Decimal("1")


# ======================================================================
# Part D — ROIC decomposition
# ======================================================================
class TestROICDecomposition:
    def test_roic_decomposition_returns_none_without_ic(self) -> None:
        r = _record(invested_capital=None)
        assert compute_roic_decomposition(r) is None

    def test_roic_decomposition_two_way_arithmetic(self) -> None:
        r = _record(
            revenue=Decimal("1000"),
            nopat=Decimal("150"),
            invested_capital=Decimal("870"),
        )
        d = compute_roic_decomposition(r)
        assert d is not None
        assert d.nopat_margin == Decimal("15")  # 150/1000
        # ic_turnover = 1000/870 ≈ 1.1494
        assert d.ic_turnover is not None
        assert abs(d.ic_turnover - Decimal("1.1494")) < Decimal("0.001")
        # ROIC ≈ 15% × 1.1494 = 17.24
        assert d.roic_computed is not None
        assert abs(d.roic_computed - Decimal("17.24")) < Decimal("0.1")

    def test_roic_spread_classification_boundaries(self) -> None:
        assert _classify_roic_spread(Decimal("-200")) == "DESTROYING"
        assert _classify_roic_spread(Decimal("0")) == "NEUTRAL"
        assert _classify_roic_spread(Decimal("100")) == "NEUTRAL"
        assert _classify_roic_spread(Decimal("300")) == "MODEST"
        assert _classify_roic_spread(Decimal("600")) == "STRONG"

    def test_roic_wacc_spread_computed_in_bps(self) -> None:
        r = _record(
            revenue=Decimal("1000"),
            nopat=Decimal("150"),
            invested_capital=Decimal("870"),
        )
        d = compute_roic_decomposition(r, wacc_pct=Decimal("10"))
        assert d is not None
        assert d.wacc == Decimal("10")
        # ROIC ≈ 17.24 %; spread vs 10 % = 7.24 pp = 724 bps.
        assert d.spread_bps is not None
        assert abs(d.spread_bps - Decimal("724")) < Decimal("5")
        assert d.value_signal == "STRONG"

    def test_roic_attribution_captures_margin_vs_turnover(self) -> None:
        d_a = ROICDecomposition(
            period="FY2023",
            nopat_margin=Decimal("10"),
            ic_turnover=Decimal("1.0"),
            roic_computed=Decimal("10"),
        )
        d_b = ROICDecomposition(
            period="FY2024",
            nopat_margin=Decimal("15"),
            ic_turnover=Decimal("1.2"),
            roic_computed=Decimal("18"),
        )
        attr = attribute_roic_change(d_a, d_b)
        assert attr is not None
        assert attr.roic_delta_bps == Decimal("800")
        # margin_contribution = ΔMargin × old_turnover = 5 × 1.0 = 5 pp = 500 bps
        assert attr.nopat_margin_contribution_bps == Decimal("500")
        # turnover_contribution = old_margin × ΔTurnover = 10 × 0.2 = 2 pp = 200 bps
        assert attr.ic_turnover_contribution_bps == Decimal("200")


# ======================================================================
# Part E — Restatement severity
# ======================================================================
class TestRestatementSeverity:
    def test_restatement_severity_negligible_threshold(self) -> None:
        assert _classify_restatement_severity(Decimal("0.2")) == "NEGLIGIBLE"
        assert _classify_restatement_severity(Decimal("0.49")) == "NEGLIGIBLE"

    def test_restatement_severity_five_levels(self) -> None:
        assert _classify_restatement_severity(Decimal("0.6")) == "MINOR"
        assert _classify_restatement_severity(Decimal("2.5")) == "MATERIAL"
        assert _classify_restatement_severity(Decimal("7")) == "SIGNIFICANT"
        assert _classify_restatement_severity(Decimal("15")) == "ADVERSE"

    def test_restatement_event_stores_period_relations(self) -> None:
        primary = _record(
            period="FY2024",
            revenue=Decimal("1000"),
            source_id="audited",
            audit_status=AuditStatus.AUDITED,
            period_relation="primary",
        )
        comparative = _record(
            period="FY2024",
            revenue=Decimal("950"),
            source_id="comp-source",
            audit_status=AuditStatus.AUDITED,
            period_relation="comparative",
        )
        events = _compare_records(primary, comparative)
        assert len(events) == 1
        assert events[0].source_a_period_relation == "comparative"
        assert events[0].source_b_period_relation == "primary"


# ======================================================================
# Part F — Trend detection
# ======================================================================
class TestTrendDetection:
    def test_compute_trends_returns_none_under_two_records(self) -> None:
        records = [_record(period="FY2024")]
        assert compute_trends(records) is None

    def test_compute_trends_revenue_cagr_values(self) -> None:
        records = [
            _record(
                period=f"FY{year}",
                period_end=date(year, 12, 31),
                revenue=Decimal(str(rev)),
            )
            for year, rev in [
                (2020, 500),
                (2021, 600),
                (2022, 720),
                (2023, 850),
                (2024, 1000),
            ]
        ]
        trends = compute_trends(records)
        assert trends is not None
        # 2Y CAGR uses annuals[-3] (2022, 720) → end (2024, 1000)
        # CAGR_2y = (1000/720)^(1/2) − 1 ≈ 17.8 %
        assert trends.revenue_cagr_2y is not None
        assert abs(trends.revenue_cagr_2y - Decimal("17.85")) < Decimal("0.2")

    def test_compute_trends_revenue_trajectory_accelerating(self) -> None:
        records = [
            _record(
                period="FY2020",
                period_end=date(2020, 12, 31),
                revenue=Decimal("500"),
            ),
            _record(
                period="FY2021",
                period_end=date(2021, 12, 31),
                revenue=Decimal("510"),
            ),
            _record(
                period="FY2022",
                period_end=date(2022, 12, 31),
                revenue=Decimal("520"),
            ),
            # Steep acceleration in recent window.
            _record(
                period="FY2023",
                period_end=date(2023, 12, 31),
                revenue=Decimal("700"),
            ),
            _record(
                period="FY2024",
                period_end=date(2024, 12, 31),
                revenue=Decimal("1000"),
            ),
        ]
        trends = compute_trends(records)
        assert trends is not None
        assert trends.revenue_trajectory == "ACCELERATING"

    def test_compute_trends_margin_delta_in_bps(self) -> None:
        records = [
            _record(
                period="FY2023",
                period_end=date(2023, 12, 31),
                operating_margin_reported=Decimal("15"),
            ),
            _record(
                period="FY2024",
                period_end=date(2024, 12, 31),
                operating_margin_reported=Decimal("20"),
            ),
        ]
        trends = compute_trends(records)
        assert trends is not None
        # (20 − 15) × 100 bps = 500 bps.
        assert trends.operating_margin_delta_bps == Decimal("500")
        assert trends.operating_margin_trajectory == "EXPANDING"

    def test_compute_trends_roic_trajectory_improving(self) -> None:
        records = [
            _record(
                period="FY2023",
                period_end=date(2023, 12, 31),
                roic_primary=Decimal("10"),
            ),
            _record(
                period="FY2024",
                period_end=date(2024, 12, 31),
                roic_primary=Decimal("15"),
            ),
        ]
        trends = compute_trends(records)
        assert trends is not None
        assert trends.roic_delta_bps == Decimal("500")
        assert trends.roic_trajectory == "IMPROVING"

    def test_compute_trends_includes_comparative_annuals(self) -> None:
        """Sprint 2A.1 — comparatives from a neighbouring AR's prior-
        year column are still annual audited observations. They
        contribute to CAGR / YoY like any other annual record."""
        comp = _record(
            period="FY2023",
            period_end=date(2023, 12, 31),
            period_relation="comparative",
            revenue=Decimal("900"),
        )
        primary = _record(
            period="FY2024",
            period_end=date(2024, 12, 31),
            revenue=Decimal("1000"),
        )
        trends = compute_trends([comp, primary])
        assert trends is not None
        assert trends.annuals_used_for_cagr == 2
        # YoY = (1000 / 900 - 1) × 100 ≈ 11.11 %
        assert trends.revenue_yoy_growth is not None
        assert abs(trends.revenue_yoy_growth - Decimal("11.11")) < Decimal("0.1")


# ======================================================================
# Part G — Quality of Earnings
# ======================================================================
class TestQualityOfEarnings:
    def test_qoe_returns_component_scores(self) -> None:
        r = _record()
        qoe = compute_qoe(
            r,
            cfo=Decimal("155"),
            prior_revenue=Decimal("900"),
            prior_ar=Decimal("100"),
            non_recurring_items_share=Decimal("0.10"),
        )
        assert qoe.period == "FY2024"
        assert qoe.accruals_quality_score is not None
        assert qoe.cfo_ni_score is not None
        assert qoe.non_recurring_score is not None
        assert qoe.audit_score is not None
        assert qoe.composite_score is not None

    def test_qoe_weighted_composite(self) -> None:
        r = _record()
        qoe = compute_qoe(
            r,
            cfo=Decimal("155"),
            non_recurring_items_share=Decimal("0.10"),
        )
        # With audit=AUDITED → audit_score 100, non-rec 100, accruals
        # well-behaved, cfo/ni ≈ 1.1 → ≥ 1 → 100. Composite should be high.
        assert qoe.composite_score is not None
        assert qoe.composite_score >= 80

    def test_qoe_missing_component_rescaled_weights(self) -> None:
        r = _record()
        # All components absent except audit → composite should still
        # be populated because audit alone is available.
        qoe = compute_qoe(r)
        # audit_score=100 with AUDITED; all other components None.
        assert qoe.audit_score == 100
        assert qoe.composite_score == 100

    def test_qoe_accruals_flag_when_weak(self) -> None:
        """Large accruals_to_assets → WEAK_ACCRUALS_QUALITY flag."""
        r = _record(net_income=Decimal("500"), total_assets=Decimal("1000"))
        # net_income 500, cfo 100 → accruals = (500-100)/1000 = 0.4 → ratio
        # well above 0.15 threshold → score 30 → flag set.
        qoe = compute_qoe(
            r,
            cfo=Decimal("100"),
            non_recurring_items_share=Decimal("0.10"),
        )
        assert "WEAK_ACCRUALS_QUALITY" in qoe.flags

    def test_qoe_cfo_lags_ni_flag(self) -> None:
        r = _record(net_income=Decimal("100"), total_assets=Decimal("1000"))
        # cfo 50 vs NI 100 → ratio 0.5 → score 40 → flag set.
        qoe = compute_qoe(
            r,
            cfo=Decimal("50"),
            non_recurring_items_share=Decimal("0.10"),
        )
        assert "CFO_LAGS_NI" in qoe.flags

    def test_qoe_audit_numeric_mapping(self) -> None:
        r_audited = _record(audit_status=AuditStatus.AUDITED)
        r_reviewed = _record(audit_status=AuditStatus.REVIEWED)
        r_unaudited = _record(audit_status=AuditStatus.UNAUDITED)
        q_a = compute_qoe(r_audited)
        q_r = compute_qoe(r_reviewed)
        q_u = compute_qoe(r_unaudited)
        assert q_a.audit_status_numeric == Decimal("1.0")
        assert q_r.audit_status_numeric == Decimal("0.7")
        assert q_u.audit_status_numeric == Decimal("0.4")

    def test_qoe_non_recurring_share_score_boundary(self) -> None:
        r = _record()
        q_low = compute_qoe(r, non_recurring_items_share=Decimal("0.15"))
        q_high = compute_qoe(r, non_recurring_items_share=Decimal("0.70"))
        assert q_low.non_recurring_score == 100
        assert q_high.non_recurring_score == 25
        assert "HIGH_NON_RECURRING_SHARE" in q_high.flags

    def test_qoe_exposes_all_component_ratios(self) -> None:
        r = _record(
            net_income=Decimal("140"),
            total_assets=Decimal("1200"),
        )
        qoe = compute_qoe(
            r,
            cfo=Decimal("150"),
            non_recurring_items_share=Decimal("0.12"),
        )
        assert qoe.accruals_to_assets is not None
        assert qoe.cfo_to_ni_ratio is not None
        assert qoe.non_recurring_items_share == Decimal("0.12")
        assert qoe.audit_status_numeric is not None


# ======================================================================
# Part H — CLI
# ======================================================================
class TestAnalyzeCLI:
    def test_analyze_cli_renders_sections(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state = _canonical_state(
            period_label="FY2024",
            comparative_periods=[
                ("FY2023", date(2023, 12, 31), Decimal("900"),
                 Decimal("170"), Decimal("120")),
            ],
        )
        repo = _stub_repo([state])
        normalizer = HistoricalNormalizer(state_repo=repo)
        buf = io.StringIO()
        test_console = Console(file=buf, width=240, record=True)
        monkeypatch.setattr(analyze_cmd, "console", test_console)
        analyze_cmd._run_analyze(
            "TST.HK", export=None, normalizer=normalizer
        )
        rendered = buf.getvalue()
        assert "FY2024" in rendered
        assert "DuPont" in rendered or "ROE" in rendered
        assert "ROIC" in rendered

    def test_analyze_cli_exits_when_no_states(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = MagicMock()
        repo.list_versions = MagicMock(return_value=[])
        normalizer = HistoricalNormalizer(state_repo=repo)
        buf = io.StringIO()
        test_console = Console(file=buf, width=120)
        monkeypatch.setattr(analyze_cmd, "console", test_console)
        import typer

        with pytest.raises(typer.Exit):
            analyze_cmd._run_analyze(
                "NOPE", export=None, normalizer=normalizer
            )

    def test_analyze_cli_markdown_export_writes_file(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        state = _canonical_state(period_label="FY2024")
        repo = _stub_repo([state])
        normalizer = HistoricalNormalizer(state_repo=repo)
        buf = io.StringIO()
        test_console = Console(file=buf, width=240)
        monkeypatch.setattr(analyze_cmd, "console", test_console)
        out_file = tmp_path / "analytical.md"
        analyze_cmd._run_analyze(
            "TST.HK", export=out_file, normalizer=normalizer
        )
        assert out_file.exists()
        text = out_file.read_text()
        assert "Analytical report" in text
        assert "FY2024" in text


# ======================================================================
# Integration
# ======================================================================
class TestIntegration:
    def test_normalize_attaches_analytical_artefacts_on_records(self) -> None:
        state = _canonical_state(period_label="FY2024")
        repo = _stub_repo([state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        primary = next(r for r in ts.records if r.period_relation == "primary")
        assert primary.dupont_3way is not None
        assert primary.roic_decomposition is not None
        assert primary.quality_of_earnings is not None
        assert primary.economic_balance_sheet is not None

    def test_normalize_emits_trends_when_multi_year(self) -> None:
        states = [
            _canonical_state(
                period_label="FY2022",
                period_end=date(2022, 12, 31),
                revenue=Decimal("800"),
                operating_income=Decimal("150"),
                net_income=Decimal("100"),
                extraction_suffix="a",
            ),
            _canonical_state(
                period_label="FY2023",
                period_end=date(2023, 12, 31),
                revenue=Decimal("900"),
                operating_income=Decimal("170"),
                net_income=Decimal("120"),
                extraction_suffix="b",
            ),
            _canonical_state(
                period_label="FY2024",
                period_end=date(2024, 12, 31),
                revenue=Decimal("1000"),
                extraction_suffix="c",
            ),
        ]
        repo = _stub_repo(states)
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        assert ts.trends is not None
        assert ts.trends.period_start == "FY2022"
        assert ts.trends.period_end == "FY2024"

    def test_normalize_emits_investment_signal(self) -> None:
        states = [
            _canonical_state(
                period_label="FY2023",
                period_end=date(2023, 12, 31),
                revenue=Decimal("900"),
                extraction_suffix="a",
            ),
            _canonical_state(
                period_label="FY2024",
                period_end=date(2024, 12, 31),
                extraction_suffix="b",
            ),
        ]
        repo = _stub_repo(states)
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        assert ts.investment_signal is not None
        # balance_sheet_strength should classify — debt 150 / cash 50 = 3.0
        # → ≥ 2 → WEAK.
        assert ts.investment_signal.balance_sheet_strength == "WEAK"

    def test_normalize_enriches_economic_bs_for_comparative_with_bs_data(
        self,
    ) -> None:
        """Sprint 2A.1 — comparatives with a populated balance sheet get
        a BS-only Economic BS (no IC, no cross-check residual)."""
        state = _canonical_state(
            period_label="FY2024",
            comparative_periods=[
                ("FY2023", date(2023, 12, 31), Decimal("900"),
                 Decimal("170"), Decimal("120")),
            ],
        )
        repo = _stub_repo([state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        primary = next(r for r in ts.records if r.period == "FY2024")
        comparative = next(r for r in ts.records if r.period == "FY2023")
        assert primary.economic_balance_sheet is not None
        assert comparative.economic_balance_sheet is not None
        # Primary uses InvestedCapital block → invested_capital populated.
        assert primary.economic_balance_sheet.invested_capital is not None
        # Sprint 2B Polish 1: comparatives aggregate IC from operating-
        # side line items when present. This fixture's comparative BS
        # only carries subtotal rows (no PPE/goodwill lines), so IC
        # stays None — but cross_check_residual is always None for
        # comparatives regardless.
        assert comparative.economic_balance_sheet.cross_check_residual is None


# ======================================================================
# Investment signal smoke
# ======================================================================
def test_synthesise_investment_signal_minimal() -> None:
    """Direct unit test with no records → signal still returned with
    default UNKNOWN / STABLE values (no crash)."""
    signal = synthesise_investment_signal(
        records=[], trends=None, latest_roic_decomposition=None, latest_qoe=None
    )
    assert signal.current_value_creation == "NEUTRAL"
    assert signal.balance_sheet_strength == "UNKNOWN"
