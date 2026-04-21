"""Unit tests for :func:`parse_raw_extraction` + unit-scale normalisation."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_thesis_engine.ingestion.base import IngestionError
from portfolio_thesis_engine.ingestion.raw_extraction_parser import (
    normalise_unit_scale,
    parse_raw_extraction,
)
from portfolio_thesis_engine.schemas.raw_extraction import RawExtraction

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "euroeyes" / "raw_extraction.yaml"


def _minimal_payload(unit_scale: str = "units") -> dict:
    return {
        "metadata": {
            "ticker": "TEST",
            "company_name": "Test Co",
            "document_type": "annual_report",
            "extraction_type": "numeric",
            "reporting_currency": "USD",
            "unit_scale": unit_scale,
            "fiscal_year": 2024,
            "extraction_date": "2025-01-15",
            "fiscal_periods": [
                {"period": "FY2024", "end_date": "2024-12-31", "is_primary": True},
            ],
        },
        "income_statement": {
            "FY2024": {
                "revenue": "500",
                "cost_of_sales": "-300",
                "operating_income": "100",
                "net_income": "75",
                "shares_basic_weighted_avg": "200",
                "extensions": {"other_income": "5"},
            },
        },
        "balance_sheet": {
            "FY2024": {
                "total_assets": "3000",
                "total_equity": "2000",
                "total_liabilities": "1000",
            },
        },
        "cash_flow": {
            "FY2024": {
                "operating_cash_flow": "130",
                "capex": "-75",
            },
        },
    }


# ======================================================================
# 1. Happy path — the realistic EuroEyes fixture
# ======================================================================


class TestEuroEyesFixture:
    def test_parses_successfully(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        assert raw.metadata.ticker == "1846.HK"
        # Fixture is millions → parser normalises to units.
        assert raw.metadata.unit_scale == "units"
        # Revenue 580M → 580_000_000
        assert raw.primary_is is not None
        assert raw.primary_is.revenue == Decimal("580000000.0")

    def test_notes_populated_after_normalisation(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        assert raw.notes.taxes is not None
        # Tax rates stay as percentages (not scaled)
        assert raw.notes.taxes.effective_tax_rate_percent == Decimal("21.9")
        # But reconciling item amounts are scaled
        assert raw.notes.taxes.reconciling_items[1].amount == Decimal("1500000.0")
        # Leases: additions scaled
        assert raw.notes.leases is not None
        assert raw.notes.leases.rou_assets_additions == Decimal("55000000.0")
        # Provisions: amounts scaled
        assert raw.notes.provisions[0].amount == Decimal("8000000.0")
        # Goodwill: top-level + by_cgu scaled
        assert raw.notes.goodwill is not None
        assert raw.notes.goodwill.closing == Decimal("600000000.0")
        assert raw.notes.goodwill.by_cgu["Greater China"] == Decimal("420000000.0")

    def test_eps_not_scaled(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        assert raw.primary_is is not None
        assert raw.primary_is.eps_basic == Decimal("0.375")

    def test_shares_not_scaled(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        assert raw.primary_is is not None
        assert raw.primary_is.shares_basic_weighted_avg == Decimal("200.0")

    def test_employee_benefits_money_only_scaled(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        assert raw.notes.employee_benefits is not None
        # Headcount stays as 850 (count, not money)
        assert raw.notes.employee_benefits.headcount == Decimal("850")
        # Compensation scales
        assert raw.notes.employee_benefits.total_compensation == Decimal("382500000.0")

    def test_sbc_expense_only_scales(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        assert raw.notes.share_based_compensation is not None
        # Expense scales
        assert raw.notes.share_based_compensation.expense == Decimal("6500000.0")
        # Share counts (granted/outstanding) do not scale
        assert raw.notes.share_based_compensation.stock_options_outstanding == Decimal("2.8")


# ======================================================================
# 2. Unit-scale normalisation — unit tests
# ======================================================================


class TestUnitScaleNormalisation:
    def test_units_is_noop(self) -> None:
        raw = RawExtraction.model_validate(_minimal_payload("units"))
        normed = normalise_unit_scale(raw)
        assert normed is raw  # Same object — no rebuild.

    def test_thousands_multiplied_by_1000(self) -> None:
        raw = RawExtraction.model_validate(_minimal_payload("thousands"))
        normed = normalise_unit_scale(raw)
        assert normed.metadata.unit_scale == "units"
        assert normed.primary_is is not None
        # 500 × 1000 = 500_000
        assert normed.primary_is.revenue == Decimal("500000")
        assert normed.primary_is.cost_of_sales == Decimal("-300000")
        # Extensions also scaled
        assert normed.primary_is.extensions["other_income"] == Decimal("5000")

    def test_millions_multiplied_by_1_000_000(self) -> None:
        raw = RawExtraction.model_validate(_minimal_payload("millions"))
        normed = normalise_unit_scale(raw)
        assert normed.metadata.unit_scale == "units"
        assert normed.primary_is is not None
        assert normed.primary_is.revenue == Decimal("500000000")
        assert normed.primary_bs is not None
        assert normed.primary_bs.total_assets == Decimal("3000000000")

    def test_eps_not_scaled_during_normalisation(self) -> None:
        """EPS / shares are non-monetary and must NOT be multiplied."""
        raw = RawExtraction.model_validate(_minimal_payload("millions"))
        # Attach EPS
        payload = _minimal_payload("millions")
        payload["income_statement"]["FY2024"]["eps_basic"] = "0.50"
        raw = RawExtraction.model_validate(payload)
        normed = normalise_unit_scale(raw)
        assert normed.primary_is is not None
        assert normed.primary_is.eps_basic == Decimal("0.50")  # unchanged

    def test_idempotent_second_call(self) -> None:
        """Calling normalise on already-units data is a no-op."""
        raw = RawExtraction.model_validate(_minimal_payload("millions"))
        once = normalise_unit_scale(raw)
        twice = normalise_unit_scale(once)
        assert once.primary_is is not None
        assert twice.primary_is is not None
        assert once.primary_is.revenue == twice.primary_is.revenue

    def test_notes_money_scaled(self) -> None:
        payload = _minimal_payload("thousands")
        payload["notes"] = {
            "taxes": {
                "effective_tax_rate_percent": "25",
                "reconciling_items": [
                    {"description": "Item A", "amount": "100"},
                ],
            },
            "provisions": [
                {"description": "Warranty", "amount": "50"},
            ],
        }
        raw = RawExtraction.model_validate(payload)
        normed = normalise_unit_scale(raw)
        # Tax rate unchanged
        assert normed.notes.taxes is not None
        assert normed.notes.taxes.effective_tax_rate_percent == Decimal("25")
        # Reconciling amount scaled
        assert normed.notes.taxes.reconciling_items[0].amount == Decimal("100000")
        # Provision amount scaled
        assert normed.notes.provisions[0].amount == Decimal("50000")


# ======================================================================
# 3. Error paths
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

    def test_schema_violation_surfaces_as_ingestion_error(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "missing_fields.yaml"
        path.write_text(
            """
metadata:
  ticker: "X"
  company_name: "Y"
  document_type: "annual_report"
  extraction_type: "numeric"
  reporting_currency: "USD"
  unit_scale: "units"
  fiscal_year: 2024
  extraction_date: "2025-01-01"
  fiscal_periods: []
income_statement: {}
balance_sheet: {}
""",
            encoding="utf-8",
        )
        with pytest.raises(IngestionError, match="schema validation failed"):
            parse_raw_extraction(path)


# ======================================================================
# 4. Round-trip from the real fixture
# ======================================================================


class TestRoundTrip:
    def test_dump_and_reload_preserves_data(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        dumped = raw.to_yaml()
        reloaded = RawExtraction.from_yaml(dumped)
        # After parse + normalise + dump + reload, both are in units.
        assert reloaded.metadata.unit_scale == "units"
        assert reloaded == raw
