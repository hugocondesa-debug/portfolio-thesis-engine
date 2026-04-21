"""Unit tests for :func:`parse_raw_extraction`."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_thesis_engine.ingestion.base import IngestionError
from portfolio_thesis_engine.ingestion.raw_extraction_parser import parse_raw_extraction

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "euroeyes" / "raw_extraction.yaml"


# ======================================================================
# 1. Happy path — the realistic EuroEyes fixture
# ======================================================================


class TestEuroEyesFixture:
    def test_parses_successfully(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        assert raw.ticker == "1846.HK"
        assert raw.company_name == "EuroEyes Medical Group"
        assert raw.reporting_currency.value == "HKD"
        assert raw.unit_scale == "millions"

    def test_two_fiscal_periods_with_primary(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        periods = [fp.period for fp in raw.fiscal_periods]
        assert periods == ["FY2024", "H1 2025"]
        assert raw.primary_period.period == "FY2024"

    def test_primary_statements_populated(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        assert raw.primary_is.revenue == Decimal("580.0")
        assert raw.primary_is.net_income == Decimal("75.0")
        assert raw.primary_bs.total_assets == Decimal("3200.0")
        assert raw.primary_bs.total_equity == Decimal("1900.0")
        assert raw.primary_cf is not None
        assert raw.primary_cf.operating_cash_flow == Decimal("135.0")

    def test_interim_period_also_parsed(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        h1 = raw.income_statement["H1 2025"]
        assert h1.revenue == Decimal("310.0")
        assert h1.net_income == Decimal("42.7")
        # No CF for interim — optional
        assert "H1 2025" not in raw.cash_flow

    def test_notes_populated(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        assert raw.notes.taxes is not None
        assert raw.notes.taxes.effective_tax_rate_percent == Decimal("21.9")
        assert len(raw.notes.taxes.reconciling_items) == 4
        assert raw.notes.leases is not None
        assert raw.notes.leases.rou_assets_additions == Decimal("55.0")
        assert len(raw.notes.provisions) == 2

    def test_segments_populated(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        assert raw.segments is not None
        assert raw.segments.by_geography is not None
        assert raw.segments.by_geography["FY2024"]["Greater China"] == Decimal("420.0")

    def test_historical_populated(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        assert raw.historical is not None
        assert len(raw.historical.revenue_by_year) == 5
        assert raw.historical.revenue_by_year["2024"] == Decimal("580.0")


# ======================================================================
# 2. Error paths
# ======================================================================


class TestErrorPaths:
    def test_missing_file(self, tmp_path: Path) -> None:
        with pytest.raises(IngestionError, match="file not found"):
            parse_raw_extraction(tmp_path / "absent.yaml")

    def test_invalid_yaml(self, tmp_path: Path) -> None:
        path = tmp_path / "bad.yaml"
        path.write_text("ticker: [unclosed", encoding="utf-8")
        with pytest.raises(IngestionError):
            parse_raw_extraction(path)

    def test_schema_violation_surfaces_as_ingestion_error(self, tmp_path: Path) -> None:
        path = tmp_path / "missing_fields.yaml"
        # Missing required fields (e.g. ticker, company_name, ...)
        path.write_text(
            """
unit_scale: "millions"
extraction_date: "2025-01-15"
source: "X"
fiscal_periods: []
income_statement: {}
balance_sheet: {}
""",
            encoding="utf-8",
        )
        with pytest.raises(IngestionError, match="schema validation failed"):
            parse_raw_extraction(path)

    def test_non_dict_yaml_surfaces_as_ingestion_error(self, tmp_path: Path) -> None:
        """YAML that parses as a non-dict (e.g. a list) should raise
        :class:`IngestionError`, not :class:`ValidationError`."""
        path = tmp_path / "list.yaml"
        path.write_text("- just\n- a\n- list\n", encoding="utf-8")
        with pytest.raises(IngestionError):
            parse_raw_extraction(path)


# ======================================================================
# 3. Decimal round-trip from the real fixture
# ======================================================================


class TestRoundTrip:
    def test_dump_and_reload_preserves_data(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        dumped = raw.to_yaml()
        from portfolio_thesis_engine.schemas.raw_extraction import RawExtraction

        reloaded = RawExtraction.from_yaml(dumped)
        assert reloaded == raw
