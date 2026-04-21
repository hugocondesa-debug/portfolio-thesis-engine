"""Pass 3 — Python-side validation of the parsed section data.

Produces :class:`ValidationIssue`s for:

- Missing core sections (``income_statement`` / ``balance_sheet`` / ``cash_flow``)
- Fiscal-period inconsistency across sections
- Currency inconsistency between IS / BS / CF
- Income-statement arithmetic sanity (Revenue − costs ≈ operating income, ±5 %)
- Balance-sheet identity (Total Assets = Total Liabilities + Total Equity, exact within rounding)
- Cash-flow identity (CFO + CFI + CFF ≈ ΔCash, ±2 %)

Issue severities roll up into a single ``overall_status`` using the
standard guardrail precedence ``FAIL > REVIEW > WARN > NOTA > PASS > SKIP``.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from portfolio_thesis_engine.schemas.common import GuardrailStatus
from portfolio_thesis_engine.section_extractor.base import (
    ExtractionResult,
    StructuredSection,
    ValidationIssue,
)

# Acceptable arithmetic tolerances, in fractional form (0.05 = 5 %).
_IS_TOLERANCE = Decimal("0.05")
_CF_TOLERANCE = Decimal("0.02")
_BS_TOLERANCE = Decimal("0.001")  # ≈ 0.1% absolute slack for rounding


# Severity → GuardrailStatus, for overall_status roll-up.
_SEVERITY_TO_STATUS: dict[str, GuardrailStatus] = {
    "FATAL": GuardrailStatus.FAIL,
    "WARN": GuardrailStatus.WARN,
    "INFO": GuardrailStatus.NOTA,
}


class ExtractionValidator:
    """Runs all Pass 3 checks against a Pass 2-completed extraction."""

    # ------------------------------------------------------------------
    def validate(self, result: ExtractionResult) -> list[ValidationIssue]:
        """Return every issue found. Empty list → everything PASSes."""
        issues: list[ValidationIssue] = []
        by_type = {s.section_type: s for s in result.sections}

        issues.extend(self._check_core_sections_present(by_type))
        issues.extend(self._check_fiscal_periods_consistent(result.sections))
        issues.extend(self._check_currencies_consistent(by_type))
        if "income_statement" in by_type:
            issues.extend(self._check_is_arithmetic(by_type["income_statement"]))
        if "balance_sheet" in by_type:
            issues.extend(self._check_bs_identity(by_type["balance_sheet"]))
        if "cash_flow" in by_type:
            issues.extend(self._check_cf_identity(by_type["cash_flow"]))
        return issues

    # ------------------------------------------------------------------
    @staticmethod
    def overall_status(issues: list[ValidationIssue]) -> GuardrailStatus:
        """Worst-case status across issues using guardrail precedence.

        Empty list → PASS. ``FATAL`` dominates, then ``WARN``, then
        ``INFO`` (→ NOTA). Unknown severities fall through to PASS.
        """
        if not issues:
            return GuardrailStatus.PASS
        priority = {
            GuardrailStatus.FAIL: 5,
            GuardrailStatus.REVIEW: 4,
            GuardrailStatus.WARN: 3,
            GuardrailStatus.NOTA: 2,
            GuardrailStatus.PASS: 1,
            GuardrailStatus.SKIP: 0,
        }
        statuses = [_SEVERITY_TO_STATUS.get(i.severity, GuardrailStatus.PASS) for i in issues]
        return max(statuses, key=lambda s: priority[s])

    # ==================================================================
    # Individual checks
    # ==================================================================
    @staticmethod
    def _check_core_sections_present(
        by_type: dict[str, StructuredSection],
    ) -> list[ValidationIssue]:
        """P1 requires IS + BS + CF. Missing any is FATAL."""
        core = ("income_statement", "balance_sheet", "cash_flow")
        issues: list[ValidationIssue] = []
        for required in core:
            if required not in by_type:
                issues.append(
                    ValidationIssue(
                        severity="FATAL",
                        message=f"Core section missing: {required}",
                        section_type=required,
                    )
                )
        return issues

    # ------------------------------------------------------------------
    @staticmethod
    def _check_fiscal_periods_consistent(
        sections: list[StructuredSection],
    ) -> list[ValidationIssue]:
        periods = {s.fiscal_period for s in sections if s.fiscal_period}
        # A comparative prior period appearing alongside the primary is fine
        # (spec C.8 tolerates up to 2 — primary + prior). Anything more
        # is a smell.
        if len(periods) > 2:
            return [
                ValidationIssue(
                    severity="WARN",
                    message=(
                        f"Multiple fiscal periods detected: {sorted(periods)}. "
                        f"Expected at most 2 (primary + prior)."
                    ),
                    details={"periods": sorted(periods)},
                )
            ]
        return []

    # ------------------------------------------------------------------
    @staticmethod
    def _check_currencies_consistent(
        by_type: dict[str, StructuredSection],
    ) -> list[ValidationIssue]:
        """IS / BS / CF must share a reporting currency (segments may differ)."""
        core_currencies: dict[str, str] = {}
        for section_type in ("income_statement", "balance_sheet", "cash_flow"):
            section = by_type.get(section_type)
            if section is None or section.parsed_data is None:
                continue
            currency = section.parsed_data.get("currency")
            if isinstance(currency, str):
                core_currencies[section_type] = currency

        distinct = set(core_currencies.values())
        if len(distinct) > 1:
            return [
                ValidationIssue(
                    severity="FATAL",
                    message=(
                        "IS / BS / CF report in different currencies: "
                        f"{core_currencies}. Reclassification requires a "
                        f"single reporting currency."
                    ),
                    details=dict(core_currencies),
                )
            ]
        return []

    # ------------------------------------------------------------------
    @staticmethod
    def _check_is_arithmetic(
        section: StructuredSection,
    ) -> list[ValidationIssue]:
        """Revenue − (cost_of_sales + opex + d_and_a) ≈ operating_income
        within ±5 %. Skips if any required category is absent."""
        parsed = section.parsed_data
        if not parsed:
            return []
        items = parsed.get("line_items") or []
        totals = _sum_by_category(items)

        revenue = totals.get("revenue")
        operating_income = totals.get("operating_income")
        if revenue is None or operating_income is None:
            return [
                ValidationIssue(
                    severity="INFO",
                    message=(
                        "Income statement arithmetic check skipped — missing "
                        "revenue or operating_income line items."
                    ),
                    section_type="income_statement",
                )
            ]

        costs = sum(
            (totals.get(cat, Decimal("0")) for cat in ("cost_of_sales", "opex", "d_and_a")),
            start=Decimal("0"),
        )
        # cost_of_sales/opex/d_and_a are typically negative in the line items.
        # operating_income ≈ revenue + costs_as_negatives.
        computed = revenue + costs
        diff = abs(computed - operating_income)
        scale = max(abs(operating_income), Decimal("1"))
        if diff / scale > _IS_TOLERANCE:
            return [
                ValidationIssue(
                    severity="WARN",
                    message=(
                        f"IS arithmetic off by {diff} "
                        f"(revenue {revenue} + costs {costs} = {computed}, "
                        f"reported operating_income {operating_income})."
                    ),
                    section_type="income_statement",
                    details={
                        "revenue": str(revenue),
                        "costs": str(costs),
                        "computed_operating_income": str(computed),
                        "reported_operating_income": str(operating_income),
                        "diff": str(diff),
                    },
                )
            ]
        return []

    # ------------------------------------------------------------------
    @staticmethod
    def _check_bs_identity(
        section: StructuredSection,
    ) -> list[ValidationIssue]:
        """Total Assets = Total Liabilities + Total Equity within 0.1 %."""
        parsed = section.parsed_data
        if not parsed:
            return []
        items = parsed.get("line_items") or []
        totals = _sum_by_category(items)

        total_assets = totals.get("total_assets")
        total_liabilities = totals.get("total_liabilities")
        total_equity = totals.get("total_equity")
        if total_assets is None or total_liabilities is None or total_equity is None:
            return [
                ValidationIssue(
                    severity="WARN",
                    message=(
                        "Balance-sheet identity check skipped — missing "
                        "total_assets / total_liabilities / total_equity."
                    ),
                    section_type="balance_sheet",
                )
            ]

        rhs = total_liabilities + total_equity
        diff = abs(total_assets - rhs)
        scale = max(abs(total_assets), Decimal("1"))
        if diff / scale > _BS_TOLERANCE:
            return [
                ValidationIssue(
                    severity="FATAL",
                    message=(
                        f"Balance-sheet identity broken: assets {total_assets} "
                        f"≠ liabilities + equity {rhs} (Δ = {diff})."
                    ),
                    section_type="balance_sheet",
                    details={
                        "total_assets": str(total_assets),
                        "total_liabilities": str(total_liabilities),
                        "total_equity": str(total_equity),
                        "diff": str(diff),
                    },
                )
            ]
        return []

    # ------------------------------------------------------------------
    @staticmethod
    def _check_cf_identity(
        section: StructuredSection,
    ) -> list[ValidationIssue]:
        """CFO + CFI + CFF ≈ net_change_in_cash within ±2 %."""
        parsed = section.parsed_data
        if not parsed:
            return []
        items = parsed.get("line_items") or []
        totals = _sum_by_category(items)

        cfo = totals.get("cfo")
        cfi = totals.get("cfi")
        cff = totals.get("cff")
        delta = totals.get("net_change_in_cash")
        if None in (cfo, cfi, cff, delta):
            return [
                ValidationIssue(
                    severity="INFO",
                    message=(
                        "Cash-flow identity check skipped — missing one of "
                        "cfo / cfi / cff / net_change_in_cash."
                    ),
                    section_type="cash_flow",
                )
            ]

        # After the None guard above, mypy still narrows these — assert for clarity.
        assert cfo is not None and cfi is not None and cff is not None and delta is not None
        computed = cfo + cfi + cff
        diff = abs(computed - delta)
        scale = max(abs(delta), Decimal("1"))
        if diff / scale > _CF_TOLERANCE:
            return [
                ValidationIssue(
                    severity="WARN",
                    message=(
                        f"Cash-flow identity off: CFO+CFI+CFF={computed} "
                        f"vs reported net_change_in_cash={delta} "
                        f"(Δ = {diff})."
                    ),
                    section_type="cash_flow",
                    details={
                        "cfo": str(cfo),
                        "cfi": str(cfi),
                        "cff": str(cff),
                        "net_change_in_cash": str(delta),
                        "diff": str(diff),
                    },
                )
            ]
        return []


# ----------------------------------------------------------------------
def _sum_by_category(
    line_items: list[dict[str, Any]],
) -> dict[str, Decimal]:
    """Group line items by ``category`` and sum their ``value_current``.

    Each category only has its own subtotal line in well-formed reports,
    so this typically returns one entry per category with a single
    underlying value. Returns Decimals to preserve precision.
    """
    sums: dict[str, Decimal] = {}
    for item in line_items:
        category = item.get("category")
        value = item.get("value_current")
        if category is None or value is None:
            continue
        sums[category] = sums.get(category, Decimal("0")) + Decimal(str(value))
    return sums
