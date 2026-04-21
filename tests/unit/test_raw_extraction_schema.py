"""Unit tests for :class:`RawExtraction` — the human/Claude.ai → system boundary."""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from portfolio_thesis_engine.schemas.common import Currency
from portfolio_thesis_engine.schemas.raw_extraction import (
    BalanceSheetPeriod,
    CashFlowPeriod,
    IncomeStatementPeriod,
    LeaseNote,
    Notes,
    ProvisionItem,
    RawExtraction,
    Segments,
    TaxNote,
    TaxReconciliationItem,
)


def _minimal_valid() -> dict:
    """Smallest payload that satisfies RawExtraction validation."""
    return {
        "ticker": "TEST",
        "company_name": "Test Co",
        "reporting_currency": "USD",
        "unit_scale": "millions",
        "extraction_date": "2025-01-15",
        "source": "Annual Report 2024",
        "fiscal_periods": [
            {"period": "FY2024", "end_date": "2024-12-31", "is_primary": True},
        ],
        "income_statement": {
            "FY2024": {
                "revenue": "100",
                "net_income": "10",
            },
        },
        "balance_sheet": {
            "FY2024": {
                "total_assets": "500",
                "total_equity": "300",
            },
        },
    }


# ======================================================================
# 1. Happy path + round-trip
# ======================================================================


class TestHappyPath:
    def test_minimal_valid_extraction(self) -> None:
        raw = RawExtraction.model_validate(_minimal_valid())
        assert raw.ticker == "TEST"
        assert raw.reporting_currency == Currency.USD
        assert raw.unit_scale == "millions"
        assert raw.primary_period.period == "FY2024"
        assert raw.primary_is.revenue == Decimal("100")
        assert raw.primary_bs.total_assets == Decimal("500")
        assert raw.primary_cf is None  # CF is optional
        assert raw.notes.taxes is None  # Defaults empty

    def test_yaml_round_trip(self) -> None:
        raw = RawExtraction.model_validate(_minimal_valid())
        dumped = raw.to_yaml()
        loaded = RawExtraction.from_yaml(dumped)
        assert loaded == raw

    def test_decimal_precision_preserved(self) -> None:
        payload = _minimal_valid()
        payload["income_statement"]["FY2024"]["revenue"] = "100.123456789"
        raw = RawExtraction.model_validate(payload)
        # Round-trip preserves precision — no float rounding.
        assert raw.primary_is.revenue == Decimal("100.123456789")
        loaded = RawExtraction.from_yaml(raw.to_yaml())
        assert loaded.primary_is.revenue == Decimal("100.123456789")

    def test_multi_period_ordering(self) -> None:
        payload = _minimal_valid()
        payload["fiscal_periods"] = [
            {"period": "H1 2025", "end_date": "2025-06-30", "is_primary": False},
            {"period": "FY2024", "end_date": "2024-12-31", "is_primary": True},
        ]
        payload["income_statement"]["H1 2025"] = {"revenue": "50"}
        payload["balance_sheet"]["H1 2025"] = {"total_assets": "260"}

        raw = RawExtraction.model_validate(payload)
        # Primary is the FY2024 period even though it's listed second
        assert raw.primary_period.period == "FY2024"


# ======================================================================
# 2. Required-field enforcement
# ======================================================================


class TestRequiredFields:
    @pytest.mark.parametrize(
        "missing",
        ["ticker", "company_name", "reporting_currency", "unit_scale",
         "extraction_date", "source", "fiscal_periods", "income_statement",
         "balance_sheet"],
    )
    def test_missing_required_field_raises(self, missing: str) -> None:
        payload = _minimal_valid()
        del payload[missing]
        with pytest.raises(ValidationError):
            RawExtraction.model_validate(payload)

    def test_invalid_unit_scale(self) -> None:
        payload = _minimal_valid()
        payload["unit_scale"] = "grams"
        with pytest.raises(ValidationError):
            RawExtraction.model_validate(payload)

    def test_bad_date_format(self) -> None:
        payload = _minimal_valid()
        payload["extraction_date"] = "15/04/2025"
        with pytest.raises(ValidationError):
            RawExtraction.model_validate(payload)

    def test_empty_ticker(self) -> None:
        payload = _minimal_valid()
        payload["ticker"] = ""
        with pytest.raises(ValidationError):
            RawExtraction.model_validate(payload)


# ======================================================================
# 3. Completeness validator (IS + BS for primary period)
# ======================================================================


class TestCompletenessValidator:
    def test_empty_fiscal_periods_rejected(self) -> None:
        payload = _minimal_valid()
        payload["fiscal_periods"] = []
        with pytest.raises(ValidationError, match="at least one entry"):
            RawExtraction.model_validate(payload)

    def test_missing_is_for_primary_rejected(self) -> None:
        payload = _minimal_valid()
        payload["income_statement"] = {}  # primary FY2024 not present
        with pytest.raises(ValidationError, match="income_statement"):
            RawExtraction.model_validate(payload)

    def test_missing_bs_for_primary_rejected(self) -> None:
        payload = _minimal_valid()
        payload["balance_sheet"] = {}
        with pytest.raises(ValidationError, match="balance_sheet"):
            RawExtraction.model_validate(payload)

    def test_two_primary_flags_rejected(self) -> None:
        payload = _minimal_valid()
        payload["fiscal_periods"] = [
            {"period": "FY2024", "end_date": "2024-12-31", "is_primary": True},
            {"period": "H1 2025", "end_date": "2025-06-30", "is_primary": True},
        ]
        payload["income_statement"]["H1 2025"] = {"revenue": "50"}
        payload["balance_sheet"]["H1 2025"] = {"total_assets": "260"}
        with pytest.raises(ValidationError, match="at most one"):
            RawExtraction.model_validate(payload)

    def test_no_primary_flag_defaults_to_first(self) -> None:
        """When no period has is_primary=true, the first entry is used."""
        payload = _minimal_valid()
        payload["fiscal_periods"] = [
            {"period": "FY2024", "end_date": "2024-12-31", "is_primary": False},
            {"period": "H1 2025", "end_date": "2025-06-30", "is_primary": False},
        ]
        payload["income_statement"]["H1 2025"] = {"revenue": "50"}
        payload["balance_sheet"]["H1 2025"] = {"total_assets": "260"}
        raw = RawExtraction.model_validate(payload)
        assert raw.primary_period.period == "FY2024"

    def test_cf_optional_when_missing(self) -> None:
        payload = _minimal_valid()
        # cash_flow intentionally not set
        raw = RawExtraction.model_validate(payload)
        assert raw.cash_flow == {}
        assert raw.primary_cf is None


# ======================================================================
# 4. Statement schemas — lenient Decimal | None
# ======================================================================


class TestStatements:
    def test_is_defaults_all_none(self) -> None:
        is_empty = IncomeStatementPeriod.model_validate({})
        assert is_empty.revenue is None
        assert is_empty.net_income is None
        assert is_empty.extensions == {}

    def test_bs_defaults_all_none(self) -> None:
        bs_empty = BalanceSheetPeriod.model_validate({})
        assert bs_empty.total_assets is None
        assert bs_empty.total_equity is None
        assert bs_empty.rou_assets is None

    def test_cf_defaults_all_none(self) -> None:
        cf_empty = CashFlowPeriod.model_validate({})
        assert cf_empty.operating_cash_flow is None
        assert cf_empty.net_change_in_cash is None

    def test_extensions_accept_arbitrary_decimal_keys(self) -> None:
        is_ext = IncomeStatementPeriod.model_validate({
            "revenue": "100",
            "extensions": {"share_of_associates_profit": "5.5"},
        })
        assert is_ext.extensions["share_of_associates_profit"] == Decimal("5.5")

    def test_extra_top_level_field_forbidden(self) -> None:
        """``extra="forbid"`` catches typos — unknown IS fields raise."""
        with pytest.raises(ValidationError):
            IncomeStatementPeriod.model_validate({"revnue": "100"})  # typo

    def test_non_numeric_value_rejected(self) -> None:
        with pytest.raises(ValidationError):
            IncomeStatementPeriod.model_validate({"revenue": "not-a-number"})


# ======================================================================
# 5. Notes
# ======================================================================


class TestTaxNote:
    def test_empty_tax_note(self) -> None:
        tn = TaxNote()
        assert tn.reconciling_items == []
        assert tn.effective_tax_rate_percent is None

    def test_reconciling_items(self) -> None:
        tn = TaxNote.model_validate({
            "effective_tax_rate_percent": "21.9",
            "statutory_rate_percent": "16.5",
            "reconciling_items": [
                {"description": "Prior year", "amount": "0.8", "classification": "one_time"},
                {"description": "Non-deductible", "amount": "1.5"},  # defaults unknown
            ],
        })
        assert tn.effective_tax_rate_percent == Decimal("21.9")
        assert len(tn.reconciling_items) == 2
        assert tn.reconciling_items[0].classification == "one_time"
        assert tn.reconciling_items[1].classification == "unknown"

    def test_reconciling_item_description_required(self) -> None:
        with pytest.raises(ValidationError):
            TaxReconciliationItem.model_validate({"amount": "1.0"})

    def test_reconciling_item_bad_classification_rejected(self) -> None:
        with pytest.raises(ValidationError):
            TaxReconciliationItem.model_validate({
                "description": "X",
                "amount": "1.0",
                "classification": "bogus",
            })


class TestLeaseNote:
    def test_all_optional(self) -> None:
        ln = LeaseNote()
        assert ln.rou_assets_additions is None
        assert ln.lease_interest_expense is None

    def test_populated(self) -> None:
        ln = LeaseNote.model_validate({
            "rou_assets_opening": "360",
            "rou_assets_closing": "380",
            "rou_assets_additions": "55",
            "lease_interest_expense": "15",
            "lease_principal_payments": "40",
        })
        assert ln.rou_assets_additions == Decimal("55")


class TestProvisions:
    def test_classification_enum(self) -> None:
        item = ProvisionItem.model_validate({
            "description": "Warranty",
            "amount": "8",
            "classification": "operating",
        })
        assert item.classification == "operating"

    def test_bad_classification_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ProvisionItem.model_validate({
                "description": "X",
                "amount": "1",
                "classification": "invalid",
            })

    def test_classification_default_other(self) -> None:
        item = ProvisionItem.model_validate({"description": "Misc", "amount": "1"})
        assert item.classification == "other"


class TestNotes:
    def test_empty_notes_default(self) -> None:
        notes = Notes()
        assert notes.taxes is None
        assert notes.leases is None
        assert notes.provisions == []

    def test_extensions_accept_any(self) -> None:
        notes = Notes.model_validate({
            "extensions": {
                "goodwill_impairment": {"amount": "12", "rationale": "China CGU"},
            },
        })
        assert "goodwill_impairment" in notes.extensions


# ======================================================================
# 6. Segments + HistoricalData
# ======================================================================


class TestSegments:
    def test_segments_by_geography(self) -> None:
        seg = Segments.model_validate({
            "by_geography": {
                "FY2024": {"Greater China": "420", "Europe": "160"},
            },
        })
        assert seg.by_geography is not None
        assert seg.by_geography["FY2024"]["Greater China"] == Decimal("420")

    def test_segments_all_dimensions_optional(self) -> None:
        seg = Segments()
        assert seg.by_geography is None
        assert seg.by_product is None
        assert seg.by_business_line is None


class TestHistorical:
    def test_historical_defaults_empty(self) -> None:
        payload = _minimal_valid()
        raw = RawExtraction.model_validate(payload)
        assert raw.historical is None

    def test_historical_series(self) -> None:
        payload = _minimal_valid()
        payload["historical"] = {
            "revenue_by_year": {"2022": "400", "2023": "500", "2024": "580"},
            "extensions": {"rnd_by_year": {"2022": "20", "2023": "25"}},
        }
        raw = RawExtraction.model_validate(payload)
        assert raw.historical is not None
        assert raw.historical.revenue_by_year["2024"] == Decimal("580")
        assert raw.historical.extensions["rnd_by_year"]["2022"] == Decimal("20")


# ======================================================================
# 7. Convenience accessors
# ======================================================================


class TestConvenience:
    def test_primary_period_with_flag(self) -> None:
        raw = RawExtraction.model_validate(_minimal_valid())
        assert raw.primary_period.period == "FY2024"
        assert raw.primary_period.is_primary is True

    def test_primary_is_bs_cf_accessors(self) -> None:
        payload = _minimal_valid()
        payload["cash_flow"] = {"FY2024": {"operating_cash_flow": "20"}}
        raw = RawExtraction.model_validate(payload)
        assert raw.primary_is.revenue == Decimal("100")
        assert raw.primary_bs.total_assets == Decimal("500")
        assert raw.primary_cf is not None
        assert raw.primary_cf.operating_cash_flow == Decimal("20")
