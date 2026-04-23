"""Phase 2 Sprint 1.1 regression tests — fixes surfaced by the first
EuroEyes historical-timeseries run.

Covers five fixes:

- Issue 1 (critical): audit_status 3-tier resolution in normalizer.
- Issue 2: operating_income falls back to IS line when bridge empty.
- Issue 3: source_document_type never renders "unknown" for resolvable
  period labels.
- Issue 4 (acceptable behaviour, pinned by a test): preliminary records
  with no invested_capital leave ``roic_primary`` None.
- Issue 5: narrative_summary flows from canonical_state.narrative_context
  into HistoricalRecord and into the NarrativeTimeline aggregation.

Plus the dedupe test for the "36 canonical-state versions → 3 records"
issue.

Total: 8 tests.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from unittest.mock import MagicMock

from portfolio_thesis_engine.analytical.historicals import (
    HistoricalNormalizer,
    _build_narrative_timeline,
    _resolve_audit_status,
    _resolve_source_document_type,
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
from portfolio_thesis_engine.schemas.historicals import HistoricalPeriodType
from portfolio_thesis_engine.schemas.raw_extraction import (
    AuditStatus,
    CapitalAllocationItem,
    GuidanceItem,
    NarrativeItem,
    RiskItem,
)


# ======================================================================
# Helpers
# ======================================================================


def _canonical(
    *,
    ticker: str = "1846.HK",
    period_label: str = "FY2024",
    period_end: date = date(2024, 12, 31),
    audit_status: str | None = "audited",
    document_type: str | None = "annual_report",
    operating_income_in_bridge: Decimal | None = Decimal("115"),
    operating_income_in_is: Decimal | None = None,
    nopat: Decimal | None = Decimal("81"),
    extraction_date: datetime | None = None,
    narrative_context: NarrativeContext | None = None,
    include_ic: bool = True,
) -> CanonicalCompanyState:
    period = FiscalPeriod(year=period_end.year, label=period_label)
    is_lines = [
        IncomeStatementLine(label="Revenue", value=Decimal("1000")),
    ]
    if operating_income_in_is is not None:
        is_lines.append(
            IncomeStatementLine(
                label="Operating profit",
                value=operating_income_in_is,
            )
        )
    is_lines.append(
        IncomeStatementLine(
            label="Profit for the year", value=Decimal("60")
        )
    )

    bridges = [
        NOPATBridge(
            period=period,
            ebitda=Decimal("200"),
            operating_income=operating_income_in_bridge,
            operating_taxes=Decimal("34"),
            nopat=nopat or Decimal("0"),
            financial_income=Decimal("0"),
            financial_expense=Decimal("10"),
            non_operating_items=Decimal("0"),
            reported_net_income=Decimal("60"),
        )
    ]
    ic_list = (
        [
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
        ]
        if include_ic
        else []
    )

    methodology_kwargs: dict = {
        "extraction_system_version": "test",
        "profile_applied": Profile.P1_INDUSTRIAL,
        "protocols_activated": ["A"],
    }
    if audit_status is not None:
        methodology_kwargs["audit_status"] = audit_status
    if document_type is not None:
        methodology_kwargs["source_document_type"] = document_type

    return CanonicalCompanyState(
        extraction_id=(
            f"{ticker}_{period_label}_"
            + (extraction_date or datetime(2025, 1, 1, tzinfo=UTC)).strftime(
                "%Y%m%d%H%M%S"
            )
        ),
        extraction_date=extraction_date or datetime(2025, 1, 1, tzinfo=UTC),
        as_of_date=period_end.isoformat(),
        identity=CompanyIdentity(
            ticker=ticker,
            name="EuroEyes",
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
            invested_capital_by_period=ic_list,
            nopat_bridge_by_period=bridges,
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
        methodology=MethodologyMetadata(**methodology_kwargs),
        narrative_context=narrative_context,
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


def _euroeyes_narrative() -> NarrativeContext:
    return NarrativeContext(
        key_themes=[
            NarrativeItem(
                text="Record interim revenue",
                source="MD&A Highlights",
                page=14,
            ),
            NarrativeItem(text="Presbyopia correction strategic concentration"),
        ],
        risks_mentioned=[
            RiskItem(
                risk="Refractive laser segment decline",
                detail="-15.9 % YoY",
                severity="medium",
                source="MD&A §6",
                page=38,
            ),
        ],
        guidance_changes=[
            GuidanceItem(
                metric="Revenue CAGR through 2028",
                value="low-to-mid teens",
                period="2025-2028",
                source="Investor day",
            )
        ],
        capital_allocation_signals=[
            CapitalAllocationItem(
                area="Organic capex",
                detail="-33 % YoY",
                period="H1_2025",
                source="MD&A",
            )
        ],
        forward_looking_statements=[],
        source_extraction_period="H1_2025",
        source_document_type="interim_report",
        extraction_timestamp=datetime(2026, 4, 22, tzinfo=UTC),
    )


# ======================================================================
# Issue 1 — audit_status 3-tier resolution
# ======================================================================


class TestAuditStatusResolution:
    def test_h1_2025_interim_without_explicit_audit_resolves_to_reviewed(
        self,
    ) -> None:
        """Legacy canonical state with stored default 'audited' + doc
        type 'interim_report' must resolve to REVIEWED."""
        state = _canonical(
            period_label="H1_2025",
            period_end=date(2025, 6, 30),
            audit_status="audited",  # stored default — the bug cascade
            document_type="interim_report",
        )
        assert _resolve_audit_status(state) == AuditStatus.REVIEWED

    def test_falls_back_to_doc_type_default_when_audit_status_missing(
        self,
    ) -> None:
        state = _canonical(
            period_label="FY2025",
            period_end=date(2025, 12, 31),
            audit_status=None,  # not stored at all
            document_type="investor_presentation",
        )
        assert _resolve_audit_status(state) == AuditStatus.UNAUDITED

    def test_explicit_reviewed_honoured(self) -> None:
        """When the stored value is already REVIEWED / UNAUDITED, keep
        it — the doc-type default is only a rescue for the default
        'audited' case."""
        state = _canonical(
            period_label="H1_2025",
            period_end=date(2025, 6, 30),
            audit_status="reviewed",
            document_type="annual_report",  # mismatched on purpose
        )
        assert _resolve_audit_status(state) == AuditStatus.REVIEWED


# ======================================================================
# Issue 2 — operating_income fallback
# ======================================================================


class TestOperatingIncomeFallback:
    def test_operating_income_falls_back_to_is_line_when_bridge_empty(
        self,
    ) -> None:
        state = _canonical(
            period_label="FY2024",
            operating_income_in_bridge=None,  # pre-1.5.9.1 bridge
            operating_income_in_is=Decimal("115779000"),
            nopat=Decimal("80471439"),
        )
        repo = _stub_repo([state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("1846.HK")
        # Record surfaces the IS line value.
        assert len(ts.records) == 1
        assert ts.records[0].operating_income == Decimal("115779000")
        # NOPAT stored independently — still present.
        assert ts.records[0].nopat == Decimal("80471439")

    def test_operating_income_prefers_bridge_when_both_present(
        self,
    ) -> None:
        """Bridge wins when it has a value (post-1.5.9.1 canonical states)."""
        state = _canonical(
            period_label="FY2024",
            operating_income_in_bridge=Decimal("115"),
            operating_income_in_is=Decimal("999"),  # ignored
        )
        repo = _stub_repo([state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("1846.HK")
        assert ts.records[0].operating_income == Decimal("115")


# ======================================================================
# Issue 3 — source_document_type never 'unknown'
# ======================================================================


class TestSourceDocumentTypeFallback:
    def test_source_never_unknown_for_fy_label(self) -> None:
        state = _canonical(
            period_label="FY2024", document_type=None
        )
        assert _resolve_source_document_type(state) == "annual_report"

    def test_source_inferred_as_interim_for_h1_label(self) -> None:
        state = _canonical(
            period_label="H1_2025",
            period_end=date(2025, 6, 30),
            document_type=None,
        )
        assert _resolve_source_document_type(state) == "interim_report"

    def test_source_explicit_document_type_wins(self) -> None:
        state = _canonical(
            period_label="FY2025",
            document_type="preliminary_results",
        )
        assert _resolve_source_document_type(state) == "preliminary_results"


# ======================================================================
# Issue 4 — preliminary ROIC null (acceptable; pinned)
# ======================================================================


class TestPreliminaryRoicNullPinned:
    def test_preliminary_record_roic_null_when_no_invested_capital(
        self,
    ) -> None:
        """Pins the expected behaviour — preliminary YAMLs often omit
        BS/CF, so invested_capital is absent and ROIC stays None.
        This is correct."""
        state = _canonical(
            period_label="FY2025",
            period_end=date(2025, 12, 31),
            audit_status="unaudited",
            document_type="investor_presentation",
            include_ic=False,  # no BS → no IC → ROIC null
        )
        repo = _stub_repo([state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("1846.HK")
        assert len(ts.records) == 1
        record = ts.records[0]
        assert record.period_type == HistoricalPeriodType.PRELIMINARY
        # ROIC is driven by KeyRatios.roic; we don't populate it when IC
        # is absent, so the record keeps it None.
        assert record.roic_primary is None


# ======================================================================
# Issue 5 — narrative flows end-to-end
# ======================================================================


class TestNarrativeFlow:
    def test_record_narrative_summary_built_from_canonical_narrative_context(
        self,
    ) -> None:
        state = _canonical(
            period_label="H1_2025",
            period_end=date(2025, 6, 30),
            audit_status="reviewed",
            document_type="interim_report",
            narrative_context=_euroeyes_narrative(),
        )
        repo = _stub_repo([state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("1846.HK")
        record = ts.records[0]
        assert record.narrative_summary is not None
        assert any(
            "Record interim revenue" in theme
            for theme in record.narrative_summary.key_themes
        )

    def test_narrative_timeline_aggregates_themes_from_records_with_narrative(
        self,
    ) -> None:
        state = _canonical(
            period_label="H1_2025",
            period_end=date(2025, 6, 30),
            audit_status="reviewed",
            document_type="interim_report",
            narrative_context=_euroeyes_narrative(),
        )
        repo = _stub_repo([state])
        ts = HistoricalNormalizer(state_repo=repo).normalize("1846.HK")
        timeline = ts.narrative_timeline
        # Themes bucket populated from the condensed record narrative.
        assert len(timeline.themes_evolution) >= 1
        # Risks bucket populated.
        assert len(timeline.risks_evolution) >= 1
        # Capital-allocation bucket populated.
        assert len(timeline.capital_allocation_evolution) >= 1


# ======================================================================
# Dedupe — 36 redundant versions → 1 per period+source
# ======================================================================


class TestCanonicalStateDedupe:
    def test_normalizer_dedupes_and_keeps_latest_per_period_source(
        self,
    ) -> None:
        """Thirty-six persisted canonical-state versions for the same
        (period, source) collapse to the newest one only."""
        states = [
            _canonical(
                period_label="FY2024",
                extraction_date=datetime(2025, 1, i + 1, tzinfo=UTC),
                operating_income_in_bridge=Decimal(str(100 + i)),
            )
            for i in range(10)
        ]
        repo = _stub_repo(states)
        ts = HistoricalNormalizer(state_repo=repo).normalize("1846.HK")
        # 10 redundant versions of the same (period, source) → 1 record.
        assert len(ts.records) == 1
        # The newest version wins — its operating_income == 109.
        assert ts.records[0].operating_income == Decimal("109")

    def test_normalizer_keeps_distinct_periods_and_sources(self) -> None:
        """Dedupe respects the (period, source) key — distinct
        combinations all survive."""
        ar_2023 = _canonical(
            period_label="FY2023",
            period_end=date(2023, 12, 31),
            document_type="annual_report",
            extraction_date=datetime(2024, 1, 1, tzinfo=UTC),
        )
        ar_2024 = _canonical(
            period_label="FY2024",
            period_end=date(2024, 12, 31),
            document_type="annual_report",
            extraction_date=datetime(2025, 1, 1, tzinfo=UTC),
        )
        interim_h1 = _canonical(
            period_label="H1_2025",
            period_end=date(2025, 6, 30),
            audit_status="reviewed",
            document_type="interim_report",
            extraction_date=datetime(2025, 9, 1, tzinfo=UTC),
        )
        preliminary = _canonical(
            period_label="FY2025",
            period_end=date(2025, 12, 31),
            audit_status="unaudited",
            document_type="investor_presentation",
            extraction_date=datetime(2026, 3, 15, tzinfo=UTC),
        )
        repo = _stub_repo([ar_2023, ar_2024, interim_h1, preliminary])
        ts = HistoricalNormalizer(state_repo=repo).normalize("1846.HK")
        periods = {r.period for r in ts.records}
        assert periods == {"FY2023", "FY2024", "H1_2025", "FY2025"}
