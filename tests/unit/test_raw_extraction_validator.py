"""Unit tests for :class:`ExtractionValidator` — three validation tiers."""

from __future__ import annotations

from pathlib import Path

import pytest

from portfolio_thesis_engine.ingestion.raw_extraction_parser import parse_raw_extraction
from portfolio_thesis_engine.ingestion.raw_extraction_validator import (
    REQUIRED_NOTES_BY_PROFILE,
    ExtractionValidator,
    ValidationReport,
    ValidationResult,
    ValidationStatus,
)
from portfolio_thesis_engine.schemas.common import Profile
from portfolio_thesis_engine.schemas.raw_extraction import RawExtraction

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "euroeyes" / "raw_extraction.yaml"


def _valid_numeric(
    *,
    is_operating_income: str = "100",
    is_revenue: str = "500",
    is_cogs: str = "-300",
    is_opex: str = "-100",
    bs_assets: str = "3000",
    bs_liab: str = "1000",
    bs_equity: str = "2000",
) -> dict:
    """Build a payload where IS + BS identities hold by construction."""
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
                {"period": "FY2024", "end_date": "2024-12-31", "is_primary": True},
            ],
        },
        "income_statement": {
            "FY2024": {
                "revenue": is_revenue,
                "cost_of_sales": is_cogs,
                "selling_marketing": is_opex,
                "operating_income": is_operating_income,
                "net_income": "70",
                "shares_basic_weighted_avg": "200",
                "shares_diluted_weighted_avg": "205",
            },
        },
        "balance_sheet": {
            "FY2024": {
                "total_assets": bs_assets,
                "total_liabilities": bs_liab,
                "total_equity": bs_equity,
            },
        },
    }


# ======================================================================
# 1. Strict validator
# ======================================================================


class TestValidateStrict:
    def test_clean_numeric_passes(self) -> None:
        raw = RawExtraction.model_validate(_valid_numeric())
        report = ExtractionValidator().validate_strict(raw)
        assert report.overall_status == "OK"
        assert len(report.fails) == 0

    def test_is_arithmetic_failure(self) -> None:
        # 500 - 300 - 100 = 100, but set operating_income to 200 → 100% off
        raw = RawExtraction.model_validate(_valid_numeric(is_operating_income="200"))
        report = ExtractionValidator().validate_strict(raw)
        assert report.overall_status == "FAIL"
        assert any(r.check_id == "S.IS" and r.status == "FAIL" for r in report.results)

    def test_bs_identity_failure(self) -> None:
        # Assets 3000, Liab+Equity = 1000 + 1500 = 2500 → 17% off
        raw = RawExtraction.model_validate(
            _valid_numeric(bs_assets="3000", bs_liab="1000", bs_equity="1500")
        )
        report = ExtractionValidator().validate_strict(raw)
        assert report.overall_status == "FAIL"
        assert any(r.check_id == "S.BS" and r.status == "FAIL" for r in report.results)

    def test_metadata_check_always_ok(self) -> None:
        """If the model validates, metadata check is OK."""
        raw = RawExtraction.model_validate(_valid_numeric())
        report = ExtractionValidator().validate_strict(raw)
        meta_result = next(r for r in report.results if r.check_id == "S.M1")
        assert meta_result.status == "OK"
        assert "ticker=TEST" in meta_result.message

    def test_is_skip_when_missing_revenue_or_op_income(self) -> None:
        payload = _valid_numeric()
        payload["income_statement"]["FY2024"]["revenue"] = None
        raw = RawExtraction.model_validate(payload)
        report = ExtractionValidator().validate_strict(raw)
        is_result = next(r for r in report.results if r.check_id == "S.IS")
        assert is_result.status == "SKIP"

    def test_bs_skip_when_subtotals_missing(self) -> None:
        payload = _valid_numeric()
        payload["balance_sheet"]["FY2024"]["total_liabilities"] = None
        raw = RawExtraction.model_validate(payload)
        report = ExtractionValidator().validate_strict(raw)
        bs_result = next(r for r in report.results if r.check_id == "S.BS")
        assert bs_result.status == "SKIP"


# ======================================================================
# 2. Warn validator
# ======================================================================


class TestValidateWarn:
    def test_euroeyes_fixture_produces_warns(self) -> None:
        """The fixture has FY2024 + H1 2025 (chronologically H1 comes
        AFTER FY2024). Validator uses H1 as "other period" which flips
        the sign of some checks — expected WARNs."""
        raw = parse_raw_extraction(_FIXTURE)
        report = ExtractionValidator().validate_warn(raw)
        # At least one check should pass (CF identity).
        assert any(r.check_id == "W.CF" and r.status == "OK" for r in report.results)

    def test_cf_identity_ok_when_balanced(self) -> None:
        payload = _valid_numeric()
        payload["cash_flow"] = {
            "FY2024": {
                "operating_cash_flow": "100",
                "investing_cash_flow": "-50",
                "financing_cash_flow": "-30",
                "fx_effect": "0",
                "net_change_in_cash": "20",
            },
        }
        raw = RawExtraction.model_validate(payload)
        report = ExtractionValidator().validate_warn(raw)
        cf_result = next(r for r in report.results if r.check_id == "W.CF")
        assert cf_result.status == "OK"

    def test_cf_identity_warn_when_off(self) -> None:
        payload = _valid_numeric()
        payload["cash_flow"] = {
            "FY2024": {
                "operating_cash_flow": "100",
                "investing_cash_flow": "-50",
                "financing_cash_flow": "-30",
                "fx_effect": "0",
                "net_change_in_cash": "50",  # should be 20
            },
        }
        raw = RawExtraction.model_validate(payload)
        report = ExtractionValidator().validate_warn(raw)
        cf_result = next(r for r in report.results if r.check_id == "W.CF")
        assert cf_result.status == "WARN"

    def test_shares_consistency_warn_when_basic_exceeds_diluted(self) -> None:
        payload = _valid_numeric()
        payload["income_statement"]["FY2024"]["shares_basic_weighted_avg"] = "250"
        payload["income_statement"]["FY2024"]["shares_diluted_weighted_avg"] = "200"
        raw = RawExtraction.model_validate(payload)
        report = ExtractionValidator().validate_warn(raw)
        shares = next(r for r in report.results if r.check_id == "W.SHARES")
        assert shares.status == "WARN"

    def test_shares_ok_when_basic_leq_diluted(self) -> None:
        payload = _valid_numeric()
        raw = RawExtraction.model_validate(payload)
        report = ExtractionValidator().validate_warn(raw)
        shares = next(r for r in report.results if r.check_id == "W.SHARES")
        assert shares.status == "OK"

    def test_yoy_warn_on_3x_revenue(self) -> None:
        payload = _valid_numeric(is_revenue="1000")
        payload["metadata"]["fiscal_periods"].append(
            {"period": "FY2023", "end_date": "2023-12-31", "is_primary": False}
        )
        payload["income_statement"]["FY2023"] = {"revenue": "200"}
        payload["balance_sheet"]["FY2023"] = {
            "total_assets": "1000",
            "total_liabilities": "400",
            "total_equity": "600",
        }
        raw = RawExtraction.model_validate(payload)
        report = ExtractionValidator().validate_warn(raw)
        yoy = next(r for r in report.results if r.check_id == "W.YOY")
        assert yoy.status == "WARN"

    def test_lease_movement_check(self) -> None:
        """Closing = opening + additions − principal."""
        payload = _valid_numeric()
        payload["notes"] = {
            "leases": {
                "lease_liabilities_opening": "100",
                "lease_liabilities_closing": "120",
                "rou_assets_additions": "40",
                "lease_principal_payments": "20",
                # 100 + 40 - 20 = 120 ✓
            },
        }
        raw = RawExtraction.model_validate(payload)
        report = ExtractionValidator().validate_warn(raw)
        lease = next(r for r in report.results if r.check_id == "W.LEASE")
        assert lease.status == "OK"


# ======================================================================
# 3. Completeness validator
# ======================================================================


class TestValidateCompleteness:
    def test_p1_all_notes_present_ok(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        report = ExtractionValidator().validate_completeness(raw, Profile.P1_INDUSTRIAL)
        # Fixture has all 10 required P1 notes + some recommended.
        fail_checks = [r for r in report.results if r.status == "FAIL"]
        assert len(fail_checks) == 0, [r.message for r in fail_checks]

    def test_p1_missing_required_fails(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        # Clear a required note
        raw_modified = raw.model_copy(
            update={
                "notes": raw.notes.model_copy(update={"taxes": None}),
            }
        )
        report = ExtractionValidator().validate_completeness(
            raw_modified, Profile.P1_INDUSTRIAL
        )
        assert report.overall_status == "FAIL"
        taxes_check = next(r for r in report.results if r.check_id == "C.R.taxes")
        assert taxes_check.status == "FAIL"

    def test_p1_missing_recommended_warns(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        # pensions is recommended, fixture doesn't have it → WARN
        report = ExtractionValidator().validate_completeness(raw, Profile.P1_INDUSTRIAL)
        pensions = next(r for r in report.results if r.check_id == "C.O.pensions")
        assert pensions.status == "WARN"

    def test_p1_checklist_has_10_required(self) -> None:
        required = REQUIRED_NOTES_BY_PROFILE[Profile.P1_INDUSTRIAL]
        assert len(required) == 10
        assert "taxes" in required
        assert "leases" in required

    def test_unsupported_profile_skips(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        # P2 banks has no entry in REQUIRED_NOTES_BY_PROFILE → SKIP
        report = ExtractionValidator().validate_completeness(raw, Profile.P2_BANKS)
        assert report.overall_status == "SKIP"
        assert any(r.check_id == "C.P0" and r.status == "SKIP" for r in report.results)


# ======================================================================
# 4. ValidationReport aggregation
# ======================================================================


class TestValidationReport:
    def test_empty_report_overall_ok(self) -> None:
        report = ValidationReport(tier="strict")
        assert report.overall_status == "OK"

    def test_precedence_fail_over_warn(self) -> None:
        report = ValidationReport(tier="warn")
        report.add(ValidationResult("A", "OK", ""))
        report.add(ValidationResult("B", "WARN", ""))
        report.add(ValidationResult("C", "FAIL", ""))
        assert report.overall_status == "FAIL"

    def test_precedence_warn_over_ok(self) -> None:
        report = ValidationReport(tier="warn")
        report.add(ValidationResult("A", "OK", ""))
        report.add(ValidationResult("B", "WARN", ""))
        assert report.overall_status == "WARN"

    def test_fails_warns_accessors(self) -> None:
        report = ValidationReport(tier="warn")
        report.add(ValidationResult("A", "OK", ""))
        report.add(ValidationResult("B", "WARN", "w1"))
        report.add(ValidationResult("C", "FAIL", "f1"))
        report.add(ValidationResult("D", "WARN", "w2"))
        assert len(report.fails) == 1
        assert len(report.warns) == 2

    @pytest.mark.parametrize(
        "statuses, expected",
        [
            (["OK"], "OK"),
            (["SKIP"], "SKIP"),
            (["OK", "SKIP"], "OK"),  # OK > SKIP
            (["WARN", "OK"], "WARN"),
            (["FAIL", "WARN"], "FAIL"),
        ],
    )
    def test_overall_status_parametrized(
        self,
        statuses: list[ValidationStatus],
        expected: ValidationStatus,
    ) -> None:
        report = ValidationReport(tier="warn")
        for i, s in enumerate(statuses):
            report.add(ValidationResult(f"C{i}", s, ""))
        assert report.overall_status == expected
