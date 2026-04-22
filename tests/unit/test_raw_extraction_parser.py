"""Unit tests for ingestion.raw_extraction_parser (Phase 1.5.3)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_thesis_engine.ingestion.base import IngestionError
from portfolio_thesis_engine.ingestion.raw_extraction_parser import (
    normalise_unit_scale,
    parse_raw_extraction,
)
from portfolio_thesis_engine.schemas.common import Currency
from portfolio_thesis_engine.schemas.raw_extraction import (
    DocumentType,
    ExtractionType,
    RawExtraction,
)

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "euroeyes" / "raw_extraction.yaml"


# ======================================================================
# Happy path — real fixture
# ======================================================================


class TestParseRealFixture:
    def test_parses_and_normalises_fixture(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        assert raw.metadata.ticker == "1846.HK"
        assert raw.primary_is is not None
        revenue_line = next(
            li for li in raw.primary_is.line_items if li.label == "Revenue"
        )
        # Fixture declares "millions"; parser multiplies.
        assert revenue_line.value == Decimal("580000000.0")
        assert raw.metadata.unit_scale == "units"

    def test_returns_pydantic_object(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        assert isinstance(raw, RawExtraction)

    def test_idempotent(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        again = normalise_unit_scale(raw)
        assert again is raw  # no-op returns same object


# ======================================================================
# Error wrapping
# ======================================================================


class TestErrorWrapping:
    def test_file_not_found_raises(self, tmp_path: Path) -> None:
        with pytest.raises(IngestionError, match="file not found"):
            parse_raw_extraction(tmp_path / "does_not_exist.yaml")

    def test_yaml_syntax_error_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text("this: : not: valid: yaml: :::", encoding="utf-8")
        with pytest.raises(IngestionError):
            parse_raw_extraction(bad)

    def test_schema_violation_raises(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.yaml"
        bad.write_text(
            """
metadata:
  ticker: "X"
  company_name: "X"
  document_type: "annual_report"
  extraction_type: "numeric"
  reporting_currency: "USD"
  unit_scale: "units"
  extraction_date: "2025-01-01"
  fiscal_periods: []
""",
            encoding="utf-8",
        )
        with pytest.raises(IngestionError, match="schema validation failed"):
            parse_raw_extraction(bad)


# ======================================================================
# Unit-scale normalisation — line items
# ======================================================================


def _base_payload(
    extra_is_lines: list[dict] | None = None,
    extra_bs_lines: list[dict] | None = None,
) -> dict:
    payload: dict = {
        "metadata": {
            "ticker": "X",
            "company_name": "X",
            "document_type": DocumentType.ANNUAL_REPORT,
            "extraction_type": ExtractionType.NUMERIC,
            "reporting_currency": Currency.USD,
            "unit_scale": "millions",
            "extraction_date": "2025-01-01",
            "fiscal_periods": [
                {"period": "FY2024", "end_date": "2024-12-31", "is_primary": True},
            ],
        },
        "income_statement": {
            "FY2024": {
                "line_items": [
                    {"order": 1, "label": "Revenue", "value": "100"},
                    {"order": 2, "label": "Cost of sales", "value": "-40"},
                    {
                        "order": 3, "label": "Profit for the year",
                        "value": "30", "is_subtotal": True,
                    },
                    *(extra_is_lines or []),
                ],
                "profit_attribution": {
                    "parent": "30",
                    "non_controlling_interests": "0",
                    "total": "30",
                },
                "earnings_per_share": {
                    "basic_value": "0.15",
                    "basic_weighted_avg_shares": "200",
                },
            },
        },
        "balance_sheet": {
            "FY2024": {
                "line_items": [
                    {
                        "order": 1, "label": "Total assets",
                        "value": "500", "section": "total_assets",
                        "is_subtotal": True,
                    },
                    *(extra_bs_lines or []),
                ],
            },
        },
    }
    return payload


class TestLineItemNormalisation:
    def test_is_line_items_scaled_by_millions(self) -> None:
        raw = RawExtraction.model_validate(_base_payload())
        normalised = normalise_unit_scale(raw)
        assert normalised.metadata.unit_scale == "units"
        assert normalised.primary_is is not None
        revenue = next(
            li for li in normalised.primary_is.line_items if li.label == "Revenue"
        )
        assert revenue.value == Decimal("100") * Decimal("1000000")

    def test_profit_attribution_scaled(self) -> None:
        raw = RawExtraction.model_validate(_base_payload())
        normalised = normalise_unit_scale(raw)
        assert normalised.primary_is is not None
        pa = normalised.primary_is.profit_attribution
        assert pa is not None
        assert pa.parent == Decimal("30") * Decimal("1000000")

    def test_eps_not_scaled(self) -> None:
        """Per-share values pass through without scaling."""
        raw = RawExtraction.model_validate(_base_payload())
        normalised = normalise_unit_scale(raw)
        assert normalised.primary_is is not None
        eps = normalised.primary_is.earnings_per_share
        assert eps is not None
        assert eps.basic_value == Decimal("0.15")
        assert eps.basic_weighted_avg_shares == Decimal("200")

    def test_thousands_scale(self) -> None:
        payload = _base_payload()
        payload["metadata"]["unit_scale"] = "thousands"
        raw = RawExtraction.model_validate(payload)
        normalised = normalise_unit_scale(raw)
        assert normalised.primary_is is not None
        revenue = next(
            li for li in normalised.primary_is.line_items if li.label == "Revenue"
        )
        assert revenue.value == Decimal("100000")

    def test_null_values_preserved(self) -> None:
        payload = _base_payload(
            extra_is_lines=[{"order": 4, "label": "Deferred tax", "value": None}]
        )
        raw = RawExtraction.model_validate(payload)
        normalised = normalise_unit_scale(raw)
        assert normalised.primary_is is not None
        deferred = next(
            li for li in normalised.primary_is.line_items
            if li.label == "Deferred tax"
        )
        assert deferred.value is None


# ======================================================================
# Note-table scaling
# ======================================================================


class TestNoteScaling:
    def test_note_table_decimal_cells_scaled(self) -> None:
        payload = _base_payload()
        payload["notes"] = [
            {
                "title": "Income tax",
                "tables": [
                    {
                        "columns": ["Label", "HKD millions"],
                        "rows": [
                            ["Statutory", "15.84"],
                            ["Effective", "21.00"],
                        ],
                    }
                ],
            }
        ]
        raw = RawExtraction.model_validate(payload)
        normalised = normalise_unit_scale(raw)
        row0 = normalised.notes[0].tables[0].rows[0]
        # String label passes through
        assert row0[0] == "Statutory"
        # Decimal cell scaled
        assert row0[1] == Decimal("15.84") * Decimal("1000000")


# ======================================================================
# Segments / historical / KPIs scaling
# ======================================================================


class TestSegmentsScaling:
    def test_segment_metrics_scaled(self) -> None:
        payload = _base_payload()
        payload["segments"] = [
            {
                "period": "FY2024",
                "segment_type": "geography",
                "segments": [
                    {
                        "segment_name": "Greater China",
                        "metrics": {"revenue": "420", "operating_income": "85"},
                    },
                ],
                "inter_segment_eliminations": {"revenue": "-5"},
            }
        ]
        raw = RawExtraction.model_validate(payload)
        normalised = normalise_unit_scale(raw)
        sr = normalised.segments[0]
        assert sr.segments[0].metrics["revenue"] == Decimal("420000000")
        assert sr.inter_segment_eliminations is not None
        assert sr.inter_segment_eliminations["revenue"] == Decimal("-5000000")


class TestHistoricalScaling:
    def test_historical_values_scaled(self) -> None:
        payload = _base_payload()
        payload["historical"] = {
            "source": "5Y summary",
            "years": [2023, 2024],
            "metrics": {"revenue": ["50", "60"]},
        }
        raw = RawExtraction.model_validate(payload)
        normalised = normalise_unit_scale(raw)
        assert normalised.historical is not None
        assert normalised.historical.metrics["revenue"][0] == Decimal("50000000")


class TestOperationalKPIScaling:
    def test_monetary_kpi_scaled(self) -> None:
        payload = _base_payload()
        payload["operational_kpis"] = [
            {
                "metric_label": "Total compensation",
                "source": "MD&A",
                "unit": "USD millions",
                "values": {"FY2024": "50"},
            },
            {
                "metric_label": "Headcount",
                "source": "MD&A",
                "unit": "count",
                "values": {"FY2024": "850"},
            },
        ]
        raw = RawExtraction.model_validate(payload)
        normalised = normalise_unit_scale(raw)
        # Monetary (USD in unit) scaled
        comp_kpi = normalised.operational_kpis[0]
        assert comp_kpi.values["FY2024"] == Decimal("50000000")
        # Count (no currency marker) NOT scaled — the schema coerces
        # "850" → Decimal("850") at load time but the parser leaves
        # it at face value.
        headcount_kpi = normalised.operational_kpis[1]
        assert headcount_kpi.values["FY2024"] == Decimal("850")
