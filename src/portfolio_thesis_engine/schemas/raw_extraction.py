"""Raw extraction — human/Claude.ai boundary for numerical data.

:class:`RawExtraction` is the source of truth for every numerical
value consumed by the pipeline. It's produced **outside the app** by
Hugo + Claude.ai from the actual annual + interim reports, with line-
by-line human validation, then saved as YAML under
``data_inputs/{ticker}/raw_extraction.yaml``.

Phase 1 originally tried to derive these values with an in-app
LLM-driven section extractor; that hallucinated on 300+ page reports.
The Phase 1.5 pivot moves extraction outside the app, keeping only
the deterministic reclassification + valuation + ficha stages inside.

Design guarantees:

- **Every numerical field is strictly typed** as :class:`Decimal`
  (never ``float``) so YAML round-trip preserves precision.
- **Every statement line is ``Decimal | None``** so partial reports
  (no cash-flow statement disclosed, say) parse cleanly — the
  guardrails downstream flag missing values as WARN, not the schema
  itself.
- **Fiscal periods are keyed by label** (``"FY2024"``, ``"H1 2025"``).
  The primary period flag picks which one the extraction engine
  uses; :meth:`validate_completeness` enforces that IS + BS exist
  for the primary period (CF is optional — not every company files
  a mid-year CF statement).
- **Extensions buckets** on every statement + Notes for per-company
  lines not in the canonical catalogue. Keeps the schema
  sector-agnostic without cluttering the main fields.
- **``extra="forbid"`` via :class:`BaseSchema`** catches typos in
  field names at parse time instead of silently dropping them.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Literal

from pydantic import Field, model_validator

from portfolio_thesis_engine.schemas.base import BaseSchema
from portfolio_thesis_engine.schemas.common import (
    Currency,
    ISODate,
    Ticker,
)

UnitScale = Literal["units", "thousands", "millions"]
TaxItemClassification = Literal[
    "operational",
    "non_operational",
    "one_time",
    "unknown",
]
ProvisionClassification = Literal[
    "operating",
    "non_operating",
    "restructuring",
    "impairment",
    "other",
]


# ----------------------------------------------------------------------
# Fiscal period descriptor
# ----------------------------------------------------------------------
class FiscalPeriodData(BaseSchema):
    """One row in the ``fiscal_periods`` list.

    ``period`` is the label used to key the IS/BS/CF dicts; ``end_date``
    is the last calendar day of the period (YYYY-MM-DD). ``is_primary``
    marks the period that drives valuation — exactly one should be
    primary in a well-formed extraction, but the top-level validator
    tolerates 0-or-1 and defaults to the first entry when none flagged.
    """

    period: str = Field(min_length=1)
    end_date: ISODate
    is_primary: bool = False


# ----------------------------------------------------------------------
# Statements — lenient (every line Decimal | None)
# ----------------------------------------------------------------------
class IncomeStatementPeriod(BaseSchema):
    """Income statement for one fiscal period.

    All lines optional. ``extensions`` captures non-standard lines
    (e.g. ``share_of_associates_profit``) without needing schema edits.
    """

    revenue: Decimal | None = None
    cost_of_sales: Decimal | None = None
    gross_profit: Decimal | None = None
    selling_marketing: Decimal | None = None
    general_administrative: Decimal | None = None
    operating_expenses_other: Decimal | None = None
    operating_income: Decimal | None = None
    depreciation_amortization: Decimal | None = None
    finance_income: Decimal | None = None
    finance_expenses: Decimal | None = None
    non_operating_income: Decimal | None = None
    income_before_tax: Decimal | None = None
    income_tax: Decimal | None = None
    net_income: Decimal | None = None
    extensions: dict[str, Decimal] = Field(default_factory=dict)


class BalanceSheetPeriod(BaseSchema):
    """Balance sheet for one fiscal period.

    Grouped as current/non-current assets, current/non-current
    liabilities, equity. Each sub-group has an ``_other`` catchall plus
    a subtotal line (``total_current_assets``, etc.). Extraction YAML
    can supply the subtotals directly or leave them ``None`` and the
    guardrails will back them out.
    """

    # ── Assets ────────────────────────────────────────────────
    cash_and_equivalents: Decimal | None = None
    accounts_receivable: Decimal | None = None
    inventory: Decimal | None = None
    current_assets_other: Decimal | None = None
    total_current_assets: Decimal | None = None
    ppe_net: Decimal | None = None
    rou_assets: Decimal | None = None
    goodwill: Decimal | None = None
    intangibles_other: Decimal | None = None
    investments: Decimal | None = None
    deferred_tax_assets: Decimal | None = None
    non_current_assets_other: Decimal | None = None
    total_non_current_assets: Decimal | None = None
    total_assets: Decimal | None = None
    # ── Liabilities ──────────────────────────────────────────
    accounts_payable: Decimal | None = None
    current_debt: Decimal | None = None
    lease_liabilities_current: Decimal | None = None
    current_liabilities_other: Decimal | None = None
    total_current_liabilities: Decimal | None = None
    long_term_debt: Decimal | None = None
    lease_liabilities_noncurrent: Decimal | None = None
    deferred_tax_liabilities: Decimal | None = None
    provisions: Decimal | None = None
    non_current_liabilities_other: Decimal | None = None
    total_non_current_liabilities: Decimal | None = None
    total_liabilities: Decimal | None = None
    # ── Equity ───────────────────────────────────────────────
    share_capital: Decimal | None = None
    retained_earnings: Decimal | None = None
    other_reserves: Decimal | None = None
    total_equity: Decimal | None = None
    non_controlling_interests: Decimal | None = None

    extensions: dict[str, Decimal] = Field(default_factory=dict)


class CashFlowPeriod(BaseSchema):
    """Cash flow for one fiscal period."""

    operating_cash_flow: Decimal | None = None
    capex: Decimal | None = None
    investments_acquisitions: Decimal | None = None
    investments_other: Decimal | None = None
    investing_cash_flow: Decimal | None = None
    dividends_paid: Decimal | None = None
    debt_issuance: Decimal | None = None
    debt_repayment: Decimal | None = None
    share_repurchases: Decimal | None = None
    financing_cash_flow: Decimal | None = None
    fx_effect: Decimal | None = None
    net_change_in_cash: Decimal | None = None
    extensions: dict[str, Decimal] = Field(default_factory=dict)


# ----------------------------------------------------------------------
# Notes — tax, leases, provisions
# ----------------------------------------------------------------------
class TaxReconciliationItem(BaseSchema):
    """One row in the statutory→effective tax reconciliation."""

    description: str = Field(min_length=1)
    amount: Decimal
    classification: TaxItemClassification = "unknown"


class TaxNote(BaseSchema):
    """Tax-note fields consumed by Module A."""

    effective_tax_rate_percent: Decimal | None = None
    statutory_rate_percent: Decimal | None = None
    reconciling_items: list[TaxReconciliationItem] = Field(default_factory=list)


class LeaseNote(BaseSchema):
    """IFRS 16 lease disclosure consumed by Module C."""

    rou_assets_opening: Decimal | None = None
    rou_assets_closing: Decimal | None = None
    rou_assets_additions: Decimal | None = None
    rou_assets_depreciation: Decimal | None = None
    lease_liabilities_total: Decimal | None = None
    lease_liabilities_opening: Decimal | None = None
    lease_liabilities_closing: Decimal | None = None
    lease_interest_expense: Decimal | None = None
    lease_principal_payments: Decimal | None = None


class ProvisionItem(BaseSchema):
    """One row of the provisions note. Module B classifies these."""

    description: str = Field(min_length=1)
    amount: Decimal
    classification: ProvisionClassification = "other"


class Notes(BaseSchema):
    """All note-level disclosures the pipeline consumes.

    ``extensions`` is a catchall for notes the Phase 1 pipeline
    doesn't consume (goodwill impairment breakout, SBC, pensions,
    etc) — preserving the data for Phase 2 modules without forcing
    a schema extension today.
    """

    taxes: TaxNote | None = None
    leases: LeaseNote | None = None
    provisions: list[ProvisionItem] = Field(default_factory=list)
    extensions: dict[str, Any] = Field(default_factory=dict)


# ----------------------------------------------------------------------
# Segments + historical (optional)
# ----------------------------------------------------------------------
class Segments(BaseSchema):
    """Segment breakdown along 0..3 dimensions (geography / product /
    business line). Each dimension maps ``{period: {segment_name: value}}``
    so a single extraction can carry multi-period segment data.
    """

    by_geography: dict[str, dict[str, Decimal]] | None = None
    by_product: dict[str, dict[str, Decimal]] | None = None
    by_business_line: dict[str, dict[str, Decimal]] | None = None


class HistoricalData(BaseSchema):
    """Multi-year time series for top-level metrics.

    Keyed by year label (``"2020"``, ``"2021"``, …). ``extensions``
    carries per-company series not in the canonical set. Phase 1
    doesn't consume this — Phase 2's CAGR / capital-allocation views
    will read it.
    """

    revenue_by_year: dict[str, Decimal] = Field(default_factory=dict)
    net_income_by_year: dict[str, Decimal] = Field(default_factory=dict)
    total_assets_by_year: dict[str, Decimal] = Field(default_factory=dict)
    total_equity_by_year: dict[str, Decimal] = Field(default_factory=dict)
    extensions: dict[str, dict[str, Decimal]] = Field(default_factory=dict)


# ----------------------------------------------------------------------
# Top-level
# ----------------------------------------------------------------------
class RawExtraction(BaseSchema):
    """Human-produced extraction from annual report → structured YAML.

    Boundary between human extraction (PDF reading with Claude.ai
    assistance) and system processing (reclassification, valuation,
    ficha). Source of truth for numerical values — everything
    downstream trusts these numbers and doesn't re-derive them from
    unstructured text.
    """

    # ── Identity ──────────────────────────────────────────────
    ticker: Ticker
    company_name: str = Field(min_length=1)
    reporting_currency: Currency
    unit_scale: UnitScale
    extraction_date: ISODate
    source: str = Field(min_length=1)
    extractor: str = "Claude.ai + human validation"

    # ── Periods ───────────────────────────────────────────────
    fiscal_periods: list[FiscalPeriodData]

    # ── Statements (keyed by period label) ───────────────────
    income_statement: dict[str, IncomeStatementPeriod]
    balance_sheet: dict[str, BalanceSheetPeriod]
    cash_flow: dict[str, CashFlowPeriod] = Field(default_factory=dict)

    # ── Notes + optional blocks ──────────────────────────────
    notes: Notes = Field(default_factory=Notes)
    segments: Segments | None = None
    historical: HistoricalData | None = None

    # ── Validators ────────────────────────────────────────────
    @model_validator(mode="after")
    def validate_completeness(self) -> RawExtraction:
        """Every well-formed extraction has:

        - at least one fiscal period;
        - exactly 0 or 1 period flagged ``is_primary`` (0 → first
          entry is treated as primary);
        - IS + BS for the primary period. (CF is optional — some
          interim reports don't disclose one.)
        """
        if not self.fiscal_periods:
            raise ValueError("fiscal_periods must have at least one entry")

        primaries = [fp for fp in self.fiscal_periods if fp.is_primary]
        if len(primaries) > 1:
            raise ValueError(
                f"at most one fiscal period may have is_primary=true; "
                f"found {len(primaries)}: {[p.period for p in primaries]}"
            )
        primary = primaries[0] if primaries else self.fiscal_periods[0]

        if primary.period not in self.income_statement:
            raise ValueError(
                f"primary period {primary.period!r} has no income_statement entry"
            )
        if primary.period not in self.balance_sheet:
            raise ValueError(
                f"primary period {primary.period!r} has no balance_sheet entry"
            )
        return self

    # ── Convenience ───────────────────────────────────────────
    @property
    def primary_period(self) -> FiscalPeriodData:
        """Period flagged ``is_primary``, or the first if none set."""
        for fp in self.fiscal_periods:
            if fp.is_primary:
                return fp
        return self.fiscal_periods[0]

    @property
    def primary_is(self) -> IncomeStatementPeriod:
        return self.income_statement[self.primary_period.period]

    @property
    def primary_bs(self) -> BalanceSheetPeriod:
        return self.balance_sheet[self.primary_period.period]

    @property
    def primary_cf(self) -> CashFlowPeriod | None:
        return self.cash_flow.get(self.primary_period.period)
