"""Analysis derivation — from an :class:`ExtractionContext` to the
:class:`AnalysisDerived` payload on :class:`CanonicalCompanyState`.

Phase 1.5.3 rewrite: consumes the as-reported structured schema
(``line_items`` with ``is_subtotal`` + ``section`` + verbatim
labels). Classification of each BS line into operating vs financial
happens **locally** based on:

- Labels (e.g. "Cash and cash equivalents" → financial asset, "Trade
  receivables" → operating asset).
- BS sections (``current_assets`` / ``non_current_assets`` / ...)
  to avoid crossing the boundary.

Three artefacts per fiscal period:

- :class:`InvestedCapital` — IC = Operating Assets − Operating Liabilities.
- :class:`NOPATBridge` — EBITDA − Operating Taxes → NOPAT →
  Financial Income − Financial Expense − Non-Operating Items →
  Reported NI.
- :class:`KeyRatios` — ROIC, ROE, margins, Net Debt / EBITDA,
  CapEx / Revenue.

Module dependencies:

- Module A's ``A.1`` adjustment carries the operating tax rate.
- Module B's ``B.2.*`` adjustments are informational (flow through
  the adjustments list; the NOPAT bridge anchors on IS fields).
- Module C's ``C.3`` adjustment is informational (FCFF uses it in
  Sprint 8+).
"""

from __future__ import annotations

import re
from decimal import Decimal

from portfolio_thesis_engine.extraction.base import ExtractionContext
from portfolio_thesis_engine.schemas.common import FiscalPeriod
from portfolio_thesis_engine.schemas.company import (
    AnalysisDerived,
    InvestedCapital,
    KeyRatios,
    NOPATBridge,
)
from portfolio_thesis_engine.schemas.raw_extraction import (
    BalanceSheetPeriod,
    CashFlowPeriod,
    IncomeStatementPeriod,
    LineItem,
)

# ----------------------------------------------------------------------
# Label patterns for local classification
# ----------------------------------------------------------------------
_REVENUE = re.compile(r"^revenue$|^total revenue$|^sales$|^turnover$",
                      re.IGNORECASE)
_COST_OF_SALES = re.compile(r"^cost of sales$|^cost of (revenue|goods sold)",
                            re.IGNORECASE)
_OPERATING_INCOME = re.compile(
    r"^operating (profit|income)$|profit from operations", re.IGNORECASE
)
_FINANCE_INCOME = re.compile(r"^finance income$|^interest income$", re.IGNORECASE)
_FINANCE_EXPENSE = re.compile(
    r"^finance (expense|cost)s?$|^interest expense", re.IGNORECASE
)
_DA = re.compile(r"^depreciation|amorti[sz]ation|^depreciation and amorti",
                 re.IGNORECASE)
_NET_INCOME = re.compile(
    r"^profit for the (year|period)$|^net (income|profit)$", re.IGNORECASE
)
_NON_OPERATING = re.compile(
    r"non[- ]operating|share of (profits?|losses?) of associate|"
    r"share of associates|discontinued operation",
    re.IGNORECASE,
)

# BS label patterns
_CASH = re.compile(r"cash (and cash equivalents|at bank|and deposits)",
                   re.IGNORECASE)
_SHORT_TERM_INV = re.compile(r"short[- ]term investment", re.IGNORECASE)
_INVESTMENTS = re.compile(
    r"^investments$|investments? in (associates|joint ventures|subsidiaries)",
    re.IGNORECASE,
)
_SHORT_TERM_DEBT = re.compile(
    r"short[- ]term (debt|borrowings?|loans?)|bank (loans?|overdraft).*current",
    re.IGNORECASE,
)
_LONG_TERM_DEBT = re.compile(
    r"long[- ]term (debt|borrowings?|loans?)|non[- ]current (debt|borrowings?)",
    re.IGNORECASE,
)
_LEASE_LIAB = re.compile(r"lease liabilit", re.IGNORECASE)
_TOTAL_EQUITY = re.compile(
    r"total equity|total shareholders'?\s?equity|equity attributable to",
    re.IGNORECASE,
)
_NCI = re.compile(
    r"non[- ]controlling interest|minority interest", re.IGNORECASE
)
_TOTAL_EQUITY_PARENT = re.compile(
    r"equity attributable to (owners|equity holders|shareholders)",
    re.IGNORECASE,
)

# CF
_CAPEX_CF = re.compile(
    r"purchas[ae] of (property|plant|equipment|intangib)|"
    r"capital expenditure|additions? to (property|ppe|intangib)",
    re.IGNORECASE,
)


def _safe_div(num: Decimal | None, den: Decimal | None) -> Decimal | None:
    if num is None or den is None or den == 0:
        return None
    return num / den


def _first_match(
    items: list[LineItem], pattern: re.Pattern[str]
) -> Decimal | None:
    for item in items:
        if item.is_subtotal:
            continue
        if pattern.search(item.label):
            return item.value
    return None


def _first_subtotal(
    items: list[LineItem], pattern: re.Pattern[str]
) -> Decimal | None:
    for item in items:
        if not item.is_subtotal:
            continue
        if pattern.search(item.label):
            return item.value
    return None


class AnalysisDeriver:
    """Single-period analysis derivation from a :class:`RawExtraction`."""

    def derive(self, context: ExtractionContext) -> AnalysisDerived:
        period = context.primary_period
        raw = context.raw_extraction

        ic = self._invested_capital(raw.primary_bs, period)
        bridge = self._nopat_bridge(raw.primary_is, context, period)
        ratios = self._key_ratios(
            raw.primary_is, raw.primary_cf, period, ic, bridge
        )
        return AnalysisDerived(
            invested_capital_by_period=[ic],
            nopat_bridge_by_period=[bridge],
            ratios_by_period=[ratios],
        )

    # ------------------------------------------------------------------
    # IC
    # ------------------------------------------------------------------
    def _invested_capital(
        self,
        bs: BalanceSheetPeriod | None,
        period: FiscalPeriod,
    ) -> InvestedCapital:
        if bs is None or not bs.line_items:
            return _empty_ic(period)

        operating_assets = Decimal("0")
        operating_liabilities = Decimal("0")
        financial_assets = Decimal("0")
        financial_liabilities = Decimal("0")
        equity_claims = Decimal("0")
        nci_claims = Decimal("0")
        equity_parent_seen = False

        for item in bs.line_items:
            if item.is_subtotal:
                continue
            if item.value is None:
                continue
            section = item.section or ""
            label = item.label

            if _CASH.search(label) or _SHORT_TERM_INV.search(label):
                financial_assets += item.value
                continue
            if _INVESTMENTS.search(label) and "associate" not in label.lower():
                financial_assets += item.value
                continue
            if (
                _SHORT_TERM_DEBT.search(label)
                or _LONG_TERM_DEBT.search(label)
                or _LEASE_LIAB.search(label)
            ):
                financial_liabilities += item.value
                continue
            if _NCI.search(label):
                nci_claims += item.value
                continue
            if section == "equity":
                equity_claims += item.value
                continue
            if section in ("current_assets", "non_current_assets"):
                operating_assets += item.value
                continue
            if section in ("current_liabilities", "non_current_liabilities"):
                operating_liabilities += item.value
                continue
            # Sections we don't walk (total_assets, total_liabilities):
            # already subtotals; skipped above.

        # Prefer "equity attributable to owners" subtotal when present.
        parent_subtotal = _first_subtotal(bs.line_items, _TOTAL_EQUITY_PARENT)
        if parent_subtotal is not None:
            equity_claims = parent_subtotal
            equity_parent_seen = True

        # If equity_claims still zero, fall back to total_equity minus NCI.
        if not equity_parent_seen and equity_claims == 0:
            total_equity = _first_subtotal(bs.line_items, _TOTAL_EQUITY)
            if total_equity is not None:
                equity_claims = total_equity - nci_claims

        invested = operating_assets - operating_liabilities
        residual = (
            invested
            + financial_assets
            - equity_claims
            - nci_claims
            - financial_liabilities
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
        self,
        is_data: IncomeStatementPeriod | None,
        context: ExtractionContext,
        period: FiscalPeriod,
    ) -> NOPATBridge:
        if is_data is None or not is_data.line_items:
            return NOPATBridge(
                period=period,
                ebitda=Decimal("0"),
                ebita=None,
                operating_taxes=Decimal("0"),
                nopat=Decimal("0"),
                financial_income=Decimal("0"),
                financial_expense=Decimal("0"),
                non_operating_items=Decimal("0"),
                reported_net_income=Decimal("0"),
            )

        op_income = (
            _first_subtotal(is_data.line_items, _OPERATING_INCOME)
            or _first_match(is_data.line_items, _OPERATING_INCOME)
            or Decimal("0")
        )
        d_and_a = _first_match(is_data.line_items, _DA)
        # EBITDA = Op Income + |D&A|; D&A is typically negative on the
        # IS so abs() yields the add-back.
        ebitda = op_income + abs(d_and_a) if d_and_a is not None else op_income
        ebita: Decimal | None = None

        anchor = ebita if ebita is not None else ebitda
        op_rate = self._operating_tax_rate_pct(context)
        operating_taxes = (
            anchor * op_rate / Decimal("100")
            if op_rate is not None
            else Decimal("0")
        )
        nopat = anchor - operating_taxes

        fin_income = _first_match(is_data.line_items, _FINANCE_INCOME) or Decimal("0")
        fin_expense_raw = _first_match(is_data.line_items, _FINANCE_EXPENSE)
        # Finance expenses typically negative — convert to positive.
        fin_expense = (
            abs(fin_expense_raw) if fin_expense_raw is not None else Decimal("0")
        )

        # Non-op: sum IS lines matching non-operating pattern.
        non_operating = Decimal("0")
        for item in is_data.line_items:
            if item.is_subtotal or item.value is None:
                continue
            if _NON_OPERATING.search(item.label):
                non_operating += item.value

        reported_ni = (
            _first_subtotal(is_data.line_items, _NET_INCOME)
            or _first_match(is_data.line_items, _NET_INCOME)
            or Decimal("0")
        )

        return NOPATBridge(
            period=period,
            ebitda=ebitda,
            ebita=ebita,
            operating_taxes=operating_taxes,
            nopat=nopat,
            financial_income=fin_income,
            financial_expense=fin_expense,
            non_operating_items=non_operating,
            reported_net_income=reported_ni,
        )

    def _operating_tax_rate_pct(
        self, context: ExtractionContext
    ) -> Decimal | None:
        for adj in context.adjustments:
            if adj.module == "A.1":
                return adj.amount
        return None

    # ------------------------------------------------------------------
    # Ratios
    # ------------------------------------------------------------------
    def _key_ratios(
        self,
        is_data: IncomeStatementPeriod | None,
        cf_data: CashFlowPeriod | None,
        period: FiscalPeriod,
        ic: InvestedCapital,
        bridge: NOPATBridge,
    ) -> KeyRatios:
        revenue = (
            _first_match(is_data.line_items, _REVENUE)
            if is_data is not None
            else None
        )
        op_income = (
            _first_subtotal(is_data.line_items, _OPERATING_INCOME)
            if is_data is not None
            else None
        )
        capex = (
            _first_match(cf_data.line_items, _CAPEX_CF)
            if cf_data is not None
            else None
        )
        ebitda = bridge.ebitda

        hundred = Decimal("100")
        roic = _safe_div(bridge.nopat * hundred, ic.invested_capital)
        roe = _safe_div(bridge.reported_net_income * hundred, ic.equity_claims)
        operating_margin = _safe_div(
            (op_income or Decimal("0")) * hundred, revenue
        )
        ebitda_margin = _safe_div(ebitda * hundred, revenue)
        net_debt = ic.financial_liabilities - ic.financial_assets
        net_debt_ebitda = _safe_div(net_debt, ebitda)
        capex_revenue = (
            _safe_div(abs(capex) * hundred, revenue) if capex else None
        )

        return KeyRatios(
            period=period,
            roic=roic,
            roe=roe,
            operating_margin=operating_margin,
            ebitda_margin=ebitda_margin,
            net_debt_ebitda=net_debt_ebitda,
            capex_revenue=capex_revenue,
        )


def _empty_ic(period: FiscalPeriod) -> InvestedCapital:
    return InvestedCapital(
        period=period,
        operating_assets=Decimal("0"),
        operating_liabilities=Decimal("0"),
        invested_capital=Decimal("0"),
        financial_assets=Decimal("0"),
        financial_liabilities=Decimal("0"),
        equity_claims=Decimal("0"),
        nci_claims=Decimal("0"),
        cross_check_residual=Decimal("0"),
    )
