"""Unit tests for schemas.raw_extraction (Phase 1.5.3 as-reported)."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from portfolio_thesis_engine.schemas.common import Currency
from portfolio_thesis_engine.schemas.raw_extraction import (
    BalanceSheetPeriod,
    CashFlowPeriod,
    DocumentMetadata,
    DocumentType,
    EarningsPerShare,
    ExtractionType,
    FiscalPeriodData,
    HistoricalDataSeries,
    IncomeStatementPeriod,
    LineItem,
    NarrativeContent,
    Note,
    NoteTable,
    OperationalKPI,
    ProfitAttribution,
    RawExtraction,
    SegmentMetrics,
    SegmentReporting,
)

# ======================================================================
# LineItem — foundational
# ======================================================================


class TestLineItem:
    def test_minimal_line_item(self) -> None:
        li = LineItem(order=1, label="Revenue", value=Decimal("580"))
        assert li.order == 1
        assert li.label == "Revenue"
        assert li.value == Decimal("580")
        assert li.is_subtotal is False
        assert li.section is None

    def test_subtotal_flag(self) -> None:
        li = LineItem(
            order=3, label="Gross profit", value=Decimal("290"), is_subtotal=True
        )
        assert li.is_subtotal is True

    def test_null_value_allowed(self) -> None:
        li = LineItem(order=1, label="Deferred tax assets", value=None)
        assert li.value is None

    def test_order_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            LineItem(order=-1, label="X", value=Decimal("0"))

    def test_empty_label_rejected(self) -> None:
        with pytest.raises(ValidationError):
            LineItem(order=1, label="", value=Decimal("0"))

    def test_full_line_item(self) -> None:
        li = LineItem(
            order=5,
            label="Property, plant and equipment",
            value=Decimal("950"),
            section="non_current_assets",
            source_note=10,
            source_page=97,
            notes="Net of accumulated depreciation HKD 635M",
        )
        assert li.section == "non_current_assets"
        # source_note coerces int → str (Phase 1.5.4)
        assert li.source_note == "10"

    def test_source_note_composite_string(self) -> None:
        """Phase 1.5.4: source_note is a free-form string so composite
        / sub-note identifiers round-trip verbatim."""
        for value in ["3.3, 35", "29(d)", "32(a)", "38(b)", "5"]:
            li = LineItem(order=1, label="X", value=Decimal("0"), source_note=value)
            assert li.source_note == value

    def test_source_note_int_coerced_to_str(self) -> None:
        li = LineItem(order=1, label="X", value=Decimal("0"), source_note=13)
        assert li.source_note == "13"


# ======================================================================
# Statement periods
# ======================================================================


class TestStatementPeriods:
    def test_income_statement_period_default_empty(self) -> None:
        is_data = IncomeStatementPeriod()
        assert is_data.line_items == []
        assert is_data.profit_attribution is None
        assert is_data.earnings_per_share is None

    def test_income_statement_with_attribution_and_eps(self) -> None:
        is_data = IncomeStatementPeriod(
            reporting_period_label="Year ended 31 December 2024",
            line_items=[
                LineItem(order=1, label="Revenue", value=Decimal("580")),
                LineItem(
                    order=2, label="Profit for the year", value=Decimal("75"),
                    is_subtotal=True,
                ),
            ],
            profit_attribution=ProfitAttribution(
                parent=Decimal("75"),
                non_controlling_interests=Decimal("0"),
                total=Decimal("75"),
            ),
            earnings_per_share=EarningsPerShare(
                basic_value=Decimal("0.375"),
                basic_unit="HKD",
                diluted_value=Decimal("0.370"),
                diluted_unit="HKD",
                basic_weighted_avg_shares=Decimal("200"),
                diluted_weighted_avg_shares=Decimal("202.7"),
                shares_unit="millions",
            ),
        )
        assert is_data.profit_attribution is not None
        assert is_data.profit_attribution.parent == Decimal("75")
        assert is_data.earnings_per_share is not None
        assert is_data.earnings_per_share.basic_unit == "HKD"

    def test_balance_sheet_period_end_date(self) -> None:
        bs = BalanceSheetPeriod(period_end_date="2024-12-31")
        assert bs.period_end_date == "2024-12-31"

    def test_cash_flow_period_default_empty(self) -> None:
        cf = CashFlowPeriod()
        assert cf.line_items == []


# ======================================================================
# NoteTable + Note
# ======================================================================


class TestNotes:
    def test_note_table_minimal(self) -> None:
        nt = NoteTable()
        assert nt.table_label is None
        assert nt.columns == []
        assert nt.rows == []

    def test_note_table_full(self) -> None:
        nt = NoteTable(
            table_label="Rate reconciliation",
            columns=["Description", "HKD millions"],
            rows=[
                ["Statutory rate", Decimal("15.84")],
                ["Non-deductible expenses", Decimal("1.5")],
            ],
            unit_note="All amounts in HK$'millions",
        )
        assert len(nt.rows) == 2
        assert isinstance(nt.rows[0][1], Decimal)

    def test_note_minimal_valid(self) -> None:
        note = Note(title="Income tax")
        assert note.title == "Income tax"
        assert note.tables == []
        assert note.narrative_summary is None

    def test_note_empty_title_rejected(self) -> None:
        with pytest.raises(ValidationError):
            Note(title="")

    def test_note_with_tables_and_summary(self) -> None:
        note = Note(
            note_number="6",
            title="Income tax expense",
            source_pages=[84, 85],
            tables=[
                NoteTable(
                    table_label="Rate reconciliation",
                    columns=["Description", "HKD millions"],
                    rows=[["Statutory tax", Decimal("15.84")]],
                )
            ],
            narrative_summary="ETR reconciles as per table above.",
        )
        assert note.note_number == "6"
        assert len(note.tables) == 1


# ======================================================================
# Segments + Historical + KPIs
# ======================================================================


class TestSegments:
    def test_segment_metrics_free_form(self) -> None:
        sm = SegmentMetrics(
            segment_name="Greater China",
            metrics={
                "revenue": Decimal("420"),
                "operating_income": Decimal("85"),
            },
        )
        assert sm.metrics["revenue"] == Decimal("420")

    def test_segment_reporting(self) -> None:
        sr = SegmentReporting(
            period="FY2024",
            segment_type="geography",
            segments=[
                SegmentMetrics(
                    segment_name="Greater China",
                    metrics={"revenue": Decimal("420")},
                ),
            ],
            inter_segment_eliminations={"revenue": Decimal("-5")},
        )
        assert sr.period == "FY2024"
        assert sr.inter_segment_eliminations is not None
        assert sr.inter_segment_eliminations["revenue"] == Decimal("-5")


class TestHistorical:
    def test_historical_parallel_arrays(self) -> None:
        h = HistoricalDataSeries(
            source="5-year summary p.172",
            years=[2020, 2021, 2022, 2023, 2024],
            metrics={
                "revenue": [
                    Decimal("380"), Decimal("440"), Decimal("485"),
                    Decimal("520"), Decimal("580"),
                ],
                "net_income": [
                    None, Decimal("45"), Decimal("52"),
                    Decimal("60"), Decimal("75"),
                ],
            },
        )
        assert len(h.years) == 5
        assert h.metrics["net_income"][0] is None


class TestOperationalKPI:
    def test_operational_kpi_mixed_values(self) -> None:
        kpi = OperationalKPI(
            metric_label="Clinics total",
            source="MD&A",
            unit="count",
            values={"FY2024": Decimal("38"), "FY2023": Decimal("36")},
        )
        assert kpi.values["FY2024"] == Decimal("38")

    def test_operational_kpi_string_values(self) -> None:
        kpi = OperationalKPI(
            metric_label="Expansion outlook",
            source="MD&A",
            unit=None,
            values={"FY2024": "Strong growth in mainland"},
        )
        assert isinstance(kpi.values["FY2024"], str)

    def test_operational_kpi_accepts_extra_fields(self) -> None:
        """Phase 1.5.4: OperationalKPI is flexible — per-metric
        ``notes`` / ``methodology`` annotations round-trip."""
        kpi = OperationalKPI.model_validate({
            "metric_label": "Patient visits",
            "source": "MD&A",
            "unit": "thousands",
            "values": {"FY2024": "285"},
            "notes": "Includes dental screenings consolidated in 2024",
        })
        assert kpi.model_extra is not None
        assert "Includes dental" in kpi.model_extra["notes"]


class TestFlexibleContainers:
    """Phase 1.5.4: extras allowed on flexible containers."""

    def test_segment_metrics_accepts_none_values(self) -> None:
        """None values on SegmentMetrics.metrics round-trip unchanged
        (Decimal | None typing)."""
        sm = SegmentMetrics(
            segment_name="Greater China",
            metrics={
                "revenue": Decimal("420"),
                "gross_profit": None,
                "advertising_and_marketing": None,
            },
        )
        assert sm.metrics["revenue"] == Decimal("420")
        assert sm.metrics["gross_profit"] is None

    def test_segment_reporting_inter_segment_eliminations_none_values(self) -> None:
        """Phase 1.5.4: inter_segment_eliminations values are
        ``Decimal | None`` — YAML nulls survive."""
        sr = SegmentReporting(
            period="FY2024",
            segment_type="geography",
            segments=[],
            inter_segment_eliminations={
                "revenue": Decimal("-5"),
                "gross_profit": None,
            },
        )
        assert sr.inter_segment_eliminations is not None
        assert sr.inter_segment_eliminations["gross_profit"] is None

    def test_segment_reporting_accepts_extra_fields(self) -> None:
        """Phase 1.5.4: SegmentReporting accepts ``source_note``,
        ``reconciliation_to_group``, ``extraction_caveat``."""
        sr = SegmentReporting.model_validate({
            "period": "FY2024",
            "segment_type": "geography",
            "segments": [],
            "source_note": "32(a)",
            "reconciliation_to_group": "Reconciled per Note 32 p. 145",
            "extraction_caveat": "Inter-segment eliminations estimated",
        })
        assert sr.model_extra is not None
        assert sr.model_extra["source_note"] == "32(a)"

    def test_document_metadata_accepts_extra_fields(self) -> None:
        """Phase 1.5.4: metadata accepts arbitrary provenance fields."""
        md = DocumentMetadata.model_validate({
            "ticker": "X",
            "company_name": "X",
            "document_type": "annual_report",
            "extraction_type": "numeric",
            "reporting_currency": "USD",
            "unit_scale": "units",
            "extraction_date": "2025-01-01",
            "source_file_name": "X_AR_2024.pdf",
            "upstream_ingest_id": "abc123",
        })
        assert md.model_extra is not None
        assert md.model_extra["source_file_name"] == "X_AR_2024.pdf"

    def test_income_statement_period_accepts_extras(self) -> None:
        """IS period accepts extras like
        ``total_comprehensive_income_attribution`` (OCI footer)."""
        is_data = IncomeStatementPeriod.model_validate({
            "line_items": [],
            "total_comprehensive_income_attribution": {
                "parent": "75.0",
                "non_controlling_interests": "0.0",
            },
        })
        assert is_data.model_extra is not None
        assert "total_comprehensive_income_attribution" in is_data.model_extra

    def test_note_accepts_extras(self) -> None:
        note = Note.model_validate({
            "title": "Income tax",
            "narrative_summary": "Summary in English.",
            "narrative_summary_fr": "Résumé en français.",
        })
        assert note.model_extra is not None
        assert note.model_extra["narrative_summary_fr"].startswith("Résumé")

    def test_line_item_still_forbids_extras(self) -> None:
        """LineItem core structure stays strict — catches typos."""
        with pytest.raises(ValidationError):
            LineItem.model_validate({
                "order": 1, "label": "X", "value": "0",
                "bogus_field": "typo",
            })

    def test_note_table_still_forbids_extras(self) -> None:
        with pytest.raises(ValidationError):
            NoteTable.model_validate({
                "columns": [], "rows": [],
                "bogus_field": "typo",
            })


# ======================================================================
# DocumentMetadata
# ======================================================================


class TestDocumentMetadata:
    def test_minimal_metadata(self) -> None:
        md = DocumentMetadata(
            ticker="1846.HK",
            company_name="EuroEyes",
            document_type=DocumentType.ANNUAL_REPORT,
            extraction_type=ExtractionType.NUMERIC,
            reporting_currency=Currency.HKD,
            unit_scale="millions",
            extraction_date="2025-04-15",
        )
        assert md.fiscal_year is None  # now optional
        assert md.extractor == "human + Claude.ai Project"

    def test_fiscal_year_optional(self) -> None:
        md = DocumentMetadata(
            ticker="X",
            company_name="X",
            document_type=DocumentType.ANNUAL_REPORT,
            extraction_type=ExtractionType.NUMERIC,
            reporting_currency=Currency.USD,
            unit_scale="units",
            extraction_date="2025-01-01",
        )
        assert md.fiscal_year is None

    def test_fiscal_year_bounds(self) -> None:
        with pytest.raises(ValidationError):
            DocumentMetadata(
                ticker="X",
                company_name="X",
                document_type=DocumentType.ANNUAL_REPORT,
                extraction_type=ExtractionType.NUMERIC,
                reporting_currency=Currency.USD,
                unit_scale="units",
                fiscal_year=1800,
                extraction_date="2025-01-01",
            )


# ======================================================================
# RawExtraction validators
# ======================================================================


def _minimal_numeric_raw() -> dict:
    return {
        "metadata": {
            "ticker": "TST",
            "company_name": "Test",
            "document_type": "annual_report",
            "extraction_type": "numeric",
            "reporting_currency": "USD",
            "unit_scale": "units",
            "extraction_date": "2025-01-01",
            "fiscal_periods": [
                {"period": "FY2024", "end_date": "2024-12-31", "is_primary": True},
            ],
        },
        "income_statement": {
            "FY2024": {
                "line_items": [
                    {"order": 1, "label": "Revenue", "value": "100"},
                    {
                        "order": 2,
                        "label": "Profit for the year",
                        "value": "10",
                        "is_subtotal": True,
                    },
                ],
            },
        },
        "balance_sheet": {
            "FY2024": {
                "line_items": [
                    {
                        "order": 1,
                        "label": "Total assets",
                        "value": "500",
                        "section": "total_assets",
                        "is_subtotal": True,
                    },
                ],
            },
        },
    }


class TestRawExtractionValidator:
    def test_minimal_numeric_extraction_valid(self) -> None:
        raw = RawExtraction.model_validate(_minimal_numeric_raw())
        assert raw.primary_period.period == "FY2024"
        assert raw.primary_is is not None
        assert len(raw.primary_is.line_items) == 2

    def test_numeric_missing_fiscal_periods_rejected(self) -> None:
        payload = _minimal_numeric_raw()
        payload["metadata"]["fiscal_periods"] = []
        with pytest.raises(ValidationError, match="fiscal_periods"):
            RawExtraction.model_validate(payload)

    def test_numeric_multiple_primaries_rejected(self) -> None:
        payload = _minimal_numeric_raw()
        payload["metadata"]["fiscal_periods"].append(
            {"period": "FY2023", "end_date": "2023-12-31", "is_primary": True}
        )
        with pytest.raises(ValidationError, match="is_primary"):
            RawExtraction.model_validate(payload)

    def test_numeric_missing_is_rejected(self) -> None:
        payload = _minimal_numeric_raw()
        del payload["income_statement"]["FY2024"]
        with pytest.raises(ValidationError, match="no income_statement"):
            RawExtraction.model_validate(payload)

    def test_numeric_empty_is_line_items_rejected(self) -> None:
        payload = _minimal_numeric_raw()
        payload["income_statement"]["FY2024"]["line_items"] = []
        with pytest.raises(ValidationError, match="no line_items"):
            RawExtraction.model_validate(payload)

    def test_numeric_missing_bs_rejected(self) -> None:
        payload = _minimal_numeric_raw()
        del payload["balance_sheet"]["FY2024"]
        with pytest.raises(ValidationError, match="no balance_sheet"):
            RawExtraction.model_validate(payload)

    def test_narrative_requires_populated_narrative(self) -> None:
        payload = {
            "metadata": {
                "ticker": "X",
                "company_name": "X",
                "document_type": "earnings_call",
                "extraction_type": "narrative",
                "reporting_currency": "USD",
                "unit_scale": "units",
                "extraction_date": "2025-01-01",
                "fiscal_periods": [
                    {"period": "FY2024", "end_date": "2024-12-31", "is_primary": True},
                ],
            },
        }
        with pytest.raises(ValidationError, match="narrative"):
            RawExtraction.model_validate(payload)

    def test_narrative_valid_with_key_themes(self) -> None:
        payload = {
            "metadata": {
                "ticker": "X",
                "company_name": "X",
                "document_type": "earnings_call",
                "extraction_type": "narrative",
                "reporting_currency": "USD",
                "unit_scale": "units",
                "extraction_date": "2025-01-01",
                "fiscal_periods": [
                    {"period": "FY2024", "end_date": "2024-12-31", "is_primary": True},
                ],
            },
            "narrative": {"key_themes": ["AI-driven growth"]},
        }
        raw = RawExtraction.model_validate(payload)
        assert raw.narrative is not None


# ======================================================================
# Convenience accessors
# ======================================================================


class TestConvenience:
    def test_primary_period_explicit(self) -> None:
        payload = _minimal_numeric_raw()
        payload["metadata"]["fiscal_periods"].append(
            {"period": "FY2023", "end_date": "2023-12-31", "is_primary": False}
        )
        raw = RawExtraction.model_validate(payload)
        assert raw.primary_period.period == "FY2024"

    def test_primary_period_defaults_to_first(self) -> None:
        """No period flagged is_primary → first wins."""
        payload = _minimal_numeric_raw()
        payload["metadata"]["fiscal_periods"][0]["is_primary"] = False
        raw = RawExtraction.model_validate(payload)
        assert raw.primary_period.period == "FY2024"

    def test_primary_is_returns_is_period(self) -> None:
        raw = RawExtraction.model_validate(_minimal_numeric_raw())
        is_data = raw.primary_is
        assert is_data is not None
        assert len(is_data.line_items) == 2

    def test_primary_bs_returns_bs_period(self) -> None:
        raw = RawExtraction.model_validate(_minimal_numeric_raw())
        bs_data = raw.primary_bs
        assert bs_data is not None

    def test_primary_cf_absent(self) -> None:
        raw = RawExtraction.model_validate(_minimal_numeric_raw())
        assert raw.primary_cf is None


# ======================================================================
# Round-trip
# ======================================================================


class TestRoundTrip:
    def test_yaml_round_trip(self) -> None:
        payload = _minimal_numeric_raw()
        raw = RawExtraction.model_validate(payload)
        dumped = raw.to_yaml()
        reloaded = RawExtraction.from_yaml(dumped)
        assert reloaded.metadata.ticker == "TST"
        assert reloaded.primary_is is not None
        assert raw.primary_is is not None
        assert (
            reloaded.primary_is.line_items[0].label
            == raw.primary_is.line_items[0].label
        )


# ======================================================================
# NarrativeContent
# ======================================================================


class TestNarrativeContent:
    def test_narrative_default_empty(self) -> None:
        n = NarrativeContent()
        assert n.key_themes == []

    def test_narrative_populated(self) -> None:
        n = NarrativeContent(
            key_themes=["Digital transformation"],
            risks_mentioned=["FX volatility"],
        )
        assert len(n.key_themes) == 1


# ======================================================================
# FiscalPeriodData
# ======================================================================


class TestFiscalPeriodData:
    def test_defaults(self) -> None:
        fpd = FiscalPeriodData(period="FY2024", end_date="2024-12-31")
        assert fpd.is_primary is False
        assert fpd.period_type == "FY"

    def test_period_type_literal(self) -> None:
        fpd = FiscalPeriodData(
            period="H1 2025", end_date="2025-06-30", period_type="H1"
        )
        assert fpd.period_type == "H1"
