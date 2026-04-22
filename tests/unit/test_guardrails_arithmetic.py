"""Unit tests for guardrails.checks.arithmetic."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from portfolio_thesis_engine.guardrails.checks.arithmetic import (
    BSChecksum,
    CFChecksum,
    ICConsistency,
    ISChecksum,
)
from portfolio_thesis_engine.schemas.common import (
    Currency,
    FiscalPeriod,
    GuardrailStatus,
    Profile,
)
from portfolio_thesis_engine.schemas.company import (
    AdjustmentsApplied,
    AnalysisDerived,
    BalanceSheetLine,
    CanonicalCompanyState,
    CashFlowLine,
    CompanyIdentity,
    IncomeStatementLine,
    InvestedCapital,
    KeyRatios,
    MethodologyMetadata,
    NOPATBridge,
    ReclassifiedStatements,
    ValidationResult,
    ValidationResults,
    VintageAndCascade,
)
from portfolio_thesis_engine.schemas.raw_extraction import (
    DocumentType,
    ExtractionType,
    RawExtraction,
)

# ======================================================================
# Helpers
# ======================================================================


def _period() -> FiscalPeriod:
    return FiscalPeriod(year=2024, label="FY2024")


def _identity() -> CompanyIdentity:
    return CompanyIdentity(
        ticker="TST",
        name="Test Co",
        reporting_currency=Currency.USD,
        profile=Profile.P1_INDUSTRIAL,
        fiscal_year_end_month=12,
        country_domicile="US",
        exchange="NYSE",
    )


def _state(
    *,
    is_lines: list[IncomeStatementLine] | None = None,
    bs_lines: list[BalanceSheetLine] | None = None,
    cf_lines: list[CashFlowLine] | None = None,
    ic: InvestedCapital | None = None,
    nopat: NOPATBridge | None = None,
    ratios: KeyRatios | None = None,
) -> CanonicalCompanyState:
    period = _period()
    return CanonicalCompanyState(
        extraction_id="x",
        extraction_date=datetime(2024, 12, 31, tzinfo=UTC),
        as_of_date="2024-12-31",
        identity=_identity(),
        reclassified_statements=[
            ReclassifiedStatements(
                period=period,
                income_statement=is_lines or [],
                balance_sheet=bs_lines or [],
                cash_flow=cf_lines or [],
                bs_checksum_pass=True,
                is_checksum_pass=True,
                cf_checksum_pass=True,
            )
        ],
        adjustments=AdjustmentsApplied(),
        analysis=AnalysisDerived(
            invested_capital_by_period=[ic] if ic else [],
            nopat_bridge_by_period=[nopat] if nopat else [],
            ratios_by_period=[ratios] if ratios else [],
        ),
        validation=ValidationResults(
            universal_checksums=[
                ValidationResult(check_id="V.0", name="stub", status="PASS", detail="ok")
            ],
            profile_specific_checksums=[],
            confidence_rating="MEDIUM",
        ),
        vintage=VintageAndCascade(),
        methodology=MethodologyMetadata(
            extraction_system_version="test",
            profile_applied=Profile.P1_INDUSTRIAL,
            protocols_activated=[],
        ),
    )


# ======================================================================
# ISChecksum (Phase 1.5.6 — reads raw_extraction with line_items)
# ======================================================================


def _raw_with_is(line_items: list[dict]) -> RawExtraction:
    """Minimal valid RawExtraction with the given IS line_items."""
    return RawExtraction.model_validate({
        "metadata": {
            "ticker": "TST",
            "company_name": "Test Co",
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
            "FY2024": {"line_items": line_items},
        },
        "balance_sheet": {
            "FY2024": {
                "line_items": [
                    {
                        "order": 1, "label": "Total assets",
                        "value": "100", "section": "total_assets",
                        "is_subtotal": True,
                    },
                ],
            },
        },
    })


class TestISChecksum:
    def test_exact_match_passes(self) -> None:
        raw = _raw_with_is([
            {"order": 1, "label": "Revenue", "value": "100"},
            {"order": 2, "label": "COGS", "value": "-60"},
            {"order": 3, "label": "Tax", "value": "-10"},
            {"order": 4, "label": "Profit for the year",
             "value": "30", "is_subtotal": True},
        ])
        result = ISChecksum().check({"raw_extraction": raw})
        assert result.status == GuardrailStatus.PASS

    def test_small_drift_warns(self) -> None:
        # Components: 100 - 60 - 9.91 = 30.09; reported 30; delta 0.3%.
        raw = _raw_with_is([
            {"order": 1, "label": "Revenue", "value": "100"},
            {"order": 2, "label": "COGS", "value": "-60"},
            {"order": 3, "label": "Tax", "value": "-9.910"},
            {"order": 4, "label": "Profit for the year",
             "value": "30", "is_subtotal": True},
        ])
        result = ISChecksum().check({"raw_extraction": raw})
        assert result.status == GuardrailStatus.WARN

    def test_big_drift_fails(self) -> None:
        # Components sum to 25 vs reported 30 → ~16.7% off.
        raw = _raw_with_is([
            {"order": 1, "label": "Revenue", "value": "100"},
            {"order": 2, "label": "COGS", "value": "-60"},
            {"order": 3, "label": "Tax", "value": "-15"},
            {"order": 4, "label": "Profit for the year",
             "value": "30", "is_subtotal": True},
        ])
        result = ISChecksum().check({"raw_extraction": raw})
        assert result.status == GuardrailStatus.FAIL
        assert result.blocking is True

    def test_no_ni_line_skips(self) -> None:
        raw = _raw_with_is([
            {"order": 1, "label": "Revenue", "value": "100"},
            # No PFY / NI subtotal anywhere — walker finds nothing.
            {"order": 2, "label": "Some other subtotal",
             "value": "100", "is_subtotal": True},
        ])
        result = ISChecksum().check({"raw_extraction": raw})
        assert result.status == GuardrailStatus.SKIP

    def test_empty_state_skips(self) -> None:
        # No raw_extraction on context at all.
        result = ISChecksum().check({})
        assert result.status == GuardrailStatus.SKIP

    def test_nested_subtotal_not_double_counted(self) -> None:
        """Phase 1.5.6 regression — nested "X, net" subtotals that
        sit mid-waterfall mustn't break the sum-leaves-to-PFY check."""
        raw = _raw_with_is([
            {"order": 1, "label": "Revenue", "value": "1000"},
            {"order": 2, "label": "Cost of sales", "value": "-400"},
            {"order": 3, "label": "Gross profit",
             "value": "600", "is_subtotal": True},
            {"order": 4, "label": "Operating expenses", "value": "-485"},
            {"order": 5, "label": "Operating profit",
             "value": "115", "is_subtotal": True},
            {"order": 6, "label": "Finance income", "value": "26"},
            {"order": 7, "label": "Finance expenses", "value": "-16"},
            {"order": 8, "label": "Finance income/(expenses), net",
             "value": "10", "is_subtotal": True},
            {"order": 9, "label": "Profit before tax",
             "value": "125", "is_subtotal": True},
            {"order": 10, "label": "Income tax", "value": "-42"},
            {"order": 11, "label": "Profit for the year",
             "value": "83", "is_subtotal": True},
        ])
        result = ISChecksum().check({"raw_extraction": raw})
        # Σ leaves = 1000 - 400 - 485 + 26 - 16 - 42 = 83 ✓
        assert result.status == GuardrailStatus.PASS


# ======================================================================
# BSChecksum
# ======================================================================


class TestBSChecksum:
    def test_identity_holds(self) -> None:
        bs = [
            BalanceSheetLine(label="Cash", value=Decimal("100"), category="cash"),
            BalanceSheetLine(label="PP&E", value=Decimal("400"), category="operating_assets"),
            BalanceSheetLine(label="Debt", value=Decimal("200"), category="financial_liabilities"),
            BalanceSheetLine(label="Equity", value=Decimal("300"), category="equity"),
        ]
        result = BSChecksum().check({"canonical_state": _state(bs_lines=bs)})
        assert result.status == GuardrailStatus.PASS

    def test_small_drift_warns(self) -> None:
        # Assets 500 vs L+E 500.05 → 0.01% (PASS boundary)
        # Use 500 vs 500.2 → 0.04% → WARN
        bs = [
            BalanceSheetLine(label="Cash", value=Decimal("500"), category="cash"),
            BalanceSheetLine(
                label="Debt", value=Decimal("200.2"), category="financial_liabilities"
            ),
            BalanceSheetLine(label="Equity", value=Decimal("300"), category="equity"),
        ]
        result = BSChecksum().check({"canonical_state": _state(bs_lines=bs)})
        assert result.status == GuardrailStatus.WARN

    def test_big_drift_fails(self) -> None:
        bs = [
            BalanceSheetLine(label="Cash", value=Decimal("500"), category="cash"),
            BalanceSheetLine(
                label="Debt", value=Decimal("100"), category="financial_liabilities"
            ),
            BalanceSheetLine(label="Equity", value=Decimal("300"), category="equity"),
        ]
        result = BSChecksum().check({"canonical_state": _state(bs_lines=bs)})
        # Assets 500 vs L+E 400 = 20% off
        assert result.status == GuardrailStatus.FAIL
        assert result.blocking is True

    def test_all_zero_skips(self) -> None:
        bs = [
            BalanceSheetLine(label="Stub", value=Decimal("0"), category="other"),
        ]
        result = BSChecksum().check({"canonical_state": _state(bs_lines=bs)})
        assert result.status == GuardrailStatus.SKIP

    def test_empty_bs_skips(self) -> None:
        result = BSChecksum().check({"canonical_state": _state()})
        assert result.status == GuardrailStatus.SKIP


# ======================================================================
# CFChecksum
# ======================================================================


class TestCFChecksum:
    def test_identity_holds(self) -> None:
        cf = [
            CashFlowLine(label="CFO", value=Decimal("100"), category="cfo"),
            CashFlowLine(label="CFI", value=Decimal("-60"), category="cfi"),
            CashFlowLine(label="CFF", value=Decimal("-20"), category="cff"),
            CashFlowLine(label="ΔCash", value=Decimal("20"), category="net_change_in_cash"),
        ]
        result = CFChecksum().check({"canonical_state": _state(cf_lines=cf)})
        assert result.status == GuardrailStatus.PASS

    def test_small_drift_warns(self) -> None:
        cf = [
            CashFlowLine(label="CFO", value=Decimal("100"), category="cfo"),
            CashFlowLine(label="CFI", value=Decimal("-60"), category="cfi"),
            CashFlowLine(label="CFF", value=Decimal("-20"), category="cff"),
            # 20 reported, 20.2 computed → 1% off → WARN (PASS≤0.5%, FAIL>2%)
            CashFlowLine(label="ΔCash", value=Decimal("19.8"), category="net_change_in_cash"),
        ]
        result = CFChecksum().check({"canonical_state": _state(cf_lines=cf)})
        assert result.status == GuardrailStatus.WARN

    def test_big_drift_fails(self) -> None:
        cf = [
            CashFlowLine(label="CFO", value=Decimal("100"), category="cfo"),
            CashFlowLine(label="CFI", value=Decimal("-60"), category="cfi"),
            CashFlowLine(label="CFF", value=Decimal("-20"), category="cff"),
            CashFlowLine(label="ΔCash", value=Decimal("50"), category="net_change_in_cash"),
        ]
        result = CFChecksum().check({"canonical_state": _state(cf_lines=cf)})
        assert result.status == GuardrailStatus.FAIL

    def test_no_net_change_skips(self) -> None:
        cf = [
            CashFlowLine(label="CFO", value=Decimal("100"), category="cfo"),
        ]
        result = CFChecksum().check({"canonical_state": _state(cf_lines=cf)})
        assert result.status == GuardrailStatus.SKIP
        assert "net_change_in_cash" in result.message


# ======================================================================
# ICConsistency
# ======================================================================


class TestICConsistency:
    def _ic(self, value: Decimal) -> InvestedCapital:
        return InvestedCapital(
            period=_period(),
            operating_assets=value,
            operating_liabilities=Decimal("0"),
            invested_capital=value,
            financial_assets=Decimal("0"),
            financial_liabilities=Decimal("0"),
            equity_claims=value,
            cross_check_residual=Decimal("0"),
        )

    def _nopat(self, value: Decimal) -> NOPATBridge:
        return NOPATBridge(
            period=_period(),
            ebitda=value,
            operating_taxes=Decimal("0"),
            nopat=value,
            financial_income=Decimal("0"),
            financial_expense=Decimal("0"),
            non_operating_items=Decimal("0"),
            reported_net_income=value,
        )

    def _ratios(self, roic: Decimal | None) -> KeyRatios:
        return KeyRatios(period=_period(), roic=roic)

    def test_consistent(self) -> None:
        # IC=1000, NOPAT=100, ROIC=10% → implied IC=1000 → PASS
        result = ICConsistency().check(
            {
                "canonical_state": _state(
                    ic=self._ic(Decimal("1000")),
                    nopat=self._nopat(Decimal("100")),
                    ratios=self._ratios(Decimal("10")),
                )
            }
        )
        assert result.status == GuardrailStatus.PASS

    def test_small_mismatch_warns(self) -> None:
        # IC=1000, NOPAT=100, ROIC=9.9% → implied IC≈1010 → 1% off → WARN
        result = ICConsistency().check(
            {
                "canonical_state": _state(
                    ic=self._ic(Decimal("1000")),
                    nopat=self._nopat(Decimal("100")),
                    ratios=self._ratios(Decimal("9.9")),
                )
            }
        )
        assert result.status == GuardrailStatus.WARN

    def test_big_mismatch_fails(self) -> None:
        # IC=1000, NOPAT=100, ROIC=5% → implied IC=2000 → 50% off → FAIL
        result = ICConsistency().check(
            {
                "canonical_state": _state(
                    ic=self._ic(Decimal("1000")),
                    nopat=self._nopat(Decimal("100")),
                    ratios=self._ratios(Decimal("5")),
                )
            }
        )
        assert result.status == GuardrailStatus.FAIL
        # NOT blocking — ratio issue, not reclass issue
        assert result.blocking is False

    @pytest.mark.parametrize(
        "nopat_val, roic",
        [
            (Decimal("0"), Decimal("10")),  # zero NOPAT
            (Decimal("100"), None),  # no ROIC
            (Decimal("100"), Decimal("0")),  # zero ROIC
        ],
    )
    def test_missing_inputs_skip(
        self, nopat_val: Decimal, roic: Decimal | None
    ) -> None:
        result = ICConsistency().check(
            {
                "canonical_state": _state(
                    ic=self._ic(Decimal("1000")),
                    nopat=self._nopat(nopat_val),
                    ratios=self._ratios(roic),
                )
            }
        )
        assert result.status == GuardrailStatus.SKIP

    def test_no_state_skips(self) -> None:
        result = ICConsistency().check({})
        assert result.status == GuardrailStatus.SKIP
