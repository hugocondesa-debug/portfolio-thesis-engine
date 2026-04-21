"""Unit tests for extraction.raw_extraction_adapter.

Sprint-2 shim: translates :class:`RawExtraction` to the Phase 1
:class:`SectionExtractionResult` shape the extraction modules still
consume. Sprint 3 rewrites the modules + deletes this adapter.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_thesis_engine.extraction.raw_extraction_adapter import (
    _TAX_CLASSIFICATION_TO_CATEGORY,
    SectionExtractionResult,
    StructuredSection,
    adapt_raw_extraction,
)
from portfolio_thesis_engine.ingestion.raw_extraction_parser import parse_raw_extraction

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "euroeyes" / "raw_extraction.yaml"


# ======================================================================
# 1. Top-level shape
# ======================================================================


class TestTopLevel:
    def test_adapter_returns_section_result(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        result = adapt_raw_extraction(raw)
        assert isinstance(result, SectionExtractionResult)
        assert result.ticker == "1846.HK"
        assert result.fiscal_period == "FY2024"
        assert result.doc_id == "1846.HK/raw_extraction"

    def test_custom_doc_id(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        result = adapt_raw_extraction(raw, doc_id="custom-doc")
        assert result.doc_id == "custom-doc"

    def test_sections_in_fixed_order(self) -> None:
        """Fixture has IS + BS + CF + taxes + leases — expect all 5
        sections in the canonical order Modules A/B/C consume."""
        raw = parse_raw_extraction(_FIXTURE)
        result = adapt_raw_extraction(raw)
        assert [s.section_type for s in result.sections] == [
            "income_statement",
            "balance_sheet",
            "cash_flow",
            "notes_taxes",
            "notes_leases",
        ]


# ======================================================================
# 2. Income statement translation
# ======================================================================


class TestIncomeStatement:
    def test_line_items_carry_revenue_through_tax(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        result = adapt_raw_extraction(raw)
        is_section = next(s for s in result.sections if s.section_type == "income_statement")
        parsed = is_section.parsed_data
        assert parsed is not None
        categories = [ln["category"] for ln in parsed["line_items"]]
        # Fixture populates revenue, cost_of_sales, opex ×2, d_and_a,
        # operating_income, finance_income, finance_expense, tax,
        # net_income — ten categories plus any extensions.
        assert categories.count("revenue") >= 1
        assert categories.count("cost_of_sales") >= 1
        assert categories.count("opex") >= 2
        assert categories.count("d_and_a") == 1
        assert categories.count("operating_income") == 1
        assert categories.count("net_income") == 1

    def test_revenue_value_normalised_to_base_units(self) -> None:
        """Fixture unit_scale='millions'; parser normalised → 580M becomes 580_000_000."""
        raw = parse_raw_extraction(_FIXTURE)
        result = adapt_raw_extraction(raw)
        is_section = next(s for s in result.sections if s.section_type == "income_statement")
        revenue_item = next(
            ln for ln in is_section.parsed_data["line_items"] if ln["category"] == "revenue"
        )
        assert revenue_item["value_current"] == Decimal("580000000.0")

    def test_extension_fields_category_other(self) -> None:
        # Use schema directly to pin extension handling.
        from portfolio_thesis_engine.schemas.common import Currency
        from portfolio_thesis_engine.schemas.raw_extraction import (
            DocumentType,
            ExtractionType,
            RawExtraction,
        )

        raw = RawExtraction.model_validate({
            "metadata": {
                "ticker": "TEST",
                "company_name": "Test",
                "document_type": DocumentType.ANNUAL_REPORT,
                "extraction_type": ExtractionType.NUMERIC,
                "reporting_currency": Currency.USD,
                "unit_scale": "units",
                "fiscal_year": 2024,
                "extraction_date": "2025-01-01",
                "fiscal_periods": [
                    {"period": "FY2024", "end_date": "2024-12-31", "is_primary": True}
                ],
            },
            "income_statement": {
                "FY2024": {
                    "revenue": "100",
                    "net_income": "10",
                    "extensions": {"custom_line": "5"},
                },
            },
            "balance_sheet": {
                "FY2024": {"total_assets": "500", "total_equity": "300"},
            },
        })
        result = adapt_raw_extraction(raw)
        is_section = next(s for s in result.sections if s.section_type == "income_statement")
        ext_item = next(
            (ln for ln in is_section.parsed_data["line_items"] if "Custom" in ln["label"]),
            None,
        )
        assert ext_item is not None
        assert ext_item["category"] == "other"


# ======================================================================
# 3. Balance sheet translation
# ======================================================================


class TestBalanceSheet:
    def test_cash_and_operating_assets(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        result = adapt_raw_extraction(raw)
        bs = next(s for s in result.sections if s.section_type == "balance_sheet")
        categories = [ln["category"] for ln in bs.parsed_data["line_items"]]
        assert categories.count("cash") == 1
        # Operating assets: receivables, inventory, PP&E, ROU, non-current other
        assert categories.count("operating_assets") >= 4
        # Goodwill + intangibles_other = 2 intangibles entries
        assert categories.count("intangibles") == 2
        assert categories.count("financial_liabilities") >= 2  # short + long-term debt
        assert categories.count("lease_liabilities") == 2  # current + non-current
        assert categories.count("equity") >= 2  # share_capital + retained_earnings + …

    def test_total_assets_carries_through(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        result = adapt_raw_extraction(raw)
        bs = next(s for s in result.sections if s.section_type == "balance_sheet")
        total = next(
            ln for ln in bs.parsed_data["line_items"]
            if ln["category"] == "total_assets"
        )
        # 3200M normalised
        assert total["value_current"] == Decimal("3200000000.0")


# ======================================================================
# 4. Cash flow translation
# ======================================================================


class TestCashFlow:
    def test_cfo_capex_cfi_cff(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        result = adapt_raw_extraction(raw)
        cf = next(s for s in result.sections if s.section_type == "cash_flow")
        categories = [ln["category"] for ln in cf.parsed_data["line_items"]]
        assert "cfo" in categories
        assert "capex" in categories
        assert "cfi" in categories
        assert "cff" in categories
        assert "dividends" in categories


# ======================================================================
# 5. Tax note translation
# ======================================================================


class TestTaxNote:
    def test_reconciling_items_remapped(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        result = adapt_raw_extraction(raw)
        tax = next(s for s in result.sections if s.section_type == "notes_taxes")
        parsed = tax.parsed_data
        assert parsed is not None
        # 4 items in fixture; check their categories mapped correctly.
        items = parsed["reconciling_items"]
        assert len(items) == 4
        for item in items:
            assert item["category"] in _TAX_CLASSIFICATION_TO_CATEGORY.values()

    def test_rates_populated(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        result = adapt_raw_extraction(raw)
        tax = next(s for s in result.sections if s.section_type == "notes_taxes")
        parsed = tax.parsed_data
        assert parsed["effective_rate_pct"] == Decimal("21.9")
        assert parsed["statutory_rate_pct"] == Decimal("16.5")

    def test_reported_tax_from_is_income_tax(self) -> None:
        """``reported_tax_expense`` = |income_tax| so Module A treats
        it the same as the Phase 1 LLM parser did."""
        raw = parse_raw_extraction(_FIXTURE)
        result = adapt_raw_extraction(raw)
        tax = next(s for s in result.sections if s.section_type == "notes_taxes")
        # Fixture income_tax = -21.0 × 1M = -21_000_000; adapter uses abs.
        assert tax.parsed_data["reported_tax_expense"] == Decimal("21000000.0")

    def test_statutory_tax_derived(self) -> None:
        """``statutory_tax`` = PBT × statutory_rate / 100 when both present."""
        raw = parse_raw_extraction(_FIXTURE)
        result = adapt_raw_extraction(raw)
        tax = next(s for s in result.sections if s.section_type == "notes_taxes")
        # 96M × 16.5% = 15.84M
        expected = Decimal("96000000.0") * Decimal("16.5") / Decimal("100")
        assert abs(tax.parsed_data["statutory_tax"] - expected) < Decimal("0.01")


# ======================================================================
# 6. Lease note translation
# ======================================================================


class TestLeaseNote:
    def test_lease_movement_populated(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        result = adapt_raw_extraction(raw)
        leases = next(s for s in result.sections if s.section_type == "notes_leases")
        movement = leases.parsed_data["lease_liability_movement"]
        # Fixture values × 1M
        assert movement["opening_balance"] == Decimal("350000000.0")
        assert movement["closing_balance"] == Decimal("370000000.0")
        assert movement["additions"] == Decimal("55000000.0")
        assert movement["principal_payments"] == Decimal("35000000.0")

    def test_rou_by_category_from_bs(self) -> None:
        """ROU is aggregated on the new BS; adapter emits a single row
        rather than synthesising categories it doesn't have."""
        raw = parse_raw_extraction(_FIXTURE)
        result = adapt_raw_extraction(raw)
        leases = next(s for s in result.sections if s.section_type == "notes_leases")
        rou = leases.parsed_data["rou_assets_by_category"]
        assert len(rou) == 1
        assert rou[0]["category"] == "All ROU assets"
        assert rou[0]["value_current"] == Decimal("380000000.0")


# ======================================================================
# 7. Edge cases
# ======================================================================


class TestEdgeCases:
    def test_no_tax_note_no_section(self, tmp_path: Path) -> None:
        """If RawExtraction has no tax note, the adapter doesn't emit
        a notes_taxes section — Module A will SKIP gracefully."""
        payload_path = tmp_path / "no_tax.yaml"
        payload_path.write_text(
            """
metadata:
  ticker: "X"
  company_name: "X"
  document_type: "annual_report"
  extraction_type: "numeric"
  reporting_currency: "USD"
  unit_scale: "units"
  fiscal_year: 2024
  extraction_date: "2025-01-01"
  fiscal_periods:
    - period: "FY2024"
      end_date: "2024-12-31"
      is_primary: true
income_statement:
  FY2024:
    revenue: "100"
    net_income: "10"
balance_sheet:
  FY2024:
    total_assets: "500"
    total_equity: "300"
""",
            encoding="utf-8",
        )
        raw = parse_raw_extraction(payload_path)
        result = adapt_raw_extraction(raw)
        assert not any(
            s.section_type == "notes_taxes" for s in result.sections
        )
        assert not any(
            s.section_type == "notes_leases" for s in result.sections
        )

    def test_empty_cash_flow_no_section(self, tmp_path: Path) -> None:
        payload_path = tmp_path / "no_cf.yaml"
        payload_path.write_text(
            """
metadata:
  ticker: "X"
  company_name: "X"
  document_type: "interim_report"
  extraction_type: "numeric"
  reporting_currency: "USD"
  unit_scale: "units"
  fiscal_year: 2024
  extraction_date: "2025-01-01"
  fiscal_periods:
    - period: "H1 2024"
      end_date: "2024-06-30"
      is_primary: true
      period_type: "H1"
income_statement:
  "H1 2024":
    revenue: "50"
    net_income: "5"
balance_sheet:
  "H1 2024":
    total_assets: "300"
    total_equity: "200"
""",
            encoding="utf-8",
        )
        raw = parse_raw_extraction(payload_path)
        result = adapt_raw_extraction(raw)
        assert not any(s.section_type == "cash_flow" for s in result.sections)


# ======================================================================
# 8. Classification mapping is a closed set
# ======================================================================


class TestClassificationMap:
    @pytest.mark.parametrize(
        "classification, expected_category",
        [
            ("operational", "non_deductible"),
            ("non_operational", "non_operating"),
            ("one_time", "prior_year_adjustment"),
            ("unknown", "other"),
        ],
    )
    def test_mapping(self, classification: str, expected_category: str) -> None:
        assert _TAX_CLASSIFICATION_TO_CATEGORY[classification] == expected_category

    def test_structured_section_is_frozen_dataclass(self) -> None:
        """StructuredSection is a frozen dataclass — Sprint 3 removes it
        entirely, but while it lives it stays immutable like the Phase 1
        type it replaces."""
        section = StructuredSection(
            section_type="income_statement",
            title="IS",
            content="",
        )
        with pytest.raises(Exception):  # noqa: B017
            section.section_type = "other"  # type: ignore[misc]
