"""Phase 1.5 Sprint-2 bridge between :class:`RawExtraction` and the
:class:`ExtractionCoordinator` + modules built in Phase 1.

**DELETE IN SPRINT 3.** Once extraction modules consume
:class:`RawExtraction` directly (Sprint 3 refactor), this file and its
:class:`StructuredSection` / :class:`SectionExtractionResult` carrier
dataclasses go away.

The adapter translates the typed :class:`RawExtraction` schema into
the list-of-:class:`StructuredSection` shape the Phase 1 modules
expect, synthesising a ``parsed_data`` dict per section that matches
the Pass 2 LLM tool-use outputs Module A / B / C / AnalysisDeriver
were built against.

Three categories of translation:

- **IS / BS / CF** — field-by-field mapping from
  :class:`IncomeStatementPeriod` / :class:`BalanceSheetPeriod` /
  :class:`CashFlowPeriod` to a ``line_items`` list with categories
  matching the Phase 1 ``SECTION_TOOLS`` enums
  (``revenue`` / ``cost_of_sales`` / ``opex`` / ``d_and_a`` /
  ``operating_income`` / …; ``cash`` / ``operating_assets`` /
  ``financial_liabilities`` / …; ``cfo`` / ``cfi`` / ``capex`` / …).
- **Notes: taxes** — :class:`TaxNote` → ``notes_taxes`` parsed_data
  with ``effective_rate_pct`` / ``reconciling_items`` / etc.
  ``classification`` values (operational / non_operational / one_time /
  unknown) map to the Phase 1 ``category`` values
  (non_deductible / non_operating / prior_year_adjustment / other).
- **Notes: leases** — :class:`LeaseNote` → ``notes_leases`` parsed_data
  with ``lease_liability_movement`` + ``rou_assets_by_category``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from portfolio_thesis_engine.schemas.common import GuardrailStatus
from portfolio_thesis_engine.schemas.raw_extraction import (
    BalanceSheetPeriod,
    CashFlowPeriod,
    IncomeStatementPeriod,
    LeaseNote,
    RawExtraction,
    TaxNote,
    TaxReconciliationItem,
)


# ----------------------------------------------------------------------
# Bridge dataclasses (copied from the now-deleted section_extractor.base
# so Sprint 2 can delete the package without breaking the modules).
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class StructuredSection:
    """A section of a financial report with its parsed payload.

    Sprint 2 bridge type — Sprint 3 removes in favour of direct
    :class:`RawExtraction` access.
    """

    section_type: str
    title: str
    content: str
    parsed_data: dict[str, Any] | None = None
    page_range: tuple[int, int] | None = None
    fiscal_period: str | None = None
    confidence: float = 1.0
    extraction_method: str = "raw_extraction_adapter"


@dataclass(frozen=True)
class ValidationIssue:
    severity: str  # "FATAL" | "WARN" | "INFO"
    message: str
    section_type: str | None = None
    details: dict[str, Any] | None = None


@dataclass
class SectionExtractionResult:
    """Structured result of the section extractor — Sprint 2 bridge
    type; Sprint 3 removes this along with the adapter."""

    doc_id: str
    ticker: str
    fiscal_period: str
    sections: list[StructuredSection]
    unresolved: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)
    overall_status: GuardrailStatus = GuardrailStatus.PASS


# ----------------------------------------------------------------------
# IS field-to-category mapping
# ----------------------------------------------------------------------
# Each tuple: (RawExtraction field name, Phase-1 category, sign policy).
# Sign policy "as_is" emits the field's raw value; "absolute" coerces to
# |value| — used on d_and_a (Phase 1 stored negative, RawExtraction can
# go either way).
_IS_FIELD_MAP: tuple[tuple[str, str, str], ...] = (
    ("revenue", "revenue", "as_is"),
    ("cost_of_sales", "cost_of_sales", "as_is"),
    ("selling_marketing", "opex", "as_is"),
    ("general_administrative", "opex", "as_is"),
    ("selling_general_administrative", "opex", "as_is"),
    ("research_development", "opex", "as_is"),
    ("other_operating_expenses", "opex", "as_is"),
    ("depreciation_amortization", "d_and_a", "as_is"),
    ("operating_income", "operating_income", "as_is"),
    ("finance_income", "finance_income", "as_is"),
    ("finance_expenses", "finance_expense", "as_is"),
    ("share_of_associates", "non_operating", "as_is"),
    ("non_operating_income", "non_operating", "as_is"),
    ("net_income_from_discontinued", "non_operating", "as_is"),
    ("income_tax", "tax", "as_is"),
    ("net_income", "net_income", "as_is"),
)


# ----------------------------------------------------------------------
# BS field-to-category mapping
# ----------------------------------------------------------------------
_BS_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("cash_and_equivalents", "cash"),
    ("short_term_investments", "financial_assets"),
    ("accounts_receivable", "operating_assets"),
    ("inventory", "operating_assets"),
    ("current_assets_other", "operating_assets"),
    ("ppe_net", "operating_assets"),
    ("rou_assets", "operating_assets"),
    ("goodwill", "intangibles"),
    ("intangibles_other", "intangibles"),
    ("investments", "financial_assets"),
    ("deferred_tax_assets", "operating_assets"),
    ("non_current_assets_other", "operating_assets"),
    ("total_assets", "total_assets"),
    ("accounts_payable", "operating_liabilities"),
    ("short_term_debt", "financial_liabilities"),
    ("lease_liabilities_current", "lease_liabilities"),
    ("deferred_revenue_current", "operating_liabilities"),
    ("current_liabilities_other", "operating_liabilities"),
    ("long_term_debt", "financial_liabilities"),
    ("lease_liabilities_noncurrent", "lease_liabilities"),
    ("deferred_tax_liabilities", "operating_liabilities"),
    ("provisions", "operating_liabilities"),
    ("pension_obligations", "operating_liabilities"),
    ("non_current_liabilities_other", "operating_liabilities"),
    ("total_liabilities", "total_liabilities"),
    ("share_capital", "equity"),
    ("share_premium", "equity"),
    ("retained_earnings", "equity"),
    ("other_reserves", "equity"),
    ("treasury_shares", "equity"),
    ("non_controlling_interests", "nci"),
    ("total_equity", "total_equity"),
)


# ----------------------------------------------------------------------
# CF field-to-category mapping
# ----------------------------------------------------------------------
_CF_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("operating_cash_flow", "cfo"),
    ("capex", "capex"),
    ("acquisitions", "acquisitions"),
    ("investing_cash_flow", "cfi"),
    ("dividends_paid", "dividends"),
    ("debt_issuance", "debt_issuance"),
    ("debt_repayment", "debt_repayment"),
    ("share_repurchases", "buybacks"),
    ("financing_cash_flow", "cff"),
    ("fx_effect", "fx_effect"),
    ("net_change_in_cash", "net_change_in_cash"),
)


# ----------------------------------------------------------------------
# Tax classification → Phase 1 category
# ----------------------------------------------------------------------
_TAX_CLASSIFICATION_TO_CATEGORY: dict[str, str] = {
    "operational": "non_deductible",
    "non_operational": "non_operating",
    "one_time": "prior_year_adjustment",
    "unknown": "other",
}


# ----------------------------------------------------------------------
# Adapter
# ----------------------------------------------------------------------
def adapt_raw_extraction(
    raw: RawExtraction,
    doc_id: str | None = None,
) -> SectionExtractionResult:
    """Translate a :class:`RawExtraction` into the Phase 1
    :class:`SectionExtractionResult` shape the modules expect.

    ``doc_id`` defaults to ``f"{ticker}/raw_extraction"``. The
    resulting sections carry the primary period's data — modules read
    the primary period via ``find_section(section_type).parsed_data``.
    """
    primary = raw.primary_period
    period_label = primary.period
    ticker = raw.metadata.ticker
    sections: list[StructuredSection] = []

    # ── Income statement ────────────────────────────────────────
    is_data = raw.income_statement.get(period_label)
    if is_data is not None:
        sections.append(
            _make_section(
                "income_statement",
                title="Consolidated Income Statement",
                period_label=period_label,
                parsed_data=_is_parsed_data(is_data, raw),
            )
        )

    # ── Balance sheet ──────────────────────────────────────────
    bs_data = raw.balance_sheet.get(period_label)
    if bs_data is not None:
        sections.append(
            _make_section(
                "balance_sheet",
                title="Consolidated Balance Sheet",
                period_label=period_label,
                parsed_data=_bs_parsed_data(bs_data, raw),
            )
        )

    # ── Cash flow ──────────────────────────────────────────────
    cf_data = raw.cash_flow.get(period_label)
    if cf_data is not None:
        sections.append(
            _make_section(
                "cash_flow",
                title="Consolidated Cash Flow",
                period_label=period_label,
                parsed_data=_cf_parsed_data(cf_data, raw),
            )
        )

    # ── Notes: taxes ──────────────────────────────────────────
    if raw.notes.taxes is not None:
        sections.append(
            _make_section(
                "notes_taxes",
                title="Note — Income Taxes",
                period_label=period_label,
                parsed_data=_tax_parsed_data(raw.notes.taxes, is_data, period_label),
            )
        )

    # ── Notes: leases ─────────────────────────────────────────
    if raw.notes.leases is not None:
        sections.append(
            _make_section(
                "notes_leases",
                title="Note — Leases (IFRS 16)",
                period_label=period_label,
                parsed_data=_lease_parsed_data(raw.notes.leases, raw, period_label),
            )
        )

    return SectionExtractionResult(
        doc_id=doc_id or f"{ticker}/raw_extraction",
        ticker=ticker,
        fiscal_period=period_label,
        sections=sections,
    )


# ----------------------------------------------------------------------
# Section builders
# ----------------------------------------------------------------------
def _make_section(
    section_type: str,
    title: str,
    period_label: str,
    parsed_data: dict[str, Any],
) -> StructuredSection:
    return StructuredSection(
        section_type=section_type,
        title=title,
        content="",  # Sprint 3 will consume RawExtraction directly; no raw markdown available
        parsed_data=parsed_data,
        fiscal_period=period_label,
        extraction_method="raw_extraction_adapter",
    )


def _is_parsed_data(is_data: IncomeStatementPeriod, raw: RawExtraction) -> dict[str, Any]:
    line_items = _line_items_from_mapping(is_data, _IS_FIELD_MAP)
    # Extensions get ``category="other"``.
    for name, value in is_data.extensions.items():
        if value is None:
            continue
        line_items.append(
            {"label": name.replace("_", " ").title(), "value_current": value, "category": "other"}
        )
    return {
        "fiscal_period": raw.primary_period.period,
        "currency": raw.metadata.reporting_currency.value,
        "currency_unit": "units",  # parser already normalised
        "line_items": line_items,
    }


def _bs_parsed_data(bs_data: BalanceSheetPeriod, raw: RawExtraction) -> dict[str, Any]:
    line_items: list[dict[str, Any]] = []
    for field_name, category in _BS_FIELD_MAP:
        value = getattr(bs_data, field_name, None)
        if value is None:
            continue
        line_items.append(
            {
                "label": _field_label(field_name),
                "value_current": value,
                "category": category,
            }
        )
    for name, value in bs_data.extensions.items():
        if value is None:
            continue
        line_items.append(
            {"label": name.replace("_", " ").title(), "value_current": value, "category": "other"}
        )
    return {
        "as_of_date": _primary_end_date(raw),
        "currency": raw.metadata.reporting_currency.value,
        "currency_unit": "units",
        "line_items": line_items,
    }


def _cf_parsed_data(cf_data: CashFlowPeriod, raw: RawExtraction) -> dict[str, Any]:
    line_items: list[dict[str, Any]] = []
    for field_name, category in _CF_FIELD_MAP:
        value = getattr(cf_data, field_name, None)
        if value is None:
            continue
        line_items.append(
            {
                "label": _field_label(field_name),
                "value_current": value,
                "category": category,
            }
        )
    for name, value in cf_data.extensions.items():
        if value is None:
            continue
        line_items.append(
            {"label": name.replace("_", " ").title(), "value_current": value, "category": "other"}
        )
    return {
        "fiscal_period": raw.primary_period.period,
        "currency": raw.metadata.reporting_currency.value,
        "currency_unit": "units",
        "line_items": line_items,
    }


def _tax_parsed_data(
    tax_note: TaxNote,
    is_data: IncomeStatementPeriod | None,
    period_label: str,
) -> dict[str, Any]:
    """Synthesise the Phase 1 tax-section parsed_data layout.

    Derives ``profit_before_tax`` and ``reported_tax_expense`` from the
    IS when available so Module A can apply its materiality check.
    """
    reconciling: list[dict[str, Any]] = []
    for item in tax_note.reconciling_items:
        reconciling.append(
            {
                "label": item.description,
                "amount": item.amount,
                "category": _TAX_CLASSIFICATION_TO_CATEGORY[item.classification],
            }
        )

    parsed: dict[str, Any] = {
        "fiscal_period": period_label,
        "reconciling_items": reconciling,
    }
    if tax_note.effective_tax_rate_percent is not None:
        parsed["effective_rate_pct"] = tax_note.effective_tax_rate_percent
    if tax_note.statutory_rate_percent is not None:
        parsed["statutory_rate_pct"] = tax_note.statutory_rate_percent

    if is_data is not None:
        if is_data.income_tax is not None:
            parsed["reported_tax_expense"] = abs(is_data.income_tax)
        if is_data.income_before_tax is not None:
            parsed["profit_before_tax"] = is_data.income_before_tax
        if (
            tax_note.statutory_rate_percent is not None
            and is_data.income_before_tax is not None
        ):
            # statutory_tax = PBT × statutory_rate/100
            parsed["statutory_tax"] = (
                is_data.income_before_tax
                * tax_note.statutory_rate_percent
                / Decimal("100")
            )
    return parsed


def _lease_parsed_data(
    lease_note: LeaseNote,
    raw: RawExtraction,
    period_label: str,
) -> dict[str, Any]:
    """Synthesise the Phase 1 lease-section parsed_data layout.

    ``lease_liability_movement`` carries the Module C inputs; ROU
    assets are not broken down by category in the new schema so we
    pass a single aggregate row when ``rou_assets`` is populated on
    the BS.
    """
    movement: dict[str, Any] = {}
    if lease_note.lease_liabilities_opening is not None:
        movement["opening_balance"] = lease_note.lease_liabilities_opening
    if lease_note.lease_liabilities_closing is not None:
        movement["closing_balance"] = lease_note.lease_liabilities_closing
    if lease_note.rou_assets_additions is not None:
        movement["additions"] = lease_note.rou_assets_additions
    if lease_note.rou_assets_depreciation is not None:
        movement["depreciation_of_rou"] = lease_note.rou_assets_depreciation
    if lease_note.lease_interest_expense is not None:
        movement["interest_expense"] = lease_note.lease_interest_expense
    if lease_note.lease_principal_payments is not None:
        movement["principal_payments"] = lease_note.lease_principal_payments

    rou_by_category: list[dict[str, Any]] = []
    bs = raw.balance_sheet.get(period_label)
    if bs is not None and bs.rou_assets is not None:
        rou_by_category.append(
            {"category": "All ROU assets", "value_current": bs.rou_assets}
        )

    return {
        "fiscal_period": period_label,
        "currency": raw.metadata.reporting_currency.value,
        "currency_unit": "units",
        "lease_liability_movement": movement,
        "rou_assets_by_category": rou_by_category,
    }


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _line_items_from_mapping(
    period_data: Any,
    mapping: tuple[tuple[str, str, str], ...],
) -> list[dict[str, Any]]:
    """Apply a ``(field, category, sign_policy)`` mapping, skipping
    None values."""
    out: list[dict[str, Any]] = []
    for field_name, category, sign_policy in mapping:
        value = getattr(period_data, field_name, None)
        if value is None:
            continue
        out.append(
            {
                "label": _field_label(field_name),
                "value_current": abs(value) if sign_policy == "absolute" else value,
                "category": category,
            }
        )
    return out


def _field_label(field_name: str) -> str:
    """Convert ``ppe_net`` → ``"Ppe Net"`` for display purposes.

    Phase-1 modules are category-driven and don't rely on label
    formatting; the conversion is purely cosmetic. The Net Income
    guardrail specifically looks for a lowercase ``"net income"``
    label — we keep that as the canonical exception.
    """
    if field_name == "net_income":
        return "Net income"
    if field_name == "operating_income":
        return "Operating income"
    if field_name == "total_assets":
        return "Total assets"
    if field_name == "total_liabilities":
        return "Total liabilities"
    if field_name == "total_equity":
        return "Total equity"
    return field_name.replace("_", " ").title()


def _primary_end_date(raw: RawExtraction) -> str:
    return raw.primary_period.end_date


# Avoid ruff F401 on the transitional import by re-exporting.
__all__ = [
    "StructuredSection",
    "ValidationIssue",
    "SectionExtractionResult",
    "adapt_raw_extraction",
]

# Keep the name TaxReconciliationItem alive so editors index it —
# the mapping table above references the classification values that
# this type enforces at the schema level.
_ = TaxReconciliationItem
