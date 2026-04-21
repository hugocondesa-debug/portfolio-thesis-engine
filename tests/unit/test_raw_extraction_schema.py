"""Unit tests for :class:`RawExtraction` — FULL SCOPE schema."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from portfolio_thesis_engine.schemas.common import Currency
from portfolio_thesis_engine.schemas.raw_extraction import (
    AcquisitionItem,
    AcquisitionsNote,
    BalanceSheetPeriod,
    CashFlowPeriod,
    CommitmentsNote,
    DiscontinuedOpsNote,
    DocumentMetadata,
    DocumentType,
    EmployeeBenefitsNote,
    ExtractionType,
    FiscalPeriodData,
    GoodwillNote,
    HistoricalData,
    IncomeStatementPeriod,
    IntangiblesNote,
    InventoryNote,
    LeaseNote,
    NarrativeContent,
    NotesContainer,
    OperationalKPIs,
    PensionNote,
    PPENote,
    ProvisionItem,
    RawExtraction,
    RelatedPartyItem,
    SBCNote,
    Segments,
    SubsequentEventItem,
    TaxNote,
    TaxReconciliationItem,
    UnknownSectionItem,
)


def _numeric_minimal() -> dict:
    """Smallest numeric extraction that validates."""
    return {
        "metadata": {
            "ticker": "TEST",
            "company_name": "Test Co",
            "document_type": "annual_report",
            "extraction_type": "numeric",
            "reporting_currency": "USD",
            "unit_scale": "units",
            "fiscal_year": 2024,
            "extraction_date": "2025-01-15",
            "fiscal_periods": [
                {
                    "period": "FY2024",
                    "end_date": "2024-12-31",
                    "is_primary": True,
                    "period_type": "FY",
                }
            ],
        },
        "income_statement": {
            "FY2024": {"revenue": "100", "net_income": "10"},
        },
        "balance_sheet": {
            "FY2024": {"total_assets": "500", "total_equity": "300"},
        },
    }


def _narrative_minimal() -> dict:
    """Smallest narrative extraction that validates."""
    return {
        "metadata": {
            "ticker": "TEST",
            "company_name": "Test Co",
            "document_type": "earnings_call",
            "extraction_type": "narrative",
            "reporting_currency": "USD",
            "unit_scale": "units",
            "fiscal_year": 2024,
            "extraction_date": "2025-01-15",
            "fiscal_periods": [
                {"period": "Q4 2024", "end_date": "2024-12-31", "period_type": "Q4"}
            ],
        },
        "narrative": {
            "key_themes": ["Margin expansion", "Geographic diversification"],
        },
    }


# ======================================================================
# 1. DocumentType + ExtractionType enums
# ======================================================================


class TestEnums:
    def test_document_type_covers_all_four_buckets(self) -> None:
        values = {dt.value for dt in DocumentType}
        # Sanity: at least one from each bucket
        assert "annual_report" in values  # numeric
        assert "earnings_call" in values  # narrative
        assert "sec_comment_letter" in values  # regulatory
        assert "pillar_3" in values  # industry-specific (banks)
        assert "ni_43_101" in values  # industry-specific (mining)
        assert "other" in values  # catchall

    def test_document_type_has_at_least_40_values(self) -> None:
        assert len(list(DocumentType)) >= 40

    def test_extraction_type_two_values(self) -> None:
        assert {et.value for et in ExtractionType} == {"numeric", "narrative"}


# ======================================================================
# 2. Happy path + round-trip
# ======================================================================


class TestNumericHappyPath:
    def test_minimal_parses(self) -> None:
        raw = RawExtraction.model_validate(_numeric_minimal())
        assert raw.metadata.ticker == "TEST"
        assert raw.metadata.document_type == DocumentType.ANNUAL_REPORT
        assert raw.metadata.extraction_type == ExtractionType.NUMERIC
        assert raw.metadata.reporting_currency == Currency.USD
        assert raw.primary_period.period == "FY2024"
        assert raw.primary_is is not None
        assert raw.primary_is.revenue == Decimal("100")

    def test_yaml_round_trip(self) -> None:
        raw = RawExtraction.model_validate(_numeric_minimal())
        loaded = RawExtraction.from_yaml(raw.to_yaml())
        assert loaded == raw

    def test_decimal_precision_preserved(self) -> None:
        payload = _numeric_minimal()
        payload["income_statement"]["FY2024"]["revenue"] = "100.123456789"
        raw = RawExtraction.model_validate(payload)
        assert raw.primary_is is not None
        assert raw.primary_is.revenue == Decimal("100.123456789")
        loaded = RawExtraction.from_yaml(raw.to_yaml())
        assert loaded.primary_is is not None
        assert loaded.primary_is.revenue == Decimal("100.123456789")


class TestNarrativeHappyPath:
    def test_narrative_minimal_parses(self) -> None:
        raw = RawExtraction.model_validate(_narrative_minimal())
        assert raw.metadata.extraction_type == ExtractionType.NARRATIVE
        assert raw.narrative is not None
        assert "Margin expansion" in raw.narrative.key_themes

    def test_narrative_round_trip(self) -> None:
        raw = RawExtraction.model_validate(_narrative_minimal())
        loaded = RawExtraction.from_yaml(raw.to_yaml())
        assert loaded == raw


# ======================================================================
# 3. Completeness validator (@model_validator)
# ======================================================================


class TestCompletenessValidator:
    def test_numeric_missing_is_rejected(self) -> None:
        payload = _numeric_minimal()
        payload["income_statement"] = {}
        with pytest.raises(ValidationError, match="income_statement"):
            RawExtraction.model_validate(payload)

    def test_numeric_missing_bs_rejected(self) -> None:
        payload = _numeric_minimal()
        payload["balance_sheet"] = {}
        with pytest.raises(ValidationError, match="balance_sheet"):
            RawExtraction.model_validate(payload)

    def test_empty_fiscal_periods_rejected(self) -> None:
        payload = _numeric_minimal()
        payload["metadata"]["fiscal_periods"] = []
        with pytest.raises(ValidationError, match="at least one entry"):
            RawExtraction.model_validate(payload)

    def test_two_primaries_rejected(self) -> None:
        payload = _numeric_minimal()
        payload["metadata"]["fiscal_periods"] = [
            {"period": "FY2024", "end_date": "2024-12-31", "is_primary": True},
            {"period": "H1 2025", "end_date": "2025-06-30", "is_primary": True},
        ]
        payload["income_statement"]["H1 2025"] = {"revenue": "50"}
        payload["balance_sheet"]["H1 2025"] = {"total_assets": "260"}
        with pytest.raises(ValidationError, match="at most one"):
            RawExtraction.model_validate(payload)

    def test_narrative_without_content_rejected(self) -> None:
        payload = _narrative_minimal()
        payload["narrative"] = {}  # empty narrative → all lists empty
        with pytest.raises(ValidationError, match="narrative"):
            RawExtraction.model_validate(payload)

    def test_narrative_missing_narrative_block_rejected(self) -> None:
        payload = _narrative_minimal()
        del payload["narrative"]
        with pytest.raises(ValidationError, match="narrative"):
            RawExtraction.model_validate(payload)

    def test_narrative_can_omit_statements(self) -> None:
        """Narrative extractions don't need IS/BS."""
        raw = RawExtraction.model_validate(_narrative_minimal())
        assert raw.income_statement == {}
        assert raw.balance_sheet == {}

    def test_no_primary_flag_first_period_used(self) -> None:
        payload = _numeric_minimal()
        payload["metadata"]["fiscal_periods"] = [
            {"period": "FY2024", "end_date": "2024-12-31", "is_primary": False},
            {"period": "H1 2025", "end_date": "2025-06-30", "is_primary": False},
        ]
        payload["income_statement"]["H1 2025"] = {"revenue": "50"}
        payload["balance_sheet"]["H1 2025"] = {"total_assets": "260"}
        raw = RawExtraction.model_validate(payload)
        assert raw.primary_period.period == "FY2024"


# ======================================================================
# 4. Required-field enforcement on metadata
# ======================================================================


class TestMetadataRequired:
    @pytest.mark.parametrize(
        "missing",
        [
            "ticker",
            "company_name",
            "document_type",
            "extraction_type",
            "reporting_currency",
            "unit_scale",
            "fiscal_year",
            "extraction_date",
            "fiscal_periods",
        ],
    )
    def test_missing_required_rejected(self, missing: str) -> None:
        payload = _numeric_minimal()
        del payload["metadata"][missing]
        with pytest.raises(ValidationError):
            RawExtraction.model_validate(payload)

    def test_invalid_unit_scale(self) -> None:
        payload = _numeric_minimal()
        payload["metadata"]["unit_scale"] = "grams"
        with pytest.raises(ValidationError):
            RawExtraction.model_validate(payload)

    def test_invalid_document_type(self) -> None:
        payload = _numeric_minimal()
        payload["metadata"]["document_type"] = "bogus"
        with pytest.raises(ValidationError):
            RawExtraction.model_validate(payload)

    def test_bad_date_format(self) -> None:
        payload = _numeric_minimal()
        payload["metadata"]["extraction_date"] = "15/04/2025"
        with pytest.raises(ValidationError):
            RawExtraction.model_validate(payload)

    def test_fiscal_year_range(self) -> None:
        payload = _numeric_minimal()
        payload["metadata"]["fiscal_year"] = 1800
        with pytest.raises(ValidationError):
            RawExtraction.model_validate(payload)


# ======================================================================
# 5. Statement schemas
# ======================================================================


class TestIncomeStatementPeriod:
    def test_all_fields_optional_default_none(self) -> None:
        is_empty = IncomeStatementPeriod()
        assert is_empty.revenue is None
        assert is_empty.operating_income is None
        assert is_empty.eps_basic is None
        assert is_empty.extensions == {}

    def test_eps_and_shares_fields(self) -> None:
        is_data = IncomeStatementPeriod.model_validate({
            "revenue": "100",
            "eps_basic": "0.50",
            "eps_diluted": "0.48",
            "shares_basic_weighted_avg": "200",
            "shares_diluted_weighted_avg": "208.3",
        })
        assert is_data.eps_basic == Decimal("0.50")
        assert is_data.shares_diluted_weighted_avg == Decimal("208.3")

    def test_extensions_extra(self) -> None:
        is_ext = IncomeStatementPeriod.model_validate({
            "revenue": "100",
            "extensions": {"share_of_associates_profit": "5"},
        })
        assert is_ext.extensions["share_of_associates_profit"] == Decimal("5")

    def test_extra_top_level_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            IncomeStatementPeriod.model_validate({"revnue": "100"})

    def test_discontinued_ops_lines(self) -> None:
        is_data = IncomeStatementPeriod.model_validate({
            "net_income_from_continuing": "100",
            "net_income_from_discontinued": "-10",
            "net_income": "90",
        })
        assert is_data.net_income_from_discontinued == Decimal("-10")


class TestBalanceSheetPeriod:
    def test_all_optional(self) -> None:
        bs = BalanceSheetPeriod()
        assert bs.total_assets is None
        assert bs.treasury_shares is None

    def test_new_fields(self) -> None:
        bs = BalanceSheetPeriod.model_validate({
            "ppe_gross": "1500",
            "accumulated_depreciation": "-600",
            "ppe_net": "900",
            "share_capital": "100",
            "share_premium": "200",
            "treasury_shares": "-50",
        })
        assert bs.ppe_gross == Decimal("1500")
        assert bs.treasury_shares == Decimal("-50")


class TestCashFlowPeriod:
    def test_all_optional(self) -> None:
        cf = CashFlowPeriod()
        assert cf.operating_cash_flow is None

    def test_detailed_fields(self) -> None:
        cf = CashFlowPeriod.model_validate({
            "net_income_cf": "100",
            "depreciation_amortization_cf": "50",
            "working_capital_changes": "-20",
            "operating_cash_flow": "130",
            "share_repurchases": "-25",
            "share_issuance": "10",
        })
        assert cf.working_capital_changes == Decimal("-20")
        assert cf.share_repurchases == Decimal("-25")


# ======================================================================
# 6. Notes — every type
# ======================================================================


class TestTaxNote:
    def test_reconciling_items(self) -> None:
        tn = TaxNote.model_validate({
            "effective_tax_rate_percent": "21.9",
            "statutory_rate_percent": "16.5",
            "reconciling_items": [
                {"description": "X", "amount": "1.5", "classification": "operational"},
                {"description": "Y", "amount": "-0.5"},  # default unknown
            ],
        })
        assert tn.effective_tax_rate_percent == Decimal("21.9")
        assert len(tn.reconciling_items) == 2
        assert tn.reconciling_items[1].classification == "unknown"

    def test_bad_classification_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaxReconciliationItem.model_validate({
                "description": "X",
                "amount": "1.0",
                "classification": "bogus",
            })


class TestLeaseNote:
    def test_new_fields(self) -> None:
        ln = LeaseNote.model_validate({
            "rou_assets_additions": "55",
            "lease_interest_expense": "15",
            "short_term_lease_expense": "3",
            "variable_lease_payments": "2",
        })
        assert ln.short_term_lease_expense == Decimal("3")
        assert ln.variable_lease_payments == Decimal("2")


class TestProvisionItem:
    def test_default_classification(self) -> None:
        p = ProvisionItem.model_validate({"description": "Misc", "amount": "1"})
        assert p.classification == "other"

    def test_restructuring_classification(self) -> None:
        p = ProvisionItem.model_validate({
            "description": "Plant closure",
            "amount": "50",
            "classification": "restructuring",
        })
        assert p.classification == "restructuring"


class TestGoodwillNote:
    def test_movement_with_by_cgu(self) -> None:
        gn = GoodwillNote.model_validate({
            "opening": "620",
            "additions": "0",
            "impairment": "-20",
            "closing": "600",
            "by_cgu": {"China": "420", "Germany": "180"},
        })
        assert gn.by_cgu["China"] == Decimal("420")
        assert gn.impairment == Decimal("-20")


class TestIntangiblesNote:
    def test_by_type_split(self) -> None:
        note = IntangiblesNote.model_validate({
            "opening": "400",
            "closing": "420",
            "by_type": {"Software": "150", "Brand": "70"},
        })
        assert note.by_type["Software"] == Decimal("150")


class TestPPENote:
    def test_movement_table(self) -> None:
        p = PPENote.model_validate({
            "opening_gross": "1500",
            "additions": "75",
            "disposals": "-10",
            "closing_gross": "1565",
            "accumulated_depreciation": "-620",
        })
        assert p.opening_gross == Decimal("1500")


class TestInventoryNote:
    def test_split_by_stage(self) -> None:
        inv = InventoryNote.model_validate({
            "raw_materials": "15",
            "wip": "10",
            "finished_goods": "55",
            "provisions": "-5",
            "total": "75",
        })
        assert inv.wip == Decimal("10")


class TestEmployeeBenefitsNote:
    def test_headcount_comp_mix(self) -> None:
        eb = EmployeeBenefitsNote.model_validate({
            "headcount": "850",
            "avg_compensation": "0.45",
            "total_compensation": "382.5",
            "pension_expense": "8",
            "sbc_expense": "6.5",
        })
        assert eb.headcount == Decimal("850")


class TestSBCNote:
    def test_grants_and_outstanding(self) -> None:
        sbc = SBCNote.model_validate({
            "stock_options_granted": "0.5",
            "stock_options_outstanding": "2.8",
            "rsus_granted": "1.0",
            "rsus_outstanding": "3.2",
            "expense": "6.5",
        })
        assert sbc.rsus_outstanding == Decimal("3.2")


class TestPensionNote:
    def test_dbo_movement(self) -> None:
        p = PensionNote.model_validate({
            "dbo_opening": "100",
            "dbo_closing": "110",
            "plan_assets_opening": "80",
            "plan_assets_closing": "85",
            "service_cost": "5",
            "interest_cost": "3",
            "actuarial_gains_losses": "-2",
        })
        assert p.service_cost == Decimal("5")


class TestCommitmentsNote:
    def test_capital_commitments(self) -> None:
        c = CommitmentsNote.model_validate({
            "capital_commitments": "42",
            "guarantees_provided": "10",
        })
        assert c.capital_commitments == Decimal("42")


class TestAcquisitions:
    def test_single_item(self) -> None:
        acq = AcquisitionsNote.model_validate({
            "items": [
                {
                    "name": "DE Subsidiary",
                    "date": "2023-08-15",
                    "consideration": "120",
                    "fair_value": "100",
                    "goodwill_recognized": "20",
                }
            ]
        })
        assert len(acq.items) == 1
        assert acq.items[0].name == "DE Subsidiary"

    def test_acquisition_item_required_fields(self) -> None:
        with pytest.raises(ValidationError):
            AcquisitionItem.model_validate({"name": "X", "date": "2024-01-01"})


class TestDiscontinuedOps:
    def test_segment_summary(self) -> None:
        d = DiscontinuedOpsNote.model_validate({
            "revenue": "50",
            "operating_income": "-10",
            "net_income": "-8",
        })
        assert d.revenue == Decimal("50")


class TestSubsequentEvents:
    def test_impact_enum(self) -> None:
        ev = SubsequentEventItem.model_validate({
            "description": "Acquisition close",
            "date": "2025-03-14",
            "impact": "material_positive",
        })
        assert ev.impact == "material_positive"

    def test_default_pending(self) -> None:
        ev = SubsequentEventItem.model_validate({"description": "TBC"})
        assert ev.impact == "pending"


class TestRelatedParty:
    def test_basic(self) -> None:
        rp = RelatedPartyItem.model_validate({
            "counterparty": "Director X",
            "nature": "Consulting",
            "amount": "0.5",
        })
        assert rp.amount == Decimal("0.5")


class TestUnknownSectionItem:
    def test_default_flagged(self) -> None:
        u = UnknownSectionItem.model_validate({
            "title": "Strange disclosures",
            "content_summary": "Weird text we don't know how to map.",
        })
        assert u.reviewer_flag is True


class TestNotesContainer:
    def test_defaults_empty(self) -> None:
        notes = NotesContainer()
        assert notes.taxes is None
        assert notes.provisions == []
        assert notes.unknown_sections == []
        assert notes.extensions == {}

    def test_unknown_sections_populate(self) -> None:
        notes = NotesContainer.model_validate({
            "unknown_sections": [
                {"title": "Mystery Note 42", "content_summary": "???"}
            ]
        })
        assert len(notes.unknown_sections) == 1
        assert notes.unknown_sections[0].reviewer_flag is True


# ======================================================================
# 7. Segments + historical + operational KPIs + narrative
# ======================================================================


class TestSegments:
    def test_by_geography_structure(self) -> None:
        seg = Segments.model_validate({
            "by_geography": {
                "FY2024": {
                    "Greater China": {"revenue": "420", "operating_income": "85"},
                },
            },
        })
        assert seg.by_geography is not None
        geo = seg.by_geography["FY2024"]["Greater China"]
        assert geo["revenue"] == Decimal("420")


class TestHistoricalData:
    def test_multiple_series(self) -> None:
        h = HistoricalData.model_validate({
            "revenue_by_year": {"2022": "400", "2024": "580"},
            "free_cash_flow_by_year": {"2024": "60"},
            "dividends_by_year": {"2024": "25"},
        })
        assert h.free_cash_flow_by_year["2024"] == Decimal("60")


class TestOperationalKPIs:
    def test_mixed_decimal_string_values(self) -> None:
        """In Pydantic's ``Decimal | str`` union, quoted inputs stay
        strings; unquoted numerics become Decimals. The schema tolerates
        both — KPIs that look numeric but carry qualitative content
        (e.g. an NPS score of ``"42 (top decile)"``) survive."""
        kpi = OperationalKPIs.model_validate({
            "metrics": {
                "clinics": {"FY2024": 38, "H1 2025": 40},  # unquoted → Decimal
                "sub_region_strategy": {"FY2024": "China expansion phase 2"},
            }
        })
        assert kpi.metrics["clinics"]["FY2024"] == Decimal("38")
        assert kpi.metrics["sub_region_strategy"]["FY2024"] == "China expansion phase 2"

    def test_quoted_numeric_stays_string(self) -> None:
        """Quoted ``"38"`` stays a string when the field accepts
        ``Decimal | str``. Extractors who want a Decimal value should
        use unquoted YAML."""
        kpi = OperationalKPIs.model_validate({
            "metrics": {"clinics": {"FY2024": "38"}}
        })
        assert kpi.metrics["clinics"]["FY2024"] == "38"


class TestNarrativeContent:
    def test_empty_defaults(self) -> None:
        n = NarrativeContent()
        assert n.key_themes == []
        assert n.q_and_a_highlights == []

    def test_guidance_change_item(self) -> None:
        n = NarrativeContent.model_validate({
            "guidance_changes": [
                {"metric": "Revenue", "old": "450-470", "new": "480-500", "direction": "up"},
            ],
            "key_themes": ["Margin expansion"],
        })
        assert n.guidance_changes[0].direction == "up"


# ======================================================================
# 8. Convenience accessors
# ======================================================================


class TestConvenience:
    def test_primary_period_with_flag(self) -> None:
        raw = RawExtraction.model_validate(_numeric_minimal())
        assert raw.primary_period.period == "FY2024"

    def test_primary_is_bs_cf(self) -> None:
        payload = _numeric_minimal()
        payload["cash_flow"] = {"FY2024": {"operating_cash_flow": "20"}}
        raw = RawExtraction.model_validate(payload)
        assert raw.primary_is is not None and raw.primary_is.revenue == Decimal("100")
        assert raw.primary_bs is not None and raw.primary_bs.total_assets == Decimal("500")
        assert raw.primary_cf is not None and raw.primary_cf.operating_cash_flow == Decimal("20")


# ======================================================================
# 9. DocumentMetadata + FiscalPeriodData
# ======================================================================


class TestFiscalPeriodData:
    @pytest.mark.parametrize(
        "period_type",
        ["FY", "H1", "H2", "Q1", "Q2", "Q3", "Q4", "YTD", "LTM"],
    )
    def test_valid_period_types(self, period_type: str) -> None:
        fp = FiscalPeriodData.model_validate({
            "period": "Label",
            "end_date": "2024-12-31",
            "period_type": period_type,
        })
        assert fp.period_type == period_type

    def test_default_period_type_fy(self) -> None:
        fp = FiscalPeriodData.model_validate({
            "period": "FY2024",
            "end_date": "2024-12-31",
        })
        assert fp.period_type == "FY"


class TestDocumentMetadata:
    def test_source_sha256_optional(self) -> None:
        meta = DocumentMetadata.model_validate({
            "ticker": "X",
            "company_name": "Y",
            "document_type": "annual_report",
            "extraction_type": "numeric",
            "reporting_currency": "USD",
            "unit_scale": "millions",
            "fiscal_year": 2024,
            "extraction_date": "2025-01-01",
            "fiscal_periods": [{"period": "FY2024", "end_date": "2024-12-31"}],
        })
        assert meta.source_file_sha256 is None
        assert meta.extraction_version == 1
