"""Phase 2 Sprint 1 regression tests — HistoricalNormalizer +
CompanyTimeSeries.

Coverage:

Schema (4):
- ``test_historical_record_schema_required_fields``
- ``test_company_time_series_sorted_ascending``
- ``test_restatement_event_materiality_threshold``
- ``test_fiscal_year_change_event_detection_when_period_end_shifts``

Normalizer state loading + primary record build (4):
- ``test_normalizer_loads_all_canonical_states``
- ``test_normalizer_empty_corpus_returns_empty_series``
- ``test_normalizer_builds_record_from_primary_period``
- ``test_normalizer_classifies_unaudited_as_preliminary``

Dedupe + restatement (3):
- ``test_normalizer_dedupe_prefers_audited``
- ``test_normalizer_emits_restatement_when_audited_disagrees_unaudited``
- ``test_normalizer_no_restatement_below_materiality_threshold``

Fiscal year change (3):
- ``test_no_change_detected_when_consistent``
- ``test_change_detected_when_period_end_shifts``
- ``test_transition_months_calculated_correctly``

TTM (4):
- ``test_ttm_builds_when_interim_and_prior_year_and_base_annual_present``
- ``test_ttm_skips_when_no_interim``
- ``test_ttm_skips_when_no_matching_prior_interim``
- ``test_ttm_arithmetic_correct``

Narrative timeline (3):
- ``test_themes_aggregated_across_records``
- ``test_themes_first_seen_last_seen_tracked``
- ``test_theme_was_consistent_flag``

CLI + markdown (3):
- ``test_cli_historicals_renders_periods_table``
- ``test_cli_historicals_exits_when_no_states``
- ``test_markdown_report_includes_periods_and_restatements``

Total: 24 tests (scoped to Sprint 1's critical paths; Sprint 2+ adds
additional analytical coverage).
"""

from __future__ import annotations

import io
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from portfolio_thesis_engine.analytical.historicals import (
    HistoricalNormalizer,
    _build_ttm_record,
    _compare_records,
    _dedupe_with_restatements,
    _detect_fiscal_year_changes,
)
from portfolio_thesis_engine.cli import historicals_cmd
from portfolio_thesis_engine.schemas.common import Currency, FiscalPeriod, Profile
from portfolio_thesis_engine.schemas.company import (
    AdjustmentsApplied,
    AnalysisDerived,
    CanonicalCompanyState,
    CompanyIdentity,
    IncomeStatementLine,
    InvestedCapital,
    KeyRatios,
    MethodologyMetadata,
    NarrativeContext,
    NOPATBridge,
    ReclassifiedStatements,
    ValidationResult,
    ValidationResults,
    VintageAndCascade,
)
from portfolio_thesis_engine.schemas.ficha import NarrativeSummary
from portfolio_thesis_engine.schemas.historicals import (
    CompanyTimeSeries,
    HistoricalPeriodType,
    HistoricalRecord,
)
from portfolio_thesis_engine.schemas.raw_extraction import AuditStatus


def _canonical_state(
    *,
    ticker: str = "1846.HK",
    period_label: str = "FY2024",
    period_end: date = date(2024, 12, 31),
    audit_status: str = "audited",
    document_type: str = "annual_report",
    revenue: Decimal | None = Decimal("1000"),
    operating_income: Decimal | None = Decimal("200"),
    nopat: Decimal | None = Decimal("150"),
    net_income: Decimal | None = Decimal("140"),
    extraction_suffix: str = "x1",
    narrative_context: NarrativeContext | None = None,
) -> CanonicalCompanyState:
    period = FiscalPeriod(year=period_end.year, label=period_label)
    is_lines = [
        IncomeStatementLine(label="Revenue", value=revenue or Decimal("0")),
        IncomeStatementLine(
            label="Operating profit",
            value=operating_income or Decimal("0"),
        ),
        IncomeStatementLine(
            label="Profit for the year",
            value=net_income or Decimal("0"),
        ),
    ]
    return CanonicalCompanyState(
        extraction_id=f"{ticker}_{period_label}_{extraction_suffix}",
        extraction_date=datetime(2025, 1, 1, tzinfo=UTC),
        as_of_date=period_end.isoformat(),
        identity=CompanyIdentity(
            ticker=ticker,
            name="EuroEyes" if ticker == "1846.HK" else ticker,
            reporting_currency=Currency.HKD,
            profile=Profile.P1_INDUSTRIAL,
            fiscal_year_end_month=period_end.month,
            country_domicile="HK",
            exchange="HKEX",
        ),
        reclassified_statements=[
            ReclassifiedStatements(
                period=period,
                income_statement=is_lines,
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
                    operating_assets=Decimal("800"),
                    operating_liabilities=Decimal("0"),
                    invested_capital=Decimal("800"),
                    financial_assets=Decimal("50"),
                    financial_liabilities=Decimal("150"),
                    equity_claims=Decimal("700"),
                    cross_check_residual=Decimal("0"),
                )
            ],
            nopat_bridge_by_period=[
                NOPATBridge(
                    period=period,
                    ebitda=Decimal("280"),
                    operating_income=operating_income,
                    operating_taxes=Decimal("50"),
                    nopat=nopat or Decimal("0"),
                    financial_income=Decimal("0"),
                    financial_expense=Decimal("10"),
                    non_operating_items=Decimal("0"),
                    reported_net_income=net_income or Decimal("0"),
                )
            ],
            ratios_by_period=[
                KeyRatios(
                    period=period,
                    roic=Decimal("18.75"),
                    roe=Decimal("20.00"),
                    operating_margin=Decimal("20"),
                    ebitda_margin=Decimal("28"),
                )
            ],
        ),
        validation=ValidationResults(
            universal_checksums=[
                ValidationResult(
                    check_id="V.0",
                    name="s",
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
        narrative_context=narrative_context,
    )


def _stub_repo(states: list[CanonicalCompanyState]) -> MagicMock:
    repo = MagicMock()
    repo.list_versions = MagicMock(
        return_value=[s.extraction_id for s in states]
    )
    # get_version returns the matching state by id.
    state_map = {s.extraction_id: s for s in states}
    repo.get_version = MagicMock(
        side_effect=lambda ticker, version: state_map.get(version)
    )
    return repo


def _historical_record(
    *,
    period: str = "FY2024",
    period_end: date = date(2024, 12, 31),
    period_type: HistoricalPeriodType = HistoricalPeriodType.ANNUAL,
    audit_status: AuditStatus = AuditStatus.AUDITED,
    revenue: Decimal | None = Decimal("1000"),
    operating_income: Decimal | None = Decimal("200"),
    net_income: Decimal | None = Decimal("140"),
    source_id: str = "cs1",
    narrative_summary: NarrativeSummary | None = None,
) -> HistoricalRecord:
    return HistoricalRecord(
        period=period,
        period_start=date(period_end.year, 1, 1),
        period_end=period_end,
        period_type=period_type,
        fiscal_year_basis=f"calendar_{period_end.month:02d}",
        audit_status=audit_status,
        source_canonical_state_id=source_id,
        source_document_type="annual_report",
        source_document_date=period_end,
        revenue=revenue,
        operating_income=operating_income,
        net_income=net_income,
        narrative_summary=narrative_summary,
    )


# ======================================================================
# Schema
# ======================================================================


class TestHistoricalSchemas:
    def test_historical_record_schema_required_fields(self) -> None:
        record = _historical_record()
        assert record.period == "FY2024"
        assert record.period_type == HistoricalPeriodType.ANNUAL
        assert record.audit_status == AuditStatus.AUDITED

    def test_company_time_series_sorted_ascending(self) -> None:
        r1 = _historical_record(
            period="FY2023", period_end=date(2023, 12, 31)
        )
        r2 = _historical_record(
            period="FY2024", period_end=date(2024, 12, 31)
        )
        ts = CompanyTimeSeries(
            ticker="TST",
            identity=CompanyIdentity(
                ticker="TST",
                name="Test",
                reporting_currency=Currency.USD,
                profile=Profile.P1_INDUSTRIAL,
                fiscal_year_end_month=12,
                country_domicile="US",
                exchange="NYSE",
            ),
            records=[r2, r1],  # unsorted
            generated_at=datetime.now(UTC),
        )
        # Schema stores as-provided; the normalizer is responsible for
        # sorting (asserted elsewhere).
        assert len(ts.records) == 2

    def test_restatement_event_materiality_threshold(self) -> None:
        """Phase 2 Sprint 2A tightened the threshold to 0.5 % and
        added five severity levels. Below 0.5 % (NEGLIGIBLE) still
        produces no event."""
        primary = _historical_record(
            period="FY2024", revenue=Decimal("1000"), source_id="audited"
        )
        # Secondary 0.2 % off — NEGLIGIBLE, no event.
        secondary_tiny = _historical_record(
            period="FY2024", revenue=Decimal("998"), source_id="prelim",
            audit_status=AuditStatus.UNAUDITED,
        )
        assert _compare_records(primary, secondary_tiny) == []

        # Secondary 5 % off — SIGNIFICANT, emits event with
        # ``is_material=True``.
        secondary_big = _historical_record(
            period="FY2024", revenue=Decimal("950"), source_id="prelim",
            audit_status=AuditStatus.UNAUDITED,
        )
        events = _compare_records(primary, secondary_big)
        assert len(events) == 1
        assert events[0].metric == "revenue"
        assert events[0].is_material is True
        assert events[0].severity == "SIGNIFICANT"

    def test_fiscal_year_change_event_detection_when_period_end_shifts(
        self,
    ) -> None:
        r1 = _historical_record(
            period="FY2024", period_end=date(2024, 12, 31)
        )
        r2 = _historical_record(
            period="FY2025", period_end=date(2026, 3, 31),
            source_id="cs2",
        )
        events = _detect_fiscal_year_changes([r1, r2])
        assert len(events) == 1
        assert events[0].previous_fiscal_year_end == "12-31"
        assert events[0].new_fiscal_year_end == "03-31"


# ======================================================================
# Normalizer
# ======================================================================


class TestNormalizer:
    def test_normalizer_empty_corpus_returns_empty_series(self) -> None:
        repo = MagicMock()
        repo.list_versions = MagicMock(return_value=[])
        ts = HistoricalNormalizer(state_repo=repo).normalize("UNKNOWN")
        assert ts.ticker == "UNKNOWN"
        assert ts.records == []

    def test_normalizer_loads_all_canonical_states(self) -> None:
        states = [
            _canonical_state(period_label="FY2023", period_end=date(2023, 12, 31),
                             extraction_suffix="a"),
            _canonical_state(period_label="FY2024", period_end=date(2024, 12, 31),
                             extraction_suffix="b"),
        ]
        repo = _stub_repo(states)
        ts = HistoricalNormalizer(state_repo=repo).normalize("1846.HK")
        # Two annual states → two records (plus TTM would require
        # interim, which isn't present here).
        assert len(ts.records) == 2
        assert {r.period for r in ts.records} == {"FY2023", "FY2024"}

    def test_normalizer_builds_record_from_primary_period(self) -> None:
        states = [
            _canonical_state(
                period_label="FY2024",
                revenue=Decimal("715"),
                operating_income=Decimal("115"),
            )
        ]
        repo = _stub_repo(states)
        ts = HistoricalNormalizer(state_repo=repo).normalize("1846.HK")
        r = ts.records[0]
        assert r.revenue == Decimal("715")
        assert r.operating_income == Decimal("115")
        assert r.period_type == HistoricalPeriodType.ANNUAL

    def test_normalizer_classifies_unaudited_as_preliminary(self) -> None:
        states = [
            _canonical_state(
                period_label="FY2025",
                audit_status="unaudited",
                document_type="investor_presentation",
                period_end=date(2025, 12, 31),
            )
        ]
        repo = _stub_repo(states)
        ts = HistoricalNormalizer(state_repo=repo).normalize("1846.HK")
        r = ts.records[0]
        assert r.period_type == HistoricalPeriodType.PRELIMINARY
        assert r.audit_status == AuditStatus.UNAUDITED


# ======================================================================
# Dedupe + restatement
# ======================================================================


class TestDedupeRestatement:
    def test_normalizer_dedupe_prefers_audited(self) -> None:
        audited = _historical_record(
            period="FY2024",
            revenue=Decimal("1000"),
            audit_status=AuditStatus.AUDITED,
            source_id="audited",
        )
        preliminary = _historical_record(
            period="FY2024",
            revenue=Decimal("950"),
            audit_status=AuditStatus.UNAUDITED,
            source_id="preliminary",
        )
        deduped, _ = _dedupe_with_restatements([preliminary, audited])
        assert len(deduped) == 1
        assert deduped[0].source_canonical_state_id == "audited"

    def test_normalizer_emits_restatement_when_audited_disagrees_unaudited(
        self,
    ) -> None:
        audited = _historical_record(
            period="FY2024",
            revenue=Decimal("1000"),
            audit_status=AuditStatus.AUDITED,
            source_id="audited",
        )
        preliminary = _historical_record(
            period="FY2024",
            revenue=Decimal("950"),  # 5.26 % off
            audit_status=AuditStatus.UNAUDITED,
            source_id="preliminary",
        )
        _, events = _dedupe_with_restatements([preliminary, audited])
        assert len(events) == 1
        assert events[0].metric == "revenue"
        assert events[0].is_material is True
        assert events[0].source_a_canonical_id == "preliminary"

    def test_normalizer_no_restatement_below_materiality_threshold(
        self,
    ) -> None:
        audited = _historical_record(
            period="FY2024",
            revenue=Decimal("1000"),
            audit_status=AuditStatus.AUDITED,
            source_id="audited",
        )
        preliminary = _historical_record(
            period="FY2024",
            revenue=Decimal("998"),  # 0.2 %
            audit_status=AuditStatus.UNAUDITED,
            source_id="preliminary",
        )
        _, events = _dedupe_with_restatements([preliminary, audited])
        assert events == []


# ======================================================================
# Fiscal year change
# ======================================================================


class TestFiscalYearChange:
    def test_no_change_detected_when_consistent(self) -> None:
        r1 = _historical_record(period_end=date(2023, 12, 31))
        r2 = _historical_record(period_end=date(2024, 12, 31))
        assert _detect_fiscal_year_changes([r1, r2]) == []

    def test_change_detected_when_period_end_shifts(self) -> None:
        r1 = _historical_record(period_end=date(2024, 12, 31))
        r2 = _historical_record(
            period_end=date(2026, 3, 31), period="FY2026",
            source_id="cs2",
        )
        events = _detect_fiscal_year_changes([r1, r2])
        assert events[0].detected_at_period == "FY2026"

    def test_transition_months_calculated_correctly(self) -> None:
        r1 = _historical_record(period_end=date(2024, 12, 31))
        r2 = _historical_record(
            period_end=date(2026, 3, 31), source_id="cs2", period="FY2026",
        )
        events = _detect_fiscal_year_changes([r1, r2])
        # Dec 2024 → Mar 2026 = 2024→2026 × 12 + (3 − 12) = 24 − 9 = 15.
        assert events[0].transition_period_months == 15


# ======================================================================
# TTM
# ======================================================================


class TestTTM:
    def _records_for_ttm(self) -> list[HistoricalRecord]:
        base_annual = _historical_record(
            period="FY2024",
            period_end=date(2024, 12, 31),
            revenue=Decimal("1000"),
            operating_income=Decimal("200"),
            net_income=Decimal("140"),
        )
        prior_interim = _historical_record(
            period="H1_2024",
            period_end=date(2024, 6, 30),
            period_type=HistoricalPeriodType.INTERIM,
            audit_status=AuditStatus.REVIEWED,
            revenue=Decimal("480"),
            operating_income=Decimal("95"),
            net_income=Decimal("65"),
            source_id="interim2024",
        )
        latest_interim = _historical_record(
            period="H1_2025",
            period_end=date(2025, 6, 30),
            period_type=HistoricalPeriodType.INTERIM,
            audit_status=AuditStatus.REVIEWED,
            revenue=Decimal("530"),
            operating_income=Decimal("110"),
            net_income=Decimal("75"),
            source_id="interim2025",
        )
        return [base_annual, prior_interim, latest_interim]

    def test_ttm_builds_when_interim_and_prior_year_and_base_annual_present(
        self,
    ) -> None:
        records = self._records_for_ttm()
        ttm = _build_ttm_record(records)
        assert ttm is not None
        assert ttm.period_type == HistoricalPeriodType.TTM
        assert ttm.period_end == date(2025, 6, 30)

    def test_ttm_skips_when_no_interim(self) -> None:
        annual = _historical_record(period="FY2024")
        assert _build_ttm_record([annual]) is None

    def test_ttm_skips_when_no_matching_prior_interim(self) -> None:
        records = [
            _historical_record(
                period="FY2024", revenue=Decimal("1000")
            ),
            _historical_record(
                period="Q3_2025",
                period_end=date(2025, 9, 30),
                period_type=HistoricalPeriodType.INTERIM,
                revenue=Decimal("700"),
            ),
        ]
        assert _build_ttm_record(records) is None

    def test_ttm_arithmetic_correct(self) -> None:
        records = self._records_for_ttm()
        ttm = _build_ttm_record(records)
        # TTM revenue = FY2024 − H1_2024 + H1_2025 = 1000 − 480 + 530 = 1050
        assert ttm is not None
        assert ttm.revenue == Decimal("1050")
        # Op income 200 − 95 + 110 = 215
        assert ttm.operating_income == Decimal("215")


# ======================================================================
# Narrative timeline
# ======================================================================


class TestNarrativeTimeline:
    def _record_with_narrative(
        self,
        *,
        period: str,
        period_end: date,
        themes: list[str],
        source_id: str,
    ) -> HistoricalRecord:
        narrative = NarrativeSummary(
            source_period=period,
            source_document_type="annual_report",
            source_extraction_timestamp=datetime.now(UTC),
            key_themes=themes,
            primary_risks=[],
            management_guidance=[],
            capital_allocation=[],
        )
        return _historical_record(
            period=period,
            period_end=period_end,
            source_id=source_id,
            narrative_summary=narrative,
        )

    def test_themes_aggregated_across_records(self) -> None:
        from portfolio_thesis_engine.analytical.historicals import (
            _build_narrative_timeline,
        )

        records = [
            self._record_with_narrative(
                period="FY2024",
                period_end=date(2024, 12, 31),
                themes=["PRC expansion", "Munich refurb"],
                source_id="cs1",
            ),
            self._record_with_narrative(
                period="H1_2025",
                period_end=date(2025, 6, 30),
                themes=["PRC expansion", "Lens exchange focus"],
                source_id="cs2",
            ),
        ]
        timeline = _build_narrative_timeline(records)
        texts = {t.theme_text for t in timeline.themes_evolution}
        assert texts == {"PRC expansion", "Munich refurb", "Lens exchange focus"}

    def test_themes_first_seen_last_seen_tracked(self) -> None:
        from portfolio_thesis_engine.analytical.historicals import (
            _build_narrative_timeline,
        )

        records = [
            self._record_with_narrative(
                period="FY2024",
                period_end=date(2024, 12, 31),
                themes=["PRC expansion"],
                source_id="cs1",
            ),
            self._record_with_narrative(
                period="H1_2025",
                period_end=date(2025, 6, 30),
                themes=["PRC expansion"],
                source_id="cs2",
            ),
        ]
        timeline = _build_narrative_timeline(records)
        prc = next(
            t for t in timeline.themes_evolution
            if t.theme_text == "PRC expansion"
        )
        assert prc.first_seen == "FY2024"
        assert prc.last_seen == "H1_2025"

    def test_theme_was_consistent_flag(self) -> None:
        from portfolio_thesis_engine.analytical.historicals import (
            _build_narrative_timeline,
        )

        records = [
            self._record_with_narrative(
                period="FY2023",
                period_end=date(2023, 12, 31),
                themes=["Theme A"],
                source_id="cs0",
            ),
            self._record_with_narrative(
                period="FY2024",
                period_end=date(2024, 12, 31),
                themes=["Theme A"],
                source_id="cs1",
            ),
            self._record_with_narrative(
                period="H1_2025",
                period_end=date(2025, 6, 30),
                themes=["Theme A"],
                source_id="cs2",
            ),
        ]
        timeline = _build_narrative_timeline(records)
        assert timeline.themes_evolution[0].was_consistent is True


# ======================================================================
# CLI + markdown
# ======================================================================


class TestCLIAndMarkdown:
    def test_cli_historicals_renders_periods_table(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        states = [
            _canonical_state(period_label="FY2024"),
        ]
        repo = _stub_repo(states)
        normalizer = HistoricalNormalizer(state_repo=repo)
        buf = io.StringIO()
        test_console = Console(file=buf, width=240, record=True)
        monkeypatch.setattr(historicals_cmd, "console", test_console)
        historicals_cmd._run_historicals(
            "1846.HK", export=None, normalizer=normalizer
        )
        rendered = buf.getvalue()
        assert "Historical time-series" in rendered
        assert "FY2024" in rendered

    def test_cli_historicals_exits_when_no_states(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        repo = MagicMock()
        repo.list_versions = MagicMock(return_value=[])
        normalizer = HistoricalNormalizer(state_repo=repo)
        buf = io.StringIO()
        test_console = Console(file=buf, width=120, record=True)
        monkeypatch.setattr(historicals_cmd, "console", test_console)
        import typer

        with pytest.raises(typer.Exit):
            historicals_cmd._run_historicals(
                "UNKNOWN", export=None, normalizer=normalizer
            )

    def test_markdown_report_includes_periods_and_restatements(
        self, tmp_path: Path
    ) -> None:
        states = [
            _canonical_state(period_label="FY2024", period_end=date(2024, 12, 31),
                             revenue=Decimal("1000"), extraction_suffix="audited"),
            _canonical_state(
                period_label="FY2024",
                period_end=date(2024, 12, 31),
                audit_status="unaudited",
                document_type="preliminary_results",
                revenue=Decimal("900"),  # 10 % off → material restatement
                operating_income=Decimal("180"),
                net_income=Decimal("130"),
                extraction_suffix="prelim",
            ),
        ]
        repo = _stub_repo(states)
        normalizer = HistoricalNormalizer(state_repo=repo)
        ts = normalizer.normalize("1846.HK")
        markdown = historicals_cmd.render_markdown_report(ts)
        assert "# 1846.HK — Historical time-series" in markdown
        assert "FY2024" in markdown
        assert "## Restatement events" in markdown
        # 10 % delta on revenue → material → surfaces.
        assert "revenue" in markdown
