"""Phase 2 Sprint 2A — :class:`EconomicBSBuilder`.

Reads an :class:`InvestedCapital` (computed by the Phase-1
AnalysisDeriver) plus the reclassified balance sheet line items for a
given period, emits an :class:`EconomicBalanceSheet`. IFRS 16 leases
are treated as OPERATING (ROU + lease liabilities inside invested
capital, not in net financial position).
"""

from __future__ import annotations

import re
from decimal import Decimal

from portfolio_thesis_engine.schemas.company import (
    CanonicalCompanyState,
    InvestedCapital,
)
from portfolio_thesis_engine.schemas.economic_bs import EconomicBalanceSheet


_PPE_LABEL = re.compile(r"property,?\s*plant\s*(and\s*)?equipment", re.IGNORECASE)
_ROU_LABEL = re.compile(r"right[- ]of[- ]use", re.IGNORECASE)
_INTANGIBLE_LABEL = re.compile(r"intangible", re.IGNORECASE)
_GOODWILL_LABEL = re.compile(r"goodwill", re.IGNORECASE)
_AR_LABEL = re.compile(
    r"trade (and other )?receivable|accounts receivable", re.IGNORECASE
)
_INVENTORY_LABEL = re.compile(r"inventor|stock\s", re.IGNORECASE)
_AP_LABEL = re.compile(
    r"trade (and other )?payable|accounts payable", re.IGNORECASE
)
_LEASE_LIAB_LABEL = re.compile(r"lease liabilit", re.IGNORECASE)
_ST_DEBT_LABEL = re.compile(
    r"short[- ]term (debt|borrowings?|loans?)|bank (loans?|overdraft).*current",
    re.IGNORECASE,
)
_LT_DEBT_LABEL = re.compile(
    r"long[- ]term (debt|borrowings?|loans?)|non[- ]current (debt|borrowings?)",
    re.IGNORECASE,
)
_EQUITY_PARENT_LABEL = re.compile(
    r"equity attributable to (owners|equity holders|shareholders)",
    re.IGNORECASE,
)
_NCI_LABEL = re.compile(
    r"non[- ]controlling interest|minority interest", re.IGNORECASE
)
_ASSOCIATE_LABEL = re.compile(
    r"investments? in (associates|joint ventures|subsidiaries)",
    re.IGNORECASE,
)
_INVESTMENT_PROPERTY_LABEL = re.compile(
    r"investment property", re.IGNORECASE
)
_CASH_LABEL = re.compile(r"cash and cash equivalent|restricted cash", re.IGNORECASE)


class EconomicBSBuilder:
    """Translate Phase-1 canonical BS + InvestedCapital into the Phase-2
    economic view.

    Phase 2 Sprint 2A.1 — the primary period gets the full economic
    view (including NFP anchored on ``InvestedCapital.financial_assets``
    and the reported IC + cross-check residual). Comparative periods
    fall back to a **BS-only** view: PPE, ROU, goodwill, working
    capital, and a raw cash/debt split from the BS line list. The
    ``invested_capital`` / ``cross_check_residual`` fields stay ``None``
    for comparatives because Module D / AnalysisDeriver only run on the
    primary period.
    """

    def build(
        self,
        canonical_state: CanonicalCompanyState,
        period_label: str | None = None,
    ) -> EconomicBalanceSheet | None:
        """Build an EconomicBalanceSheet for the requested period. When
        ``period_label`` is ``None``, targets the primary period. Returns
        ``None`` when the canonical state has no balance sheet for the
        requested period."""
        rs = _find_reclassified_statement(canonical_state, period_label)
        if rs is None or not rs.balance_sheet:
            return None
        primary_label = (
            canonical_state.reclassified_statements[0].period.label
            if canonical_state.reclassified_statements
            else None
        )
        is_primary = period_label is None or period_label == primary_label
        ic: InvestedCapital | None = None
        if is_primary and canonical_state.analysis.invested_capital_by_period:
            ic = canonical_state.analysis.invested_capital_by_period[0]

        bs_lines = rs.balance_sheet

        # ── Operating items ──────────────────────────────────────
        ppe_net = _sum_matching(bs_lines, _PPE_LABEL)
        rou_assets = _sum_matching(bs_lines, _ROU_LABEL)
        goodwill = _sum_matching(bs_lines, _GOODWILL_LABEL)
        # Sprint 2B Part B — only subtract goodwill from the intangibles
        # total when the intangibles regex actually captured the
        # goodwill line (e.g. a combined "Intangible assets including
        # goodwill" subtotal). When "Goodwill" and "Intangible assets"
        # are separate rows the regex ``r"intangible"`` skips goodwill,
        # so subtracting would drive operating_intangibles negative.
        intangibles_all = _sum_matching(
            bs_lines, _INTANGIBLE_LABEL, exclude_pattern=_GOODWILL_LABEL
        )
        operating_intangibles = intangibles_all
        accounts_receivable = _sum_matching(bs_lines, _AR_LABEL)
        inventory = _sum_matching(bs_lines, _INVENTORY_LABEL)
        accounts_payable = _sum_matching(bs_lines, _AP_LABEL)

        working_capital = None
        wc_components = (accounts_receivable, inventory, accounts_payable)
        if any(v is not None for v in wc_components):
            working_capital = (
                (accounts_receivable or Decimal("0"))
                + (inventory or Decimal("0"))
                - (accounts_payable or Decimal("0"))
            )

        # ── Financial items ──────────────────────────────────────
        lease_liabilities = _sum_matching(bs_lines, _LEASE_LIAB_LABEL)
        short_term_debt = _sum_matching(bs_lines, _ST_DEBT_LABEL)
        long_term_debt = _sum_matching(bs_lines, _LT_DEBT_LABEL)
        financial_debt = _combine(short_term_debt, long_term_debt)
        # Phase 2 Sprint 2A: leases OPERATING → NFP = cash − financial_debt
        # (excludes lease_liabilities). Primary reads cash from the
        # InvestedCapital block; comparatives fall back to the BS line.
        if ic is not None:
            cash = ic.financial_assets
        else:
            cash = _sum_matching(bs_lines, _CASH_LABEL)
        nfp = None
        if cash is not None and financial_debt is not None:
            nfp = cash - financial_debt

        # ── Non-operating ────────────────────────────────────────
        associates_jvs = _sum_matching(bs_lines, _ASSOCIATE_LABEL)
        investment_property = _sum_matching(
            bs_lines, _INVESTMENT_PROPERTY_LABEL
        )

        # ── Equity ───────────────────────────────────────────────
        equity_parent = _sum_matching(bs_lines, _EQUITY_PARENT_LABEL, subtotal_ok=True)
        nci = _sum_matching(bs_lines, _NCI_LABEL)

        invested_capital = ic.invested_capital if ic is not None else None
        equity_claims = ic.equity_claims if ic is not None else None
        nci_claims = ic.nci_claims if ic is not None else None
        cross_check = ic.cross_check_residual if ic is not None else None

        # Phase 2 Sprint 2B Polish 1 — comparatives have no IC block,
        # but the operating-side aggregates reconstruct IC via the
        # identity ``IC = Σ operating assets − operating liabilities``.
        # Working capital (AR + inventory − AP) already encodes the
        # current-asset / current-liability netting; the non-current
        # side is PPE + ROU + goodwill + operating_intangibles. Leave
        # ``cross_check_residual = None`` since we can't reconcile
        # against financial-side claims here.
        if invested_capital is None:
            invested_capital = _combine(
                ppe_net,
                rou_assets,
                goodwill,
                operating_intangibles,
                working_capital,
                associates_jvs,
                investment_property,
            )

        total_equity_value: Decimal | None
        if equity_parent is not None or equity_claims is not None:
            total_equity_value = (equity_parent or equity_claims or Decimal("0")) + (
                nci or nci_claims or Decimal("0")
            )
        else:
            total_equity_value = None

        return EconomicBalanceSheet(
            period=period_label or rs.period.label,
            currency=canonical_state.identity.reporting_currency.value,
            operating_ppe_net=ppe_net,
            rou_assets=rou_assets,
            operating_intangibles=operating_intangibles,
            goodwill=goodwill,
            accounts_receivable=accounts_receivable,
            inventory=inventory,
            accounts_payable=accounts_payable,
            operating_provisions=None,  # Phase 2 Sprint 2B
            operating_deferred_tax_net=None,  # Phase 2 Sprint 2B
            working_capital=working_capital,
            invested_capital=invested_capital,
            cash_and_equivalents=cash,
            short_term_investments=None,
            financial_debt=financial_debt,
            lease_liabilities=lease_liabilities,
            net_financial_position=nfp,
            equity_investments=None,
            associates_jvs=associates_jvs,
            investment_property=investment_property,
            non_operating_provisions=None,
            equity_parent=equity_parent if equity_parent is not None else equity_claims,
            nci=nci if nci is not None else nci_claims,
            total_equity=total_equity_value,
            cross_check_residual=cross_check,
        )


def _find_reclassified_statement(
    state: CanonicalCompanyState, period_label: str | None
) -> object | None:
    if not state.reclassified_statements:
        return None
    if period_label is None:
        return state.reclassified_statements[0]
    for rs in state.reclassified_statements:
        if rs.period.label == period_label:
            return rs
    return None


def _sum_matching(
    lines: list,
    pattern: re.Pattern[str],
    subtotal_ok: bool = False,
    exclude_pattern: re.Pattern[str] | None = None,
) -> Decimal | None:
    """Sum BS line values whose label matches ``pattern``. When
    ``exclude_pattern`` is provided, any line that also matches it is
    skipped — lets the intangibles aggregator exclude goodwill rows."""
    total: Decimal | None = None
    for line in lines:
        if not subtotal_ok and getattr(line, "is_adjusted", False):
            continue
        if not pattern.search(line.label):
            continue
        if exclude_pattern is not None and exclude_pattern.search(line.label):
            continue
        value = line.value
        if value is None:
            continue
        total = value if total is None else total + value
    return total


def _combine(*values: Decimal | None) -> Decimal | None:
    non_null = [v for v in values if v is not None]
    if not non_null:
        return None
    total = Decimal("0")
    for v in non_null:
        total += v
    return total


__all__ = ["EconomicBSBuilder"]
