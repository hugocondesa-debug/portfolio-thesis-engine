"""Unit tests for ingestion.raw_extraction_validator (Phase 1.5.3)."""

from __future__ import annotations

from pathlib import Path

from portfolio_thesis_engine.ingestion.raw_extraction_parser import (
    parse_raw_extraction,
)
from portfolio_thesis_engine.ingestion.raw_extraction_validator import (
    REQUIRED_NOTE_PATTERNS,
    ExtractionValidator,
)
from portfolio_thesis_engine.schemas.common import Currency, Profile
from portfolio_thesis_engine.schemas.raw_extraction import (
    DocumentType,
    ExtractionType,
    RawExtraction,
)

_FIXTURE = Path(__file__).parent.parent / "fixtures" / "euroeyes" / "raw_extraction_ar_2024.yaml"
_REAL_CLAUDE_AI_FIXTURE = (
    Path(__file__).parent.parent / "fixtures" / "euroeyes"
    / "raw_extraction_real_claude_ai_2025.yaml"
)


def _minimal_payload() -> dict:
    """Minimal numeric payload with clean identities for validator tests."""
    return {
        "metadata": {
            "ticker": "TST",
            "company_name": "Test",
            "document_type": DocumentType.ANNUAL_REPORT,
            "extraction_type": ExtractionType.NUMERIC,
            "reporting_currency": Currency.USD,
            "unit_scale": "units",
            "extraction_date": "2025-01-01",
            "fiscal_periods": [
                {"period": "FY2024", "end_date": "2024-12-31", "is_primary": True},
            ],
        },
        "income_statement": {
            "FY2024": {
                "line_items": [
                    {"order": 1, "label": "Revenue", "value": "1000"},
                    {"order": 2, "label": "Cost of sales", "value": "-600"},
                    {
                        "order": 3, "label": "Gross profit",
                        "value": "400", "is_subtotal": True,
                    },
                    {"order": 4, "label": "Selling expenses", "value": "-100"},
                    {"order": 5, "label": "G&A expenses", "value": "-50"},
                    {
                        "order": 6, "label": "Operating profit",
                        "value": "250", "is_subtotal": True,
                    },
                    {"order": 7, "label": "Finance income", "value": "5"},
                    {"order": 8, "label": "Finance costs", "value": "-15"},
                    {
                        "order": 9, "label": "Profit before taxation",
                        "value": "240", "is_subtotal": True,
                    },
                    {"order": 10, "label": "Income tax", "value": "-60"},
                    {
                        "order": 11, "label": "Profit for the year",
                        "value": "180", "is_subtotal": True,
                    },
                ],
            },
        },
        "balance_sheet": {
            "FY2024": {
                "line_items": [
                    # current_assets
                    {
                        "order": 1, "label": "Cash and cash equivalents",
                        "value": "200", "section": "current_assets",
                    },
                    {
                        "order": 2, "label": "Trade receivables",
                        "value": "150", "section": "current_assets",
                    },
                    {
                        "order": 3, "label": "Total current assets",
                        "value": "350", "section": "current_assets",
                        "is_subtotal": True,
                    },
                    # non_current_assets
                    {
                        "order": 4, "label": "Property, plant and equipment",
                        "value": "700", "section": "non_current_assets",
                    },
                    {
                        "order": 5, "label": "Goodwill",
                        "value": "100", "section": "non_current_assets",
                    },
                    {
                        "order": 6, "label": "Total non-current assets",
                        "value": "800", "section": "non_current_assets",
                        "is_subtotal": True,
                    },
                    # total_assets
                    {
                        "order": 7, "label": "Total assets",
                        "value": "1150", "section": "total_assets",
                        "is_subtotal": True,
                    },
                    # current_liabilities
                    {
                        "order": 8, "label": "Trade payables",
                        "value": "80", "section": "current_liabilities",
                    },
                    {
                        "order": 9, "label": "Total current liabilities",
                        "value": "80", "section": "current_liabilities",
                        "is_subtotal": True,
                    },
                    # non_current_liabilities
                    {
                        "order": 10, "label": "Long-term borrowings",
                        "value": "300", "section": "non_current_liabilities",
                    },
                    {
                        "order": 11, "label": "Total non-current liabilities",
                        "value": "300", "section": "non_current_liabilities",
                        "is_subtotal": True,
                    },
                    {
                        "order": 12, "label": "Total liabilities",
                        "value": "380", "section": "total_liabilities",
                        "is_subtotal": True,
                    },
                    # equity
                    {
                        "order": 13, "label": "Share capital",
                        "value": "300", "section": "equity",
                    },
                    {
                        "order": 14, "label": "Retained earnings",
                        "value": "470", "section": "equity",
                    },
                    {
                        "order": 15, "label": "Total equity",
                        "value": "770", "section": "equity",
                        "is_subtotal": True,
                    },
                ],
            },
        },
    }


# ======================================================================
# Strict tier
# ======================================================================


class TestStrictTier:
    def test_clean_payload_strict_ok(self) -> None:
        raw = RawExtraction.model_validate(_minimal_payload())
        report = ExtractionValidator().validate_strict(raw)
        assert report.overall_status == "OK"

    def test_is_walking_subtotal_fail(self) -> None:
        payload = _minimal_payload()
        # Break gross profit: revenue 1000 - COGS 600 = 400, but we
        # set it to 500.
        payload["income_statement"]["FY2024"]["line_items"][2]["value"] = "500"
        raw = RawExtraction.model_validate(payload)
        report = ExtractionValidator().validate_strict(raw)
        assert report.overall_status == "FAIL"
        assert any(r.check_id.startswith("S.IS") and r.status == "FAIL"
                   for r in report.results)

    def test_bs_identity_fail(self) -> None:
        payload = _minimal_payload()
        # Break BS identity: Assets = 1150, but set Liab + Equity to 1200
        # by bumping total equity.
        payload["balance_sheet"]["FY2024"]["line_items"][-1]["value"] = "820"
        raw = RawExtraction.model_validate(payload)
        report = ExtractionValidator().validate_strict(raw)
        assert report.overall_status == "FAIL"
        assert any(r.check_id == "S.BS.IDENTITY" and r.status == "FAIL"
                   for r in report.results)

    def test_bs_section_walk_fail(self) -> None:
        payload = _minimal_payload()
        # Break current-assets section: cash 200 + AR 150 = 350; set
        # subtotal to 400 instead.
        payload["balance_sheet"]["FY2024"]["line_items"][2]["value"] = "400"
        # Also bump Total assets to keep identity satisfied at grand level
        payload["balance_sheet"]["FY2024"]["line_items"][6]["value"] = "1200"
        # And bump equity so identity still holds
        payload["balance_sheet"]["FY2024"]["line_items"][-2]["value"] = "520"
        payload["balance_sheet"]["FY2024"]["line_items"][-1]["value"] = "820"
        raw = RawExtraction.model_validate(payload)
        report = ExtractionValidator().validate_strict(raw)
        # Section walk for current_assets should FAIL.
        assert any(
            r.check_id.startswith("S.BS.current_assets")
            and r.status == "FAIL"
            for r in report.results
        )

    def test_cross_section_grand_totals_skipped_not_failed(self) -> None:
        """Total assets / Total liabilities / CF net change are single-
        line sections — walker skips them."""
        raw = RawExtraction.model_validate(_minimal_payload())
        report = ExtractionValidator().validate_strict(raw)
        # No FAIL on total_assets section walk (skipped).
        ta_walks = [
            r for r in report.results
            if r.check_id.startswith("S.BS.total_assets")
        ]
        for r in ta_walks:
            assert r.status != "FAIL"


# ======================================================================
# Phase 1.5.5 — IFRS IS patterns
# ======================================================================


def _payload_with_nested_finance_subtotal() -> dict:
    """IS with Finance income/(expenses), net as a nested subtotal
    (sum of the two preceding finance lines, should NOT reset
    waterfall)."""
    return {
        "metadata": {
            "ticker": "TST",
            "company_name": "Test",
            "document_type": DocumentType.ANNUAL_REPORT,
            "extraction_type": ExtractionType.NUMERIC,
            "reporting_currency": Currency.USD,
            "unit_scale": "units",
            "extraction_date": "2025-01-01",
            "fiscal_periods": [
                {"period": "FY2024", "end_date": "2024-12-31", "is_primary": True},
            ],
        },
        "income_statement": {
            "FY2024": {
                "line_items": [
                    {"order": 1, "label": "Revenue", "value": "1000"},
                    {"order": 2, "label": "Cost of sales", "value": "-400"},
                    {
                        "order": 3, "label": "Gross profit",
                        "value": "600", "is_subtotal": True,
                    },
                    {"order": 4, "label": "Operating expenses", "value": "-485"},
                    {
                        "order": 5, "label": "Operating profit",
                        "value": "115", "is_subtotal": True,
                    },
                    {"order": 6, "label": "Finance income", "value": "26"},
                    {"order": 7, "label": "Finance expenses", "value": "-16"},
                    {
                        "order": 8,
                        "label": "Finance income/(expenses), net",
                        "value": "10",
                        "is_subtotal": True,
                    },
                    {
                        "order": 9, "label": "Profit before tax",
                        "value": "125", "is_subtotal": True,
                    },
                    {"order": 10, "label": "Income tax", "value": "-42"},
                    {
                        "order": 11, "label": "Profit for the year",
                        "value": "83", "is_subtotal": True,
                    },
                ],
            },
        },
        "balance_sheet": {
            "FY2024": {
                "line_items": [
                    {
                        "order": 1, "label": "Total assets",
                        "value": "1000", "section": "total_assets",
                        "is_subtotal": True,
                    },
                ],
            },
        },
    }


class TestNestedSubtotals:
    def test_auto_detected_nested_subtotal(self) -> None:
        """IS with "Finance income/(expenses), net" nested subtotal —
        validator auto-detects (no flag on LineItem) because the
        sum-since-anchor matches."""
        raw = RawExtraction.model_validate(_payload_with_nested_finance_subtotal())
        report = ExtractionValidator().validate_strict(raw)
        assert report.overall_status == "OK"
        # At least one NESTED check emitted.
        assert any(r.check_id.startswith("S.IS.NESTED") for r in report.results)

    def test_explicit_nested_flag(self) -> None:
        """Same pattern with ``skip_in_waterfall=True`` explicitly."""
        payload = _payload_with_nested_finance_subtotal()
        payload["income_statement"]["FY2024"]["line_items"][7]["skip_in_waterfall"] = True
        raw = RawExtraction.model_validate(payload)
        report = ExtractionValidator().validate_strict(raw)
        assert report.overall_status == "OK"


# ======================================================================
# Phase 1.5.5 — OCI + TCI
# ======================================================================


def _payload_with_oci_and_tci() -> dict:
    """IS with OCI section + TCI. PFY=100, OCI=-20, TCI=80."""
    return {
        "metadata": {
            "ticker": "TST",
            "company_name": "Test",
            "document_type": DocumentType.ANNUAL_REPORT,
            "extraction_type": ExtractionType.NUMERIC,
            "reporting_currency": Currency.USD,
            "unit_scale": "units",
            "extraction_date": "2025-01-01",
            "fiscal_periods": [
                {"period": "FY2024", "end_date": "2024-12-31", "is_primary": True},
            ],
        },
        "income_statement": {
            "FY2024": {
                "line_items": [
                    {"order": 1, "label": "Revenue", "value": "1000"},
                    {"order": 2, "label": "Total expenses", "value": "-850"},
                    {
                        "order": 3, "label": "Profit before tax",
                        "value": "150", "is_subtotal": True,
                    },
                    {"order": 4, "label": "Income tax", "value": "-50"},
                    {
                        "order": 5, "label": "Profit for the year",
                        "value": "100", "is_subtotal": True,
                    },
                    # OCI section
                    {
                        "order": 6,
                        "label": "Other comprehensive (loss)/income",
                        "value": None,
                    },
                    {
                        "order": 7,
                        "label": "Items that may be reclassified to profit or loss",
                        "value": None,
                    },
                    {
                        "order": 8,
                        "label": "Exchange differences on translation of foreign operations",
                        "value": "-25",
                    },
                    {
                        "order": 9,
                        "label": "Items that will not be reclassified to profit or loss",
                        "value": None,
                    },
                    {
                        "order": 10,
                        "label": "Remeasurement of defined benefit plans",
                        "value": "5",
                    },
                    {
                        "order": 11,
                        "label": "Other comprehensive loss for the year",
                        "value": "-20",
                        "is_subtotal": True,
                    },
                    {
                        "order": 12,
                        "label": "Total comprehensive income for the year",
                        "value": "80",
                        "is_subtotal": True,
                    },
                ],
            },
        },
        "balance_sheet": {
            "FY2024": {
                "line_items": [
                    {
                        "order": 1, "label": "Total assets",
                        "value": "1000", "section": "total_assets",
                        "is_subtotal": True,
                    },
                ],
            },
        },
    }


class TestOCITCI:
    def test_oci_and_tci_ok(self) -> None:
        raw = RawExtraction.model_validate(_payload_with_oci_and_tci())
        report = ExtractionValidator().validate_strict(raw)
        assert report.overall_status == "OK"
        # OCI + TCI dedicated checks present
        assert any(r.check_id == "S.IS.OCI" and r.status == "OK" for r in report.results)
        assert any(r.check_id == "S.IS.TCI" and r.status == "OK" for r in report.results)

    def test_tci_mismatch_fails(self) -> None:
        payload = _payload_with_oci_and_tci()
        # Break TCI: PFY 100 + OCI -20 should = 80; set to 75.
        payload["income_statement"]["FY2024"]["line_items"][-1]["value"] = "75"
        raw = RawExtraction.model_validate(payload)
        report = ExtractionValidator().validate_strict(raw)
        assert any(
            r.check_id == "S.IS.TCI" and r.status == "FAIL"
            for r in report.results
        )

    def test_oci_subtotal_mismatch_fails(self) -> None:
        payload = _payload_with_oci_and_tci()
        # Break OCI: -25 + 5 = -20; set to -30.
        payload["income_statement"]["FY2024"]["line_items"][-2]["value"] = "-30"
        raw = RawExtraction.model_validate(payload)
        report = ExtractionValidator().validate_strict(raw)
        assert any(
            r.check_id == "S.IS.OCI" and r.status == "FAIL"
            for r in report.results
        )


# ======================================================================
# Phase 1.5.5 — BS multi-level equity subtotals
# ======================================================================


def _payload_with_tep_and_total_equity() -> dict:
    """BS with both Total equity attributable to parent + NCI +
    Total equity (grand)."""
    return {
        "metadata": {
            "ticker": "TST",
            "company_name": "Test",
            "document_type": DocumentType.ANNUAL_REPORT,
            "extraction_type": ExtractionType.NUMERIC,
            "reporting_currency": Currency.USD,
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
                        "order": 2, "label": "Profit for the year",
                        "value": "10", "is_subtotal": True,
                    },
                ],
            },
        },
        "balance_sheet": {
            "FY2024": {
                "line_items": [
                    {
                        "order": 1, "label": "Total assets",
                        "value": "1000", "section": "total_assets",
                        "is_subtotal": True,
                    },
                    {
                        "order": 2, "label": "Total liabilities",
                        "value": "400", "section": "total_liabilities",
                        "is_subtotal": True,
                    },
                    {
                        "order": 3, "label": "Share capital",
                        "value": "300", "section": "equity",
                    },
                    {
                        "order": 4, "label": "Retained earnings",
                        "value": "270", "section": "equity",
                    },
                    {
                        "order": 5,
                        "label": "Total equity attributable to owners",
                        "value": "570",
                        "section": "equity",
                        "is_subtotal": True,
                    },
                    {
                        "order": 6,
                        "label": "Non-controlling interests",
                        "value": "30",
                        "section": "equity",
                    },
                    {
                        "order": 7, "label": "Total equity",
                        "value": "600", "section": "equity",
                        "is_subtotal": True,
                    },
                ],
            },
        },
    }


class TestEquityMultiSubtotal:
    def test_identity_uses_last_equity_subtotal(self) -> None:
        """BS identity picks the LAST equity subtotal (Total equity
        incl. NCI), not the first (TEP). Identity: 1000 = 400 + 600."""
        raw = RawExtraction.model_validate(_payload_with_tep_and_total_equity())
        report = ExtractionValidator().validate_strict(raw)
        identity = next(r for r in report.results if r.check_id == "S.BS.IDENTITY")
        assert identity.status == "OK"
        assert identity.data["equity_subtotal_label"] == "Total equity"


# ======================================================================
# Phase 1.5.5 — CF memo lines
# ======================================================================


def _payload_with_cf_memo_lines() -> dict:
    """CF with opening / closing memo balances tagged notes: 'memo'."""
    return {
        "metadata": {
            "ticker": "TST",
            "company_name": "Test",
            "document_type": DocumentType.ANNUAL_REPORT,
            "extraction_type": ExtractionType.NUMERIC,
            "reporting_currency": Currency.USD,
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
                        "order": 2, "label": "Profit for the year",
                        "value": "10", "is_subtotal": True,
                    },
                ],
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
                ],
            },
        },
        "cash_flow": {
            "FY2024": {
                "line_items": [
                    {
                        "order": 1, "label": "Net cash from operating",
                        "value": "100", "section": "operating",
                        "is_subtotal": True,
                    },
                    {
                        "order": 2, "label": "Net cash used in investing",
                        "value": "-60", "section": "investing",
                        "is_subtotal": True,
                    },
                    {
                        "order": 3, "label": "Net cash used in financing",
                        "value": "-30", "section": "financing",
                        "is_subtotal": True,
                    },
                    {
                        "order": 4, "label": "Net increase in cash",
                        "value": "10", "section": "subtotal",
                        "is_subtotal": True,
                    },
                    {
                        "order": 5, "label": "Cash at beginning of year",
                        "value": "200", "section": "subtotal",
                        "is_subtotal": True, "notes": "memo",
                    },
                    {
                        "order": 6, "label": "Cash at end of year",
                        "value": "210", "section": "subtotal",
                        "is_subtotal": True, "notes": "memo",
                    },
                ],
            },
        },
    }


class TestCFMemoLines:
    def test_net_change_label_match_preferred_over_memo(self) -> None:
        """W.CF identity uses the 'Net increase in cash' line, not
        the memo cash-closing line."""
        raw = RawExtraction.model_validate(_payload_with_cf_memo_lines())
        report = ExtractionValidator().validate_warn(raw)
        w_cf = next(r for r in report.results if r.check_id == "W.CF")
        assert w_cf.status == "OK"
        assert "Net increase in cash" in w_cf.data["net_change_label"]


# ======================================================================
# Warn tier
# ======================================================================


class TestWarnTier:
    def test_warn_tier_on_fixture(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        report = ExtractionValidator().validate_warn(raw)
        # The fixture is clean; warn tier should be OK.
        assert report.overall_status in ("OK", "WARN")

    def test_shares_check_basic_gt_diluted_warns(self) -> None:
        payload = _minimal_payload()
        payload["income_statement"]["FY2024"]["earnings_per_share"] = {
            "basic_weighted_avg_shares": "1000",
            "diluted_weighted_avg_shares": "900",  # wrong — diluted < basic
        }
        raw = RawExtraction.model_validate(payload)
        report = ExtractionValidator().validate_warn(raw)
        assert any(
            r.check_id == "W.SHARES" and r.status == "WARN"
            for r in report.results
        )

    def test_yoy_sanity_skip_with_one_period(self) -> None:
        raw = RawExtraction.model_validate(_minimal_payload())
        report = ExtractionValidator().validate_warn(raw)
        yoy = next(r for r in report.results if r.check_id == "W.YOY")
        assert yoy.status == "SKIP"


# ======================================================================
# Completeness tier
# ======================================================================


class TestCompletenessTier:
    def test_fixture_has_most_required_notes(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        report = ExtractionValidator().validate_completeness(
            raw, Profile.P1_INDUSTRIAL
        )
        # Required checks (C.R.*) all pass on the fixture (10 notes).
        required_checks = [r for r in report.results if r.check_id.startswith("C.R.")]
        assert all(r.status == "OK" for r in required_checks)

    def test_missing_all_notes_all_fail(self) -> None:
        raw = RawExtraction.model_validate(_minimal_payload())
        report = ExtractionValidator().validate_completeness(
            raw, Profile.P1_INDUSTRIAL
        )
        required_checks = [r for r in report.results if r.check_id.startswith("C.R.")]
        assert all(r.status == "FAIL" for r in required_checks)

    def test_unconfigured_profile_skips(self) -> None:
        raw = RawExtraction.model_validate(_minimal_payload())
        report = ExtractionValidator().validate_completeness(
            raw, Profile.P2_BANKS
        )
        assert any(r.status == "SKIP" for r in report.results)

    def test_note_pattern_matches_title_variants(self) -> None:
        """Tax note title variants all match the pattern."""
        pattern = REQUIRED_NOTE_PATTERNS[Profile.P1_INDUSTRIAL]["taxes"]
        assert pattern.search("Income tax")
        assert pattern.search("Income taxes")
        assert pattern.search("Taxation")
        assert pattern.search("Note 6 — income tax expense")
        assert not pattern.search("Leases")

    def test_note_with_empty_tables_and_summary_not_counted(self) -> None:
        """A note that matches title but has nothing populated should
        NOT count toward completeness."""
        payload = _minimal_payload()
        payload["notes"] = [
            {
                "title": "Income tax",  # matches pattern
                # no tables, no narrative_summary
            },
        ]
        raw = RawExtraction.model_validate(payload)
        report = ExtractionValidator().validate_completeness(
            raw, Profile.P1_INDUSTRIAL
        )
        tax_check = next(r for r in report.results if r.check_id == "C.R.taxes")
        assert tax_check.status == "FAIL"

    def test_note_with_narrative_summary_counts(self) -> None:
        payload = _minimal_payload()
        payload["notes"] = [
            {
                "title": "Income tax",
                "narrative_summary": "ETR 30%; see next period for reconciliation.",
            },
        ]
        raw = RawExtraction.model_validate(payload)
        report = ExtractionValidator().validate_completeness(
            raw, Profile.P1_INDUSTRIAL
        )
        tax_check = next(r for r in report.results if r.check_id == "C.R.taxes")
        assert tax_check.status == "OK"


# ======================================================================
# Full real fixture strict pass
# ======================================================================


class TestRealFixture:
    def test_strict_ok_on_fixture(self) -> None:
        raw = parse_raw_extraction(_FIXTURE)
        report = ExtractionValidator().validate_strict(raw)
        # Every walking-subtotal on IS / BS / CF + S.BS.IDENTITY should pass.
        fails = [r for r in report.results if r.status == "FAIL"]
        assert fails == [], f"Unexpected FAILs: {[f.check_id for f in fails]}"

    def test_real_claude_ai_fixture_strict_ok(self) -> None:
        """Phase 1.5.5 regression: Hugo's real 4288-line EuroEyes
        extraction — which uses Finance income/(expenses), net as a
        nested subtotal, an OCI section, TEP + NCI + Total equity on
        the BS, and memo cash-balance lines on the CF — must validate
        strictly OK after the validator enhancements."""
        raw = parse_raw_extraction(_REAL_CLAUDE_AI_FIXTURE)
        report = ExtractionValidator().validate_strict(raw)
        fails = [r for r in report.results if r.status == "FAIL"]
        assert fails == [], f"Unexpected FAILs: {[f.check_id for f in fails]}"
