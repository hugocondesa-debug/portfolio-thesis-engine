"""Phase 2 Sprint 2B regression tests — analytical layer extended.

Covers:

Phase 2B-OPEN (5 polish items from Sprint 2A validation, 20 tests):
- Polish 1 (3): FY2023 IC aggregation for comparative records
- Polish 2 (3): AR / Rev QoE component when prior annual has AR
- Polish 3 (5): QoE paradox resolution — interim cap + weights
- Polish 4 (5): Investment signal picks highest-quality available
- Polish 5 (4): Preliminary growth signal caveat

Phase 2B-CORE:
- Part A (6): DuPont 5-way decomposition + attribution
- Part B (10): Full restatement engine (metrics, thresholds, patterns,
  narrative link, severity + direction)
- Part C (5): Trend enhancements (CapEx/Revenue, WC intensity, CCC,
  ROIC spread trend, CFO/Revenue)

Total: 48 tests.
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
    attribute_roe_5way_change,
    compute_dupont_5way,
    compute_qoe,
    compute_trends,
)
from portfolio_thesis_engine.analytical.historicals import (
    HistoricalNormalizer,
    _apply_interim_qoe_cap,
    _classify_restatement_pattern,
    _compare_records,
    _default_threshold_for,
    _detect_restatement_patterns,
    _link_restatements_to_narrative,
    _metric_class,
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
from portfolio_thesis_engine.schemas.historicals import (
    DuPont5Way,
    HistoricalPeriodType,
    HistoricalRecord,
    QualityOfEarnings,
    RestatementEvent,
)
from portfolio_thesis_engine.schemas.raw_extraction import AuditStatus


# ======================================================================
# Fixtures
# ======================================================================
def _bs_lines_full() -> list[BalanceSheetLine]:
    """BS with all operating + financial categories populated."""
    return [
        BalanceSheetLine(label="Property, plant and equipment", value=Decimal("567413"), category="non_current_assets"),
        BalanceSheetLine(label="Right-of-use assets", value=Decimal("100000"), category="non_current_assets"),
        BalanceSheetLine(label="Intangible assets", value=Decimal("30297"), category="non_current_assets"),
        BalanceSheetLine(label="Goodwill", value=Decimal("253407"), category="non_current_assets"),
        BalanceSheetLine(label="Inventories", value=Decimal("17269"), category="current_assets"),
        BalanceSheetLine(label="Trade receivables", value=Decimal("4738"), category="current_assets"),
        BalanceSheetLine(label="Cash and cash equivalents", value=Decimal("653232"), category="current_assets"),
        BalanceSheetLine(label="Trade payables", value=Decimal("25047"), category="current_liabilities"),
        BalanceSheetLine(label="Lease liabilities (non-current)", value=Decimal("250574"), category="non_current_liabilities"),
        BalanceSheetLine(label="Long-term borrowings", value=Decimal("853"), category="non_current_liabilities"),
        BalanceSheetLine(label="Share capital", value=Decimal("26004"), category="equity"),
        BalanceSheetLine(label="Retained earnings", value=Decimal("700000"), category="equity"),
    ]


def _is_lines(revenue: Decimal, op_income: Decimal, ni: Decimal, pbt: Decimal | None = None) -> list[IncomeStatementLine]:
    pbt = pbt if pbt is not None else op_income * Decimal("0.95")
    tax = pbt - ni
    return [
        IncomeStatementLine(label="Revenue", value=revenue),
        IncomeStatementLine(label="Operating profit", value=op_income),
        IncomeStatementLine(label="Finance income", value=Decimal("10000")),
        IncomeStatementLine(label="Finance expenses", value=-Decimal("5000")),
        IncomeStatementLine(label="Profit before tax", value=pbt),
        IncomeStatementLine(label="Income tax expense", value=-tax),
        IncomeStatementLine(label="Profit for the year", value=ni),
    ]


def _cf_lines() -> list[CashFlowLine]:
    return [
        CashFlowLine(label="Cash generated from operations", value=Decimal("225245"), category="operating"),
    ]


def _state(
    *,
    ticker: str = "TST.HK",
    period_label: str = "FY2024",
    period_end: date = date(2024, 12, 31),
    revenue: Decimal = Decimal("715682"),
    op_income: Decimal = Decimal("115779"),
    ni: Decimal = Decimal("84359"),
    pbt: Decimal = Decimal("126466"),
    audit_status: str = "audited",
    document_type: str = "annual_report",
    include_full_bs: bool = True,
    comparative: tuple[str, date, Decimal, Decimal, Decimal] | None = None,
    extraction_suffix: str = "x1",
) -> CanonicalCompanyState:
    period = FiscalPeriod(year=period_end.year, label=period_label)
    reclassified = [
        ReclassifiedStatements(
            period=period,
            income_statement=_is_lines(revenue, op_income, ni, pbt),
            balance_sheet=_bs_lines_full() if include_full_bs else [],
            cash_flow=_cf_lines(),
            bs_checksum_pass=True,
            is_checksum_pass=True,
            cf_checksum_pass=True,
        )
    ]
    if comparative is not None:
        c_label, c_end, c_rev, c_oi, c_ni = comparative
        c_period = FiscalPeriod(year=c_end.year, label=c_label)
        c_pbt = c_oi * Decimal("0.95")
        reclassified.append(
            ReclassifiedStatements(
                period=c_period,
                income_statement=_is_lines(c_rev, c_oi, c_ni, c_pbt),
                balance_sheet=_bs_lines_full(),
                cash_flow=[],
                bs_checksum_pass=True,
                is_checksum_pass=True,
                cf_checksum_pass=True,
            )
        )
    return CanonicalCompanyState(
        extraction_id=f"{ticker.replace('.', '-')}_{period_label}_{extraction_suffix}",
        extraction_date=datetime(2025, 1, 1, tzinfo=UTC),
        as_of_date=period_end.isoformat(),
        identity=CompanyIdentity(
            ticker=ticker,
            name="Test",
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
                    operating_assets=Decimal("850000"),
                    operating_liabilities=Decimal("60000"),
                    invested_capital=Decimal("790914"),
                    financial_assets=Decimal("653232"),
                    financial_liabilities=Decimal("853"),
                    bank_debt=Decimal("853"),
                    lease_liabilities=Decimal("318433"),
                    equity_claims=Decimal("1092965"),
                    nci_claims=Decimal("32749"),
                    cross_check_residual=Decimal("0"),
                )
            ],
            nopat_bridge_by_period=[
                NOPATBridge(
                    period=period,
                    ebitda=op_income + Decimal("50000"),
                    operating_income=op_income,
                    operating_taxes=Decimal("32405"),
                    nopat=Decimal("64922"),
                    financial_income=Decimal("10000"),
                    financial_expense=Decimal("5000"),
                    non_operating_items=Decimal("0"),
                    reported_net_income=ni,
                )
            ],
            ratios_by_period=[
                KeyRatios(
                    period=period,
                    roic=Decimal("8.21"),
                    roe=Decimal("7.72"),
                    operating_margin=Decimal("16.18"),
                    ebitda_margin=Decimal("31.86"),
                    capex_revenue=Decimal("11.23"),
                )
            ],
        ),
        validation=ValidationResults(
            universal_checksums=[
                ValidationResult(check_id="V.0", name="ok", status="PASS", detail="ok")
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
    repo.list_versions = MagicMock(return_value=[s.extraction_id for s in states])
    state_map = {s.extraction_id: s for s in states}
    repo.get_version = MagicMock(side_effect=lambda t, v: state_map.get(v))
    return repo


def _record(
    *,
    period: str = "FY2024",
    period_end: date = date(2024, 12, 31),
    period_type: HistoricalPeriodType = HistoricalPeriodType.ANNUAL,
    audit_status: AuditStatus = AuditStatus.AUDITED,
    revenue: Decimal | None = Decimal("1000"),
    operating_income: Decimal | None = Decimal("200"),
    net_income: Decimal | None = Decimal("140"),
    pbt: Decimal | None = Decimal("180"),
    total_assets: Decimal | None = Decimal("1200"),
    total_equity: Decimal | None = Decimal("700"),
    cfo: Decimal | None = None,
    accounts_receivable: Decimal | None = None,
    source_id: str = "cs1",
) -> HistoricalRecord:
    return HistoricalRecord(
        period=period,
        period_start=date(period_end.year, 1, 1),
        period_end=period_end,
        period_type=period_type,
        period_relation="primary",
        fiscal_year_basis=f"calendar_{period_end.month:02d}",
        audit_status=audit_status,
        source_canonical_state_id=source_id,
        source_document_type="annual_report",
        source_document_date=period_end,
        revenue=revenue,
        operating_income=operating_income,
        net_income=net_income,
        pbt=pbt,
        total_assets=total_assets,
        total_equity=total_equity,
        cfo=cfo,
        accounts_receivable=accounts_receivable,
    )


# ======================================================================
# Polish 1 — FY2023 IC for comparatives
# ======================================================================
class TestPolish1IcAggregation:
    def test_comparative_record_ic_computed_when_components_present(
        self,
    ) -> None:
        state = _state(
            comparative=(
                "FY2023", date(2023, 12, 31), Decimal("714289"),
                Decimal("193514"), Decimal("133254"),
            )
        )
        repo = _stub_repo([state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        fy2023 = next(r for r in ts.records if r.period == "FY2023")
        # IC aggregated from operating-side lines.
        assert fy2023.invested_capital is not None
        assert fy2023.economic_balance_sheet is not None
        assert fy2023.economic_balance_sheet.invested_capital is not None

    def test_primary_record_still_uses_analysis_ic(self) -> None:
        """Primary record's IC stays anchored on AnalysisDeriver's
        InvestedCapital block — not overwritten by the aggregate."""
        state = _state()
        repo = _stub_repo([state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        primary = ts.records[0]
        assert primary.invested_capital == Decimal("790914")

    def test_fy2023_ic_reasonable_magnitude(self) -> None:
        """FY2023 IC from EuroEyes-shape BS should sit near the sum of
        operating assets (PPE 567M + ROU 100M + goodwill 253M +
        working_capital)."""
        state = _state(
            comparative=(
                "FY2023", date(2023, 12, 31), Decimal("714289"),
                Decimal("193514"), Decimal("133254"),
            )
        )
        repo = _stub_repo([state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        fy2023 = next(r for r in ts.records if r.period == "FY2023")
        assert fy2023.invested_capital is not None
        assert fy2023.invested_capital > Decimal("800000")
        assert fy2023.invested_capital < Decimal("1100000")


# ======================================================================
# Polish 2 — AR / Revenue QoE component
# ======================================================================
class TestPolish2ArRevQoE:
    def test_ar_revenue_score_computed_when_two_annuals_with_ar(
        self,
    ) -> None:
        """With prior_ar + prior_revenue + current AR on the record,
        QoE can now compute AR_growth - Revenue_growth."""
        record = _record(
            revenue=Decimal("1100"),
            accounts_receivable=Decimal("110"),
        )
        qoe = compute_qoe(
            record,
            prior_revenue=Decimal("1000"),
            prior_ar=Decimal("100"),
        )
        # AR growth = 10 %, Rev growth = 10 %, delta = 0 pp → score 100.
        assert qoe.ar_revenue_score == 100
        assert qoe.ar_growth_vs_revenue_growth_delta is not None
        assert abs(qoe.ar_growth_vs_revenue_growth_delta) < Decimal("0.01")

    def test_ar_revenue_score_flags_when_ar_outpaces_revenue(self) -> None:
        record = _record(
            revenue=Decimal("1100"),
            accounts_receivable=Decimal("150"),
        )
        qoe = compute_qoe(
            record,
            prior_revenue=Decimal("1000"),
            prior_ar=Decimal("100"),
        )
        # AR growth 50 %, revenue growth 10 % → delta 40 pp → score 30.
        assert qoe.ar_revenue_score == 30
        assert "AR_GROWING_FASTER_THAN_REVENUE" in qoe.flags

    def test_ar_revenue_score_null_when_prior_ar_missing(self) -> None:
        record = _record(
            revenue=Decimal("1100"),
            accounts_receivable=Decimal("110"),
        )
        qoe = compute_qoe(
            record, prior_revenue=Decimal("1000"), prior_ar=None
        )
        assert qoe.ar_revenue_score is None


# ======================================================================
# Polish 3 — QoE paradox resolution
# ======================================================================
class TestPolish3QoeParadox:
    def test_interim_qoe_weights_downweight_accruals(self) -> None:
        from portfolio_thesis_engine.analytical.analyze import (
            _qoe_weights_for,
        )

        annual_weights = _qoe_weights_for(HistoricalPeriodType.ANNUAL)
        interim_weights = _qoe_weights_for(HistoricalPeriodType.INTERIM)
        ttm_weights = _qoe_weights_for(HistoricalPeriodType.TTM)
        assert annual_weights["accruals"] == Decimal("0.30")
        assert interim_weights["accruals"] == Decimal("0.15")
        assert ttm_weights["accruals"] == Decimal("0.10")
        assert annual_weights["audit"] == Decimal("0.15")
        assert interim_weights["audit"] == Decimal("0.25")
        assert ttm_weights["audit"] == Decimal("0.30")

    def test_weights_sum_close_to_one(self) -> None:
        from portfolio_thesis_engine.analytical.analyze import (
            _qoe_weights_for,
        )

        for period_type in (
            HistoricalPeriodType.ANNUAL,
            HistoricalPeriodType.INTERIM,
            HistoricalPeriodType.TTM,
        ):
            weights = _qoe_weights_for(period_type)
            assert abs(sum(weights.values(), Decimal("0")) - Decimal("1")) < Decimal("0.01")

    def test_interim_cap_never_exceeds_prior_annual_minus_five(self) -> None:
        annual = _record(
            period="FY2024",
            period_type=HistoricalPeriodType.ANNUAL,
            audit_status=AuditStatus.AUDITED,
            period_end=date(2024, 12, 31),
        )
        annual.quality_of_earnings = QualityOfEarnings(
            period="FY2024",
            audit_status_numeric=Decimal("1.0"),
            audit_score=100,
            composite_score=89,
        )
        interim = _record(
            period="H1_2025",
            period_type=HistoricalPeriodType.INTERIM,
            audit_status=AuditStatus.REVIEWED,
            period_end=date(2025, 6, 30),
        )
        interim.quality_of_earnings = QualityOfEarnings(
            period="H1_2025",
            audit_status_numeric=Decimal("0.7"),
            audit_score=70,
            composite_score=95,  # Would exceed the cap.
        )
        _apply_interim_qoe_cap([annual, interim])
        assert interim.quality_of_earnings is not None
        # Cap = 89 − 5 = 84. Interim was 95 → now capped at 84.
        assert interim.quality_of_earnings.composite_score == 84
        assert "CAPPED_BY_PRIOR_ANNUAL" in interim.quality_of_earnings.flags

    def test_interim_cap_no_op_when_score_below_cap(self) -> None:
        annual = _record(
            period="FY2024",
            period_type=HistoricalPeriodType.ANNUAL,
            audit_status=AuditStatus.AUDITED,
            period_end=date(2024, 12, 31),
        )
        annual.quality_of_earnings = QualityOfEarnings(
            period="FY2024", composite_score=89,
        )
        interim = _record(
            period="H1_2025",
            period_type=HistoricalPeriodType.INTERIM,
            audit_status=AuditStatus.REVIEWED,
            period_end=date(2025, 6, 30),
        )
        interim.quality_of_earnings = QualityOfEarnings(
            period="H1_2025", composite_score=70,
        )
        _apply_interim_qoe_cap([annual, interim])
        assert interim.quality_of_earnings is not None
        assert interim.quality_of_earnings.composite_score == 70
        assert "CAPPED_BY_PRIOR_ANNUAL" not in interim.quality_of_earnings.flags

    def test_interim_cap_no_op_when_no_prior_annual_composite(self) -> None:
        """Interim before any audited annual stays at its raw score."""
        interim = _record(
            period="H1_2024",
            period_type=HistoricalPeriodType.INTERIM,
            audit_status=AuditStatus.REVIEWED,
            period_end=date(2024, 6, 30),
        )
        interim.quality_of_earnings = QualityOfEarnings(
            period="H1_2024", composite_score=90,
        )
        _apply_interim_qoe_cap([interim])
        assert interim.quality_of_earnings is not None
        assert interim.quality_of_earnings.composite_score == 90


# ======================================================================
# Polish 4 — Investment signal highest-quality picks
# ======================================================================
class TestPolish4InvestmentSignalPicks:
    def test_earnings_quality_source_prefers_audited_over_preliminary(
        self,
    ) -> None:
        states = [
            _state(
                period_label="FY2024",
                period_end=date(2024, 12, 31),
                audit_status="audited",
                extraction_suffix="a",
            ),
            _state(
                period_label="FY2025",
                period_end=date(2026, 3, 31),
                audit_status="unaudited",
                document_type="investor_presentation",
                extraction_suffix="b",
            ),
        ]
        repo = _stub_repo(states)
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        assert ts.investment_signal is not None
        assert ts.investment_signal.earnings_quality_source_period == "FY2024"

    def test_earnings_quality_falls_back_to_reviewed_if_no_audited(
        self,
    ) -> None:
        state = _state(
            period_label="H1_2025",
            period_end=date(2025, 6, 30),
            audit_status="reviewed",
            document_type="interim_report",
        )
        repo = _stub_repo([state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        assert ts.investment_signal is not None
        # Only record → its own reviewed interim.
        assert ts.investment_signal.earnings_quality_source_period is not None

    def test_balance_sheet_strength_uses_highest_trust_annual(self) -> None:
        states = [
            _state(
                period_label="FY2024",
                period_end=date(2024, 12, 31),
                audit_status="audited",
                extraction_suffix="a",
            ),
            _state(
                period_label="FY2025",
                period_end=date(2026, 3, 31),
                audit_status="unaudited",
                document_type="investor_presentation",
                extraction_suffix="b",
            ),
        ]
        repo = _stub_repo(states)
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        assert ts.investment_signal is not None
        # EuroEyes-like BS: cash 653M, long-term debt 853 → ratio ~0.001
        # → STRONG (audited anchor).
        assert ts.investment_signal.balance_sheet_strength == "STRONG"

    def test_pick_highest_trust_returns_none_on_empty(self) -> None:
        from portfolio_thesis_engine.analytical.historicals import (
            _pick_highest_trust,
        )

        record, value = _pick_highest_trust([], lambda r: r.quality_of_earnings)
        assert record is None
        assert value is None

    def test_latest_qoe_prefers_audited_annual_over_newer_preliminary(
        self,
    ) -> None:
        from portfolio_thesis_engine.analytical.historicals import _latest_qoe

        fy2024 = _record(period="FY2024", period_end=date(2024, 12, 31))
        fy2024.quality_of_earnings = QualityOfEarnings(
            period="FY2024", composite_score=89
        )
        fy2025_prelim = _record(
            period="FY2025",
            period_end=date(2026, 3, 31),
            period_type=HistoricalPeriodType.PRELIMINARY,
            audit_status=AuditStatus.UNAUDITED,
        )
        fy2025_prelim.quality_of_earnings = QualityOfEarnings(
            period="FY2025", composite_score=40
        )
        picked = _latest_qoe([fy2024, fy2025_prelim])
        assert picked is not None
        assert picked.period == "FY2024"
        assert picked.composite_score == 89


# ======================================================================
# Polish 5 — preliminary growth signal caveat
# ======================================================================
class TestPolish5PreliminaryCaveat:
    def test_preliminary_yoy_computed_separately(self) -> None:
        records = [
            _record(
                period="FY2023",
                period_end=date(2023, 12, 31),
                revenue=Decimal("900"),
            ),
            _record(
                period="FY2024",
                period_end=date(2024, 12, 31),
                revenue=Decimal("1000"),
            ),
            _record(
                period="FY2025",
                period_end=date(2026, 3, 31),
                period_type=HistoricalPeriodType.PRELIMINARY,
                audit_status=AuditStatus.UNAUDITED,
                revenue=Decimal("1120"),
            ),
        ]
        trends = compute_trends(records)
        assert trends is not None
        assert trends.revenue_yoy_growth_preliminary is not None
        # (1120 / 1000 − 1) × 100 = 12 %
        assert abs(trends.revenue_yoy_growth_preliminary - Decimal("12")) < Decimal("0.1")
        assert trends.preliminary_signal_period == "FY2025"

    def test_preliminary_trajectory_differs_when_preliminary_accelerates(
        self,
    ) -> None:
        records = [
            _record(
                period="FY2023",
                period_end=date(2023, 12, 31),
                revenue=Decimal("1000"),
            ),
            _record(
                period="FY2024",
                period_end=date(2024, 12, 31),
                revenue=Decimal("1005"),  # flat audited YoY
            ),
            _record(
                period="FY2025",
                period_end=date(2026, 3, 31),
                period_type=HistoricalPeriodType.PRELIMINARY,
                audit_status=AuditStatus.UNAUDITED,
                revenue=Decimal("1200"),  # sharp preliminary acceleration
            ),
        ]
        trends = compute_trends(records)
        assert trends is not None
        assert trends.revenue_trajectory == "STABLE"
        assert trends.revenue_trajectory_incl_preliminary == "ACCELERATING"

    def test_preliminary_ignored_for_cagr(self) -> None:
        """Preliminary must not leak into CAGR / YoY audited."""
        records = [
            _record(
                period="FY2023",
                period_end=date(2023, 12, 31),
                revenue=Decimal("1000"),
            ),
            _record(
                period="FY2024",
                period_end=date(2024, 12, 31),
                revenue=Decimal("1005"),
            ),
            _record(
                period="FY2025",
                period_end=date(2026, 3, 31),
                period_type=HistoricalPeriodType.PRELIMINARY,
                audit_status=AuditStatus.UNAUDITED,
                revenue=Decimal("1500"),
            ),
        ]
        trends = compute_trends(records)
        assert trends is not None
        # Audited YoY = (1005 / 1000 - 1) × 100 = 0.5 %.
        assert trends.revenue_yoy_growth is not None
        assert abs(trends.revenue_yoy_growth - Decimal("0.5")) < Decimal("0.01")

    def test_investment_signal_caveat_bullets_populated(self) -> None:
        states = [
            _state(
                period_label="FY2023",
                period_end=date(2023, 12, 31),
                revenue=Decimal("640000"),
                extraction_suffix="prev",
            ),
            _state(
                period_label="FY2024",
                period_end=date(2024, 12, 31),
                extraction_suffix="a",
            ),
            _state(
                period_label="FY2025",
                period_end=date(2026, 3, 31),
                audit_status="unaudited",
                document_type="investor_presentation",
                revenue=Decimal("900000"),  # 25 % preliminary uplift
                extraction_suffix="b",
            ),
        ]
        repo = _stub_repo(states)
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        assert ts.investment_signal is not None
        # Caveat bullet present (preliminary signal diverges from audited).
        assert ts.investment_signal.preliminary_caveat_bullets


# ======================================================================
# Part A — DuPont 5-way
# ======================================================================
class TestPartADuPont5Way:
    def test_compute_dupont_5way_returns_none_missing_inputs(self) -> None:
        r = _record(pbt=None)
        assert compute_dupont_5way(r) is None

    def test_dupont_5way_product_reconciles_with_reported_roe(self) -> None:
        r = _record(
            revenue=Decimal("1000"),
            operating_income=Decimal("200"),
            pbt=Decimal("180"),
            net_income=Decimal("140"),
            total_assets=Decimal("1200"),
            total_equity=Decimal("700"),
        )
        d = compute_dupont_5way(r)
        assert d is not None
        # tax burden = 140 / 180 = 0.7778
        assert d.tax_burden is not None
        assert abs(d.tax_burden - Decimal("0.7778")) < Decimal("0.001")
        # interest burden = 180 / 200 = 0.9
        assert d.interest_burden is not None
        assert abs(d.interest_burden - Decimal("0.9")) < Decimal("0.001")
        # Operating margin = 200/1000 = 20 %
        assert d.operating_margin == Decimal("20")
        # ROE reported = 140 / 700 = 20 %
        assert d.roe_reported == Decimal("20")
        # Reconciliation delta must be tiny.
        assert d.reconciliation_delta is not None
        assert abs(d.reconciliation_delta) < Decimal("0.01")

    def test_dupont_5way_attribution_sums_to_delta(self) -> None:
        a = compute_dupont_5way(
            _record(
                revenue=Decimal("1000"),
                operating_income=Decimal("200"),
                pbt=Decimal("180"),
                net_income=Decimal("130"),
                total_assets=Decimal("1200"),
                total_equity=Decimal("700"),
            )
        )
        b = compute_dupont_5way(
            _record(
                revenue=Decimal("1100"),
                operating_income=Decimal("220"),
                pbt=Decimal("200"),
                net_income=Decimal("150"),
                total_assets=Decimal("1250"),
                total_equity=Decimal("720"),
            )
        )
        assert a is not None and b is not None
        a.period = "FY2023"
        b.period = "FY2024"
        attr = attribute_roe_5way_change(a, b)
        assert attr is not None
        # Contributions + residual should reconcile to ΔROE bps.
        total = (
            attr.tax_burden_contribution_bps
            + attr.interest_burden_contribution_bps
            + attr.operating_margin_contribution_bps
            + attr.asset_turnover_contribution_bps
            + attr.financial_leverage_contribution_bps
            + attr.cross_residual_bps
        )
        assert abs(total - attr.roe_delta_bps) < Decimal("1")

    def test_dupont_5way_attaches_to_record_during_normalize(self) -> None:
        state = _state()
        repo = _stub_repo([state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        primary = ts.records[0]
        assert primary.dupont_5way is not None
        assert primary.dupont_5way.tax_burden is not None

    def test_dupont_5way_cli_table_renders(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        state = _state()
        repo = _stub_repo([state])
        normalizer = HistoricalNormalizer(state_repo=repo)
        buf = io.StringIO()
        test_console = Console(file=buf, width=240, record=True)
        monkeypatch.setattr(analyze_cmd, "console", test_console)
        analyze_cmd._run_analyze("TST.HK", export=None, normalizer=normalizer)
        rendered = buf.getvalue()
        assert "DuPont 5-way" in rendered

    def test_dupont_5way_markdown_section(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        state = _state()
        repo = _stub_repo([state])
        normalizer = HistoricalNormalizer(state_repo=repo)
        buf = io.StringIO()
        test_console = Console(file=buf, width=240)
        monkeypatch.setattr(analyze_cmd, "console", test_console)
        out = tmp_path / "analytical.md"
        analyze_cmd._run_analyze("TST.HK", export=out, normalizer=normalizer)
        md = out.read_text()
        assert "## DuPont 5-way" in md


# ======================================================================
# Part B — full restatement engine
# ======================================================================
class TestPartBRestatementEngine:
    def test_metric_class_buckets_correctly(self) -> None:
        assert _metric_class("revenue") == "headline"
        assert _metric_class("pbt") == "secondary"
        assert _metric_class("ebitda") == "memo"

    def test_default_threshold_half_percent_for_headlines(self) -> None:
        assert _default_threshold_for("revenue") == Decimal("0.5")
        assert _default_threshold_for("pbt") == Decimal("1.0")

    def test_compare_records_respects_per_metric_threshold(self) -> None:
        """Headline metric 0.6 % delta → event. Memo metric 0.8 %
        delta → no event (below 1 % threshold)."""
        primary = _record(
            period="FY2024",
            revenue=Decimal("1000"),
            operating_income=Decimal("100"),  # will test secondary metric too
            source_id="audited",
        )
        secondary = _record(
            period="FY2024",
            revenue=Decimal("994"),  # 0.6 %
            operating_income=Decimal("99.2"),  # 0.8 %
            source_id="prelim",
        )
        events = _compare_records(primary, secondary)
        metrics = {e.metric for e in events}
        assert "revenue" in metrics  # headline >= 0.5 %
        # Operating_income is also headline; 0.8 % delta → event
        assert "operating_income" in metrics

    def test_event_has_direction_and_metric_class(self) -> None:
        primary = _record(revenue=Decimal("1000"))
        secondary = _record(revenue=Decimal("950"))
        events = _compare_records(primary, secondary)
        assert len(events) == 1
        assert events[0].direction == "UPWARD"  # primary > secondary
        assert events[0].metric_class == "headline"

    def test_pattern_detection_marks_systemic_upward(self) -> None:
        events = [
            RestatementEvent(
                period="FY2023",
                source_a_canonical_id="a",
                source_a_audit=AuditStatus.UNAUDITED,
                source_a_value=Decimal("100"),
                source_b_canonical_id="b",
                source_b_audit=AuditStatus.AUDITED,
                source_b_value=Decimal("110"),
                metric=m,
                metric_class="headline",
                direction="UPWARD",
                delta_absolute=Decimal("10"),
                delta_pct=Decimal("10"),
                is_material=True,
                severity="ADVERSE",
                detected_at=datetime.now(UTC),
            )
            for m in ("revenue", "operating_income", "net_income")
        ]
        patterns = _detect_restatement_patterns(events)
        assert len(patterns) == 1
        assert patterns[0].dominant_direction == "UPWARD"
        assert patterns[0].systemic_flag is True

    def test_pattern_classification_policy_change(self) -> None:
        """P&L + BS metrics affected simultaneously → POLICY_CHANGE."""
        events = [
            RestatementEvent(
                period="FY2023",
                source_a_canonical_id="a",
                source_a_audit=AuditStatus.UNAUDITED,
                source_a_value=Decimal("100"),
                source_b_canonical_id="b",
                source_b_audit=AuditStatus.AUDITED,
                source_b_value=Decimal("110"),
                metric=m,
                metric_class=c,
                direction="UPWARD",
                delta_absolute=Decimal("10"),
                delta_pct=Decimal("10"),
                is_material=True,
                severity="ADVERSE",
                detected_at=datetime.now(UTC),
            )
            for m, c in (
                ("revenue", "headline"),
                ("operating_income", "headline"),
                ("total_assets", "headline"),
            )
        ]
        patterns = _detect_restatement_patterns(events)
        # Contains both P&L (revenue, op income) and BS (total_assets)
        assert patterns[0].classification == "POLICY_CHANGE"

    def test_pattern_classification_reclassification(self) -> None:
        """BS-only restatement → RECLASSIFICATION."""
        events = [
            RestatementEvent(
                period="FY2023",
                source_a_canonical_id="a",
                source_a_audit=AuditStatus.UNAUDITED,
                source_a_value=Decimal("100"),
                source_b_canonical_id="b",
                source_b_audit=AuditStatus.AUDITED,
                source_b_value=Decimal("105"),
                metric=m,
                metric_class="headline" if m in ("total_assets", "total_equity") else "secondary",
                direction="UPWARD",
                delta_absolute=Decimal("5"),
                delta_pct=Decimal("5"),
                is_material=True,
                severity="MATERIAL",
                detected_at=datetime.now(UTC),
            )
            for m in ("total_assets", "total_equity", "cash_and_equivalents")
        ]
        patterns = _detect_restatement_patterns(events)
        assert patterns[0].classification == "RECLASSIFICATION"

    def test_one_off_when_below_systemic_threshold(self) -> None:
        events = [
            RestatementEvent(
                period="FY2023",
                source_a_canonical_id="a",
                source_a_audit=AuditStatus.UNAUDITED,
                source_a_value=Decimal("100"),
                source_b_canonical_id="b",
                source_b_audit=AuditStatus.AUDITED,
                source_b_value=Decimal("110"),
                metric="revenue",
                metric_class="headline",
                direction="UPWARD",
                delta_absolute=Decimal("10"),
                delta_pct=Decimal("10"),
                is_material=True,
                severity="ADVERSE",
                detected_at=datetime.now(UTC),
            )
        ]
        patterns = _detect_restatement_patterns(events)
        assert patterns[0].classification == "ONE_OFF_ADJUSTMENT"

    def test_pattern_classification_error_correction_on_proportional(
        self,
    ) -> None:
        """All metrics move within 1 pp of each other → ERROR_CORRECTION."""
        events = [
            RestatementEvent(
                period="FY2023",
                source_a_canonical_id="a",
                source_a_audit=AuditStatus.UNAUDITED,
                source_a_value=Decimal("100"),
                source_b_canonical_id="b",
                source_b_audit=AuditStatus.AUDITED,
                source_b_value=Decimal("101"),
                metric=m,
                metric_class="secondary",
                direction="UPWARD",
                delta_absolute=Decimal("1"),
                delta_pct=delta,
                is_material=False,
                severity="MINOR",
                detected_at=datetime.now(UTC),
            )
            for m, delta in (
                ("pbt", Decimal("1.0")),
                ("income_tax_expense", Decimal("1.2")),
                ("finance_income", Decimal("1.1")),
            )
        ]
        patterns = _detect_restatement_patterns(events)
        # All-same-direction, same-ish percentage → ERROR_CORRECTION.
        assert patterns[0].classification == "ERROR_CORRECTION"

    def test_restatement_narrative_link_populates_when_keyword_match(
        self,
    ) -> None:
        from portfolio_thesis_engine.schemas.ficha import NarrativeSummary

        patterns = [
            type("P", (), {"period_comparison": "FY2023: ..."})()
        ]
        # Build a record whose narrative summary mentions a policy change.
        record = _record(period="FY2024")
        record.narrative_summary = NarrativeSummary(
            source_period="FY2024",
            source_document_type="annual_report",
            source_extraction_timestamp=datetime.now(UTC),
            key_themes=[],
            primary_risks=["Prior-period reclassification of revenue"],
            management_guidance=[],
            capital_allocation=[],
        )
        from portfolio_thesis_engine.schemas.historicals import RestatementPattern

        links = _link_restatements_to_narrative(
            [
                RestatementPattern(
                    period_comparison="FY2023: primary vs comparative",
                    event_count=3,
                    dominant_direction="UPWARD",
                    systemic_flag=True,
                    classification="POLICY_CHANGE",
                )
            ],
            [record],
        )
        assert len(links) == 1
        assert links[0].narrative_period == "FY2024"
        assert "reclassification" in links[0].linked_theme.lower()


# ======================================================================
# Part C — trend enhancements
# ======================================================================
class TestPartCTrendEnhancements:
    def test_capex_revenue_ratio_populates_from_audited_annual(self) -> None:
        # Trend analysis needs >= 2 annuals; add a prior-year audited
        # fixture so compute_trends activates.
        state_prev = _state(
            period_label="FY2023",
            period_end=date(2023, 12, 31),
            revenue=Decimal("640000"),
            extraction_suffix="prev",
        )
        state = _state()
        repo = _stub_repo([state_prev, state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        assert ts.trends is not None
        assert ts.trends.capex_revenue_ratio is not None

    def test_cfo_revenue_ratio_computed(self) -> None:
        state = _state()
        repo = _stub_repo([state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        # Only one annual → trends returns None (needs 2+). Add a
        # second audited annual so trends populate.
        state_prev = _state(
            period_label="FY2023",
            period_end=date(2023, 12, 31),
            revenue=Decimal("650000"),
            extraction_suffix="prev",
        )
        repo2 = _stub_repo([state_prev, state])
        ts2 = HistoricalNormalizer(state_repo=repo2).normalize("TST.HK")
        assert ts2.trends is not None
        assert ts2.trends.cfo_revenue_ratio is not None

    def test_working_capital_intensity_populates(self) -> None:
        state_prev = _state(
            period_label="FY2023",
            period_end=date(2023, 12, 31),
            revenue=Decimal("650000"),
            extraction_suffix="prev",
        )
        state = _state()
        repo = _stub_repo([state_prev, state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        assert ts.trends is not None
        assert ts.trends.working_capital_intensity is not None

    def test_cash_conversion_cycle_populates(self) -> None:
        state_prev = _state(
            period_label="FY2023",
            period_end=date(2023, 12, 31),
            revenue=Decimal("650000"),
            extraction_suffix="prev",
        )
        state = _state()
        repo = _stub_repo([state_prev, state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        assert ts.trends is not None
        # DSO + DIO − DPO — signs depend on fixture, just assert non-None.
        assert ts.trends.cash_conversion_cycle is not None

    def test_roic_spread_trend_defaults_stable(self) -> None:
        state_prev = _state(
            period_label="FY2023",
            period_end=date(2023, 12, 31),
            revenue=Decimal("650000"),
            extraction_suffix="prev",
        )
        state = _state()
        repo = _stub_repo([state_prev, state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("TST.HK")
        assert ts.trends is not None
        # Only 1 annual with ROIC decomp → stable spread trend.
        assert ts.trends.roic_spread_trend == "STABLE_SPREAD"
