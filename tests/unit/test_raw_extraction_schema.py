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
        assert li.source_note == 10


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
