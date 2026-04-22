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
from typing import Any

from portfolio_thesis_engine.extraction.base import ExtractionContext
from portfolio_thesis_engine.schemas.decomposition import SubItem
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
    RawExtraction,
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
# Phase 1.5.9 — non-recurring items that sit *inside* operating income
# but shouldn't flow through a forward projection. Conservative: targets
# the clearly-non-recurring vocabulary IFRS filings use above EBIT.
_NON_RECURRING_OP = re.compile(
    r"^other gains?[ ,]?\s*(and losses?,?\s*)?net$|"
    r"^other (income|gains?)\s*/\s*(losses?|expenses?),?\s*net$|"
    r"^(government )?(grants?|subsid(y|ies))\b|"
    r"^gain on disposal|"
    r"^(impairment|reversal of impairment)\s+(gain|loss|charge)|"
    r"^fair value (gain|loss|remeasurement) on contingent|"
    r"^exceptional items?|"
    r"^restructuring (costs?|charges?|gains?)|"
    r"^one[- ]off|^one[- ]time|"
    r"^litigation (gain|settlement|charge)",
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
    r"purchas[ae]s? of (property|plant|equipment|intangib)|"
    r"capital expenditure|additions? to (property|ppe|intangib)",
    re.IGNORECASE,
)

# Phase 1.5.6 — D&A discovery from notes.
_PPE_NOTE_TITLE = re.compile(
    r"property,? plant|property and equipment|plant and equipment",
    re.IGNORECASE,
)
_INTANGIBLES_NOTE_TITLE = re.compile(r"intangible", re.IGNORECASE)
_DEPRECIATION_ROW = re.compile(r"^\s*depreciation charge\s*$", re.IGNORECASE)
_AMORTISATION_ROW = re.compile(r"^\s*amorti[sz]ation charge\s*$", re.IGNORECASE)


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
    """Single-period analysis derivation from a :class:`RawExtraction`.

    Phase 1.5.10: when ``decompositions`` is supplied, the sustainable
    operating income is computed from sub-item granularity instead of
    aggregate regex matches. Absent decompositions, the Phase 1.5.9
    regex fallback runs — backwards compat preserved.
    """

    def derive(
        self,
        context: ExtractionContext,
        decompositions: dict[str, Any] | None = None,
    ) -> AnalysisDerived:
        period = context.primary_period
        raw = context.raw_extraction

        ic = self._invested_capital(raw.primary_bs, period)
        bridge = self._nopat_bridge(
            raw.primary_is, context, period, decompositions=decompositions
        )
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
        bank_debt = Decimal("0")
        lease_liabs = Decimal("0")
        wc_current_assets = Decimal("0")
        wc_current_liabilities = Decimal("0")
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
            # Phase 1.5.9.1 — split bank debt from leases. Leases first
            # (their label may also contain "borrowings" in some filings).
            if _LEASE_LIAB.search(label):
                financial_liabilities += item.value
                lease_liabs += item.value
                continue
            if _SHORT_TERM_DEBT.search(label) or _LONG_TERM_DEBT.search(label):
                financial_liabilities += item.value
                bank_debt += item.value
                continue
            if _NCI.search(label):
                nci_claims += item.value
                continue
            if section == "equity":
                equity_claims += item.value
                continue
            if section in ("current_assets", "non_current_assets"):
                operating_assets += item.value
                if section == "current_assets":
                    wc_current_assets += item.value
                continue
            if section in ("current_liabilities", "non_current_liabilities"):
                operating_liabilities += item.value
                if section == "current_liabilities":
                    wc_current_liabilities += item.value
                continue
            # Sections we don't walk (total_assets, total_liabilities):
            # already subtotals; skipped above.

        # Operating working capital: current-section operating items only
        # (excludes PP&E, intangibles, goodwill, long-term provisions).
        # Feeds the DCF's per-year ΔWC projection.
        operating_wc = wc_current_assets - wc_current_liabilities

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
            bank_debt=bank_debt,
            lease_liabilities=lease_liabs,
            operating_working_capital=operating_wc,
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
        decompositions: dict[str, Any] | None = None,
    ) -> NOPATBridge:
        if is_data is None or not is_data.line_items:
            return NOPATBridge(
                period=period,
                ebitda=Decimal("0"),
                ebita=None,
                operating_income=Decimal("0"),
                operating_income_sustainable=None,
                non_recurring_operating_items=Decimal("0"),
                depreciation=Decimal("0"),
                amortisation=Decimal("0"),
                nopat_methodology="ebit_based_no_amort_detected",
                which_used_for_nopat="reported",
                operating_taxes=Decimal("0"),
                nopat=Decimal("0"),
                nopat_reported=Decimal("0"),
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

        # Phase 1.5.10 — prefer Module D decomposition when available,
        # but only for lines that would otherwise have been caught by
        # the Phase 1.5.9 non-recurring regex. Decomposing core lines
        # (Revenue, COGS, SG&A) into sub-items is fine for transparency
        # but those sub-items must NOT enter the sustainable-margin
        # adjustment — they're the run-rate profit, not candidates for
        # exclusion.
        #
        # Absent decompositions, fall back to the Phase 1.5.9 aggregate-
        # label regex (backwards compat).
        non_recurring = Decimal("0")
        non_recurring_labels: list[str] = []
        non_recurring_detail: list[SubItem] = []
        operational_adjustments_detail: list[SubItem] = []
        module_d_applied = False
        if decompositions:
            for item in is_data.line_items:
                if item.is_subtotal or item.value is None:
                    continue
                # Gate: parent line must be a non-recurring candidate.
                # This is the same gate the Phase 1.5.9 regex used;
                # keeps Revenue / COGS / etc. out of the adjustment.
                if not _NON_RECURRING_OP.search(item.label):
                    continue
                key = f"IS:{item.label}"
                decomp = decompositions.get(key)
                if decomp is None or not decomp.sub_items:
                    continue
                # Only trigger Module-D-based adjustment when at least
                # one sub-item is exclude / flag. If every sub-item is
                # include (e.g. decomposed "Government grants, net"
                # whose sub-items are all operational + recurring),
                # keep the full parent in OI.
                if not any(
                    s.action in ("exclude", "flag_for_review")
                    for s in decomp.sub_items
                ):
                    continue
                module_d_applied = True
                for sub in decomp.sub_items:
                    if sub.action in ("exclude", "flag_for_review"):
                        non_recurring += sub.value
                        non_recurring_labels.append(sub.label)
                        non_recurring_detail.append(sub)
                    else:
                        operational_adjustments_detail.append(sub)

        if not module_d_applied:
            non_recurring, non_recurring_labels = _sum_non_recurring_op(
                is_data.line_items
            )
            non_recurring_detail = []
            operational_adjustments_detail = []

        sustainable_oi: Decimal | None = None
        if non_recurring != 0:
            sustainable_oi = op_income - non_recurring
            context.estimates_log.append(
                "AnalysisDeriver: sustainable operating income = "
                f"{op_income} − {non_recurring} (non-recurring: "
                f"{', '.join(non_recurring_labels)}) = {sustainable_oi}."
            )

        # Phase 1.5.9 — split depreciation (PP&E rollforward) from
        # amortisation (intangibles rollforward). Fall back to combined
        # D&A when only one note is present.
        depreciation, amortisation = _split_da_from_notes(context.raw_extraction)
        # If the IS carries a single combined "Depreciation and
        # amortisation" line (some IFRS filers), it's routed to
        # depreciation as the primary non-cash add-back — amortisation
        # stays 0 and NOPAT falls back to the EBIT basis.
        combined_is_da = _first_match(is_data.line_items, _DA)
        if combined_is_da is not None and depreciation == 0 and amortisation == 0:
            depreciation = abs(combined_is_da)

        ebitda = op_income + depreciation + amortisation
        ebita: Decimal | None = (
            op_income + amortisation if amortisation != 0 else None
        )

        if depreciation == 0 and amortisation == 0:
            context.estimates_log.append(
                "AnalysisDeriver: D&A not discoverable from IS line_items "
                "or PP&E / intangibles notes. EBITDA falls back to "
                "Operating profit; NOPAT anchors on EBIT."
            )

        # NOPAT = EBITA × (1 − t). Amortisation add-back captures PPA /
        # intangibles amortisation as a real operating expense whose tax
        # shield is already inside EBITA. Depreciation is NOT added to
        # EBITA — it flows through FCFF as a non-cash add-back.
        op_rate = self._operating_tax_rate_pct(context)
        ebit_sustainable = (
            sustainable_oi if sustainable_oi is not None else op_income
        )
        if amortisation > 0:
            ebita_reported = op_income + amortisation
            ebita_sustainable = ebit_sustainable + amortisation
            nopat_methodology = "ebita_based"
        else:
            ebita_reported = op_income
            ebita_sustainable = ebit_sustainable
            nopat_methodology = "ebit_based_no_amort_detected"
            context.estimates_log.append(
                "AnalysisDeriver: amortisation not isolatable from "
                "intangibles notes; NOPAT falls back to EBIT basis."
            )
        # Phase 1.5.9.1 — NOPAT primary = sustainable basis so the
        # Year-0 display and ROIC agree with the forward projection
        # (which has always used sustainable margin). Reported NOPAT
        # tracked for reconciliation with accounting statements.
        which_used_for_nopat = (
            "sustainable" if sustainable_oi is not None else "reported"
        )
        op_rate_frac = (
            op_rate / Decimal("100") if op_rate is not None else Decimal("0")
        )
        nopat_primary_anchor = (
            ebita_sustainable if which_used_for_nopat == "sustainable"
            else ebita_reported
        )
        operating_taxes = nopat_primary_anchor * op_rate_frac
        nopat = nopat_primary_anchor - operating_taxes
        nopat_reported_value = ebita_reported - (ebita_reported * op_rate_frac)

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
            operating_income=op_income,
            operating_income_sustainable=sustainable_oi,
            non_recurring_operating_items=non_recurring,
            non_recurring_items_detail=non_recurring_detail,
            operational_adjustments_detail=operational_adjustments_detail,
            depreciation=depreciation,
            amortisation=amortisation,
            nopat_methodology=nopat_methodology,
            which_used_for_nopat=which_used_for_nopat,
            operating_taxes=operating_taxes,
            nopat=nopat,
            nopat_reported=nopat_reported_value,
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
        # Phase 1.5.9.1 — primary ROIC uses sustainable NOPAT (matches
        # the DCF's forward projection). ROIC_reported tracks the
        # reported basis for reconciliation with accounting statements.
        roic = _safe_div(bridge.nopat * hundred, ic.invested_capital)
        roic_reported: Decimal | None = None
        if bridge.nopat_reported is not None:
            roic_reported = _safe_div(
                bridge.nopat_reported * hundred, ic.invested_capital
            )
        roe = _safe_div(bridge.reported_net_income * hundred, ic.equity_claims)
        operating_margin = _safe_div(
            (op_income or Decimal("0")) * hundred, revenue
        )
        # Phase 1.5.9 — sustainable margin strips non-recurring items
        # from the numerator (see :class:`NOPATBridge`). Reported back to
        # the analyst so they can see both; DCF anchors on sustainable.
        sustainable_operating_margin: Decimal | None = None
        if bridge.operating_income_sustainable is not None:
            sustainable_operating_margin = _safe_div(
                bridge.operating_income_sustainable * hundred, revenue
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
            roic_reported=roic_reported,
            roe=roe,
            operating_margin=operating_margin,
            sustainable_operating_margin=sustainable_operating_margin,
            ebitda_margin=ebitda_margin,
            net_debt_ebitda=net_debt_ebitda,
            capex_revenue=capex_revenue,
        )


def construct_economic_bs_from_decomposition(
    canonical_state: Any,
    decompositions: dict[str, Any],
) -> Any:
    """Phase 1.5.10 stub — Phase 2 Sprint 2 will use BS decompositions
    to split operating from financing items at sub-item granularity
    (e.g. "Trade receivables" decomposed into customer-receivable vs
    related-party balances). Phase 1.5.10 keeps the current
    :class:`InvestedCapital` computation in the
    :class:`AnalysisDeriver._invested_capital` method.
    """
    _ = (canonical_state, decompositions)
    raise NotImplementedError(
        "Economic BS from decomposition: Phase 2 Sprint 2 (ModuleE.BS)."
    )


def _sum_non_recurring_op(
    items: list[LineItem],
) -> tuple[Decimal, list[str]]:
    """Phase 1.5.9 — identify non-recurring items that sit above operating
    profit on the IS and should be excluded from the run-rate margin the
    DCF projects forward.

    Matches labels against :data:`_NON_RECURRING_OP`. Subtotals are
    ignored (those are aggregates, not individual items). Returns the
    signed sum (typical: net gain → positive) plus the matched labels
    for the estimate log.
    """
    total = Decimal("0")
    matched: list[str] = []
    for item in items:
        if item.is_subtotal or item.value is None:
            continue
        if _NON_RECURRING_OP.search(item.label):
            total += item.value
            matched.append(item.label)
    return total, matched


def _split_da_from_notes(raw: RawExtraction) -> tuple[Decimal, Decimal]:
    """Phase 1.5.9 — split depreciation from amortisation using PP&E vs
    intangibles rollforward tables.

    Returns ``(depreciation, amortisation)``. Either component is
    ``Decimal(0)`` when the corresponding note isn't present. The EBITA-
    basis NOPAT calculation uses amortisation as an EBIT add-back;
    depreciation flows through FCFF separately.
    """
    primary_year_str = str(
        raw.primary_period.end_date.split("-")[0]
        if raw.primary_period.end_date
        else raw.metadata.fiscal_year or ""
    )
    depreciation = Decimal("0")
    amortisation = Decimal("0")

    for note in raw.notes:
        is_ppe = bool(_PPE_NOTE_TITLE.search(note.title))
        is_intangible = bool(_INTANGIBLES_NOTE_TITLE.search(note.title))
        if not (is_ppe or is_intangible):
            continue
        for table in note.tables:
            label = (table.table_label or "").lower()
            if primary_year_str and primary_year_str not in label:
                continue
            for row in table.rows:
                if not row:
                    continue
                row_label = str(row[0]) if row[0] is not None else ""
                if is_ppe:
                    if not _DEPRECIATION_ROW.search(row_label):
                        continue
                else:
                    if not _AMORTISATION_ROW.search(row_label):
                        continue
                numeric_cells = [c for c in row[1:] if isinstance(c, Decimal)]
                if not numeric_cells:
                    continue
                value = abs(numeric_cells[-1])
                if is_ppe:
                    depreciation += value
                else:
                    amortisation += value

    return depreciation, amortisation


def _sum_da_from_notes(raw: RawExtraction) -> Decimal | None:
    """Phase 1.5.6 back-compat — combined D+A total. Callers that need
    the D/A split should use :func:`_split_da_from_notes` instead."""
    d, a = _split_da_from_notes(raw)
    if d == 0 and a == 0:
        return None
    return d + a


def _empty_ic(period: FiscalPeriod) -> InvestedCapital:
    return InvestedCapital(
        period=period,
        operating_assets=Decimal("0"),
        operating_liabilities=Decimal("0"),
        invested_capital=Decimal("0"),
        financial_assets=Decimal("0"),
        financial_liabilities=Decimal("0"),
        bank_debt=Decimal("0"),
        lease_liabilities=Decimal("0"),
        operating_working_capital=Decimal("0"),
        equity_claims=Decimal("0"),
        nci_claims=Decimal("0"),
        cross_check_residual=Decimal("0"),
    )
