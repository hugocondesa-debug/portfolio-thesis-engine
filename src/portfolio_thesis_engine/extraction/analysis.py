"""Analysis derivation — from an :class:`ExtractionContext` to the
:class:`AnalysisDerived` payload on :class:`CanonicalCompanyState`.

Phase 1.5 / Sprint 3 rewrite: consumes :class:`RawExtraction` directly.
Every value is a typed ``Decimal | None`` field on
:class:`IncomeStatementPeriod` / :class:`BalanceSheetPeriod` /
:class:`CashFlowPeriod` — no more ``line_items`` scans or category
enum lookups.

Three artefacts per fiscal period:

- :class:`InvestedCapital` — IC = Operating Assets − Operating Liabilities.
- :class:`NOPATBridge` — EBITDA − Operating Taxes → NOPAT + Financial
  Income − Financial Expense − Non-Operating Items → Reported NI.
- :class:`KeyRatios` — ROIC, ROE, margins, Net Debt / EBITDA, CapEx / Revenue.

Phase 1 ships single-period analysis. Multi-period work (capital
allocation, CAGRs, DuPont) waits on Phase 2.

Module dependencies:

- Module A's ``A.1`` adjustment carries the operating tax rate.
- Module B's ``B.2.*`` adjustments' amounts sum into non-op items.
- Module C's ``C.3`` adjustment is informational (FCFF uses it in
  Sprint 8+).
"""

from __future__ import annotations

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
)


def _z(value: Decimal | None) -> Decimal:
    """Return ``value`` or ``Decimal(0)`` for summing across None fields."""
    return value if value is not None else Decimal("0")


def _safe_div(num: Decimal | None, den: Decimal | None) -> Decimal | None:
    """Return ``num / den`` when both present and den ≠ 0, else ``None``."""
    if num is None or den is None or den == 0:
        return None
    return num / den


class AnalysisDeriver:
    """Single-period analysis derivation from a :class:`RawExtraction`."""

    def derive(self, context: ExtractionContext) -> AnalysisDerived:
        period = context.primary_period
        raw = context.raw_extraction
        is_data = raw.primary_is
        bs_data = raw.primary_bs
        cf_data = raw.primary_cf

        ic = self._invested_capital(bs_data, period)
        bridge = self._nopat_bridge(is_data, context, period)
        ratios = self._key_ratios(is_data, cf_data, period, ic, bridge)
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
        if bs is None:
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

        operating_assets = (
            _z(bs.accounts_receivable)
            + _z(bs.inventory)
            + _z(bs.current_assets_other)
            + _z(bs.ppe_net)
            + _z(bs.rou_assets)
            + _z(bs.goodwill)
            + _z(bs.intangibles_other)
            + _z(bs.deferred_tax_assets)
            + _z(bs.non_current_assets_other)
        )
        operating_liabilities = (
            _z(bs.accounts_payable)
            + _z(bs.deferred_revenue_current)
            + _z(bs.current_liabilities_other)
            + _z(bs.deferred_tax_liabilities)
            + _z(bs.provisions)
            + _z(bs.pension_obligations)
            + _z(bs.non_current_liabilities_other)
        )
        invested = operating_assets - operating_liabilities

        financial_assets = (
            _z(bs.cash_and_equivalents)
            + _z(bs.short_term_investments)
            + _z(bs.investments)
        )
        financial_liabilities = (
            _z(bs.short_term_debt)
            + _z(bs.long_term_debt)
            + _z(bs.lease_liabilities_current)
            + _z(bs.lease_liabilities_noncurrent)
        )
        equity_claims = _z(bs.total_equity_parent)
        # Fall back to total_equity minus NCI if total_equity_parent absent.
        if equity_claims == 0 and bs.total_equity is not None:
            equity_claims = _z(bs.total_equity) - _z(bs.non_controlling_interests)
        nci_claims = _z(bs.non_controlling_interests)

        # Cross-check identity:
        # IC + financial_assets = equity + NCI + financial_liabilities
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
        if is_data is None:
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

        operating_income = _z(is_data.operating_income)
        da = is_data.depreciation_amortization
        # EBITDA = Op Income + |D&A|. Raw schema's D&A is typically
        # positive or negative depending on extractor style; take abs.
        ebitda = (
            operating_income + abs(da) if da is not None else operating_income
        )
        # Phase 1 raw schema aggregates D+A; EBITA stays None until a
        # future schema split (same policy as Phase 1).
        ebita: Decimal | None = None

        anchor = ebita if ebita is not None else ebitda
        op_rate = self._operating_tax_rate_pct(context)
        operating_taxes = (
            anchor * op_rate / Decimal("100")
            if op_rate is not None
            else Decimal("0")
        )
        nopat = anchor - operating_taxes

        financial_income = _z(is_data.finance_income)
        # finance_expenses on the raw schema is typically negative; flip
        # to a positive "expense" value for the bridge.
        financial_expense = abs(is_data.finance_expenses) if is_data.finance_expenses is not None else Decimal("0")

        # Non-op items reconciling NOPAT to Reported NI come off the IS
        # directly. Module B adjustments (notes-sourced items like
        # goodwill impairment / restructuring provisions) travel in the
        # adjustments list for downstream consumers; the NOPAT bridge
        # keeps a clean IS-anchored view.
        non_operating = (
            _z(is_data.non_operating_income)
            + _z(is_data.share_of_associates)
            + _z(is_data.net_income_from_discontinued)
        )

        reported_ni = _z(is_data.net_income)

        return NOPATBridge(
            period=period,
            ebitda=ebitda,
            ebita=ebita,
            operating_taxes=operating_taxes,
            nopat=nopat,
            financial_income=financial_income,
            financial_expense=financial_expense,
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
        revenue = is_data.revenue if is_data else None
        op_income = is_data.operating_income if is_data else None
        capex = cf_data.capex if cf_data else None
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
