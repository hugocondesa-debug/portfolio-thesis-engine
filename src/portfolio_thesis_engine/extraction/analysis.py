"""Analysis derivation — from an :class:`ExtractionContext` to the
:class:`AnalysisDerived` payload on :class:`CanonicalCompanyState`.

Produces three artefacts per fiscal period: :class:`InvestedCapital`
(IC = Operating Assets − Operating Liabilities), :class:`NOPATBridge`
(EBITA − Operating Taxes → NOPAT + Financial Income − Financial Expense
− Non-Operating Items → Reported Net Income) and :class:`KeyRatios`
(ROIC, ROE, margins, Net Debt / EBITDA, CapEx / Revenue).

Phase 1 ships single-period analysis only. Multi-period work
(`Capital Allocation`, CAGRs, DuPont, etc.) waits on Phase 2 — where
the extraction system starts producing multiple reclassified
statements per run.

The deriver is **deterministic**. It consumes:

- IS / BS / CF ``line_items`` produced by :mod:`section_extractor`
  Pass 2, categorised via the per-statement enums.
- Module A's ``A.1`` adjustment, which carries the operating tax rate.
- Module B's ``B.2.*`` adjustments, whose amounts are the non-operating
  items to subtract from operating income.
- Module C's ``C.3`` adjustment (lease additions — informational for
  this sprint; FCFF uses it in Sprint 8).

When a required input is missing, the corresponding field on
:class:`KeyRatios` lands as ``None`` rather than raising; the bridge
and IC are always produced (zero-filled when the section is absent).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from portfolio_thesis_engine.extraction.base import ExtractionContext
from portfolio_thesis_engine.schemas.common import FiscalPeriod
from portfolio_thesis_engine.schemas.company import (
    AnalysisDerived,
    InvestedCapital,
    KeyRatios,
    NOPATBridge,
)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _sum_by_category(line_items: list[dict[str, Any]], *categories: str) -> Decimal:
    """Sum ``value_current`` across line items whose category is in
    ``categories``. Missing items → 0."""
    total = Decimal("0")
    for item in line_items:
        if str(item.get("category", "")) in categories:
            amount = _to_decimal(item.get("value_current"))
            if amount is not None:
                total += amount
    return total


def _safe_div(num: Decimal | None, den: Decimal | None) -> Decimal | None:
    """Return ``num / den`` when both present and den ≠ 0, else ``None``."""
    if num is None or den is None or den == 0:
        return None
    return num / den


class AnalysisDeriver:
    """Single-period analysis derivation."""

    def derive(self, context: ExtractionContext) -> AnalysisDerived:
        period = context.primary_period
        ic = self._invested_capital(context, period)
        bridge = self._nopat_bridge(context, period)
        ratios = self._key_ratios(context, period, ic, bridge)
        return AnalysisDerived(
            invested_capital_by_period=[ic],
            nopat_bridge_by_period=[bridge],
            ratios_by_period=[ratios],
            # Phase 2 lands capital_allocation, dupont, etc.
        )

    # ------------------------------------------------------------------
    # IC
    # ------------------------------------------------------------------
    def _invested_capital(
        self, context: ExtractionContext, period: FiscalPeriod
    ) -> InvestedCapital:
        bs = context.find_section("balance_sheet")
        lines: list[dict[str, Any]] = (
            (bs.parsed_data or {}).get("line_items", []) if bs and bs.parsed_data else []
        )
        operating_assets = _sum_by_category(lines, "operating_assets", "intangibles")
        operating_liabilities = _sum_by_category(lines, "operating_liabilities")
        invested = operating_assets - operating_liabilities

        financial_assets = _sum_by_category(lines, "financial_assets", "cash")
        financial_liabilities = _sum_by_category(
            lines, "financial_liabilities", "lease_liabilities"
        )
        equity_claims = _sum_by_category(lines, "equity", "total_equity")
        nci_claims = _sum_by_category(lines, "nci")

        # Cross-check identity:
        # invested_capital + financial_assets
        #   = equity_claims + nci_claims + financial_liabilities
        # Residual should be ~0; surface any gap so downstream guardrails
        # can pick it up in Sprint 8.
        residual = (
            invested + financial_assets - equity_claims - nci_claims - financial_liabilities
        )

        return InvestedCapital(
            period=period,
            operating_assets=operating_assets,
            operating_liabilities=operating_liabilities,
            invested_capital=invested,
            financial_assets=financial_assets,
            financial_liabilities=financial_liabilities,
            equity_claims=equity_claims,
            nci_claims=nci_claims,
            cross_check_residual=residual,
        )

    # ------------------------------------------------------------------
    # NOPAT bridge
    # ------------------------------------------------------------------
    def _nopat_bridge(
        self, context: ExtractionContext, period: FiscalPeriod
    ) -> NOPATBridge:
        is_section = context.find_section("income_statement")
        lines: list[dict[str, Any]] = (
            (is_section.parsed_data or {}).get("line_items", [])
            if is_section and is_section.parsed_data
            else []
        )

        operating_income = _sum_by_category(lines, "operating_income")
        amortisation = _sum_by_category(lines, "d_and_a")
        # Approximation for Phase 1: EBITA ≈ Operating Income + |amortisation|.
        # When D&A is broken out separately below operating income we add
        # it back; when it's already inside operating_income the parser
        # doesn't emit a separate d_and_a line and EBITA == operating_income.
        ebita = operating_income + abs(amortisation) if amortisation else operating_income

        # Operating taxes — Module A.1 holds the rate.
        op_rate = self._operating_tax_rate_pct(context)
        operating_taxes = (ebita * op_rate / Decimal("100")) if op_rate is not None else Decimal("0")
        nopat = ebita - operating_taxes

        financial_income = _sum_by_category(lines, "finance_income")
        financial_expense = _sum_by_category(lines, "finance_expense")
        non_op_is = _sum_by_category(lines, "non_operating")

        # Non-operating items from Module B adjustments (B.2.*). Summed
        # into the same bucket so the bridge aggregates every source.
        non_op_b = sum(
            (adj.amount for adj in context.adjustments if adj.module.startswith("B.2")),
            start=Decimal("0"),
        )
        non_operating = non_op_is + non_op_b

        reported_ni = _sum_by_category(lines, "net_income")

        return NOPATBridge(
            period=period,
            ebita=ebita,
            operating_taxes=operating_taxes,
            nopat=nopat,
            financial_income=financial_income,
            financial_expense=financial_expense,
            non_operating_items=non_operating,
            reported_net_income=reported_ni,
        )

    def _operating_tax_rate_pct(self, context: ExtractionContext) -> Decimal | None:
        for adj in context.adjustments:
            if adj.module == "A.1":
                return adj.amount
        return None

    # ------------------------------------------------------------------
    # Ratios
    # ------------------------------------------------------------------
    def _key_ratios(
        self,
        context: ExtractionContext,
        period: FiscalPeriod,
        ic: InvestedCapital,
        bridge: NOPATBridge,
    ) -> KeyRatios:
        is_section = context.find_section("income_statement")
        cf_section = context.find_section("cash_flow")
        is_lines: list[dict[str, Any]] = (
            (is_section.parsed_data or {}).get("line_items", [])
            if is_section and is_section.parsed_data
            else []
        )
        cf_lines: list[dict[str, Any]] = (
            (cf_section.parsed_data or {}).get("line_items", [])
            if cf_section and cf_section.parsed_data
            else []
        )

        revenue = _sum_by_category(is_lines, "revenue")
        d_and_a = _sum_by_category(is_lines, "d_and_a")
        capex = _sum_by_category(cf_lines, "capex")
        ebitda = bridge.ebita + abs(d_and_a) if d_and_a else bridge.ebita

        hundred = Decimal("100")
        roic = _safe_div(bridge.nopat * hundred, ic.invested_capital)
        roe = _safe_div(bridge.reported_net_income * hundred, ic.equity_claims)
        operating_margin = _safe_div(
            _sum_by_category(is_lines, "operating_income") * hundred, revenue
        )
        ebitda_margin = _safe_div(ebitda * hundred, revenue)
        net_debt = ic.financial_liabilities - ic.financial_assets
        net_debt_ebitda = _safe_div(net_debt, ebitda)
        capex_revenue = _safe_div(abs(capex) * hundred, revenue) if capex else None

        return KeyRatios(
            period=period,
            roic=roic,
            roe=roe,
            operating_margin=operating_margin,
            ebitda_margin=ebitda_margin,
            net_debt_ebitda=net_debt_ebitda,
            capex_revenue=capex_revenue,
        )
