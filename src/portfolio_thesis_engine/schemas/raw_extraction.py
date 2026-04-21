"""Raw extraction — human/Claude.ai boundary for every numerical value.

Phase 1.5 architecture. Hugo reads the source document (PDF annual
report, interim, earnings-call transcript, SEC correspondence, …)
in a Claude.ai Project per profile, produces a structured YAML
validated by :class:`RawExtraction`, and feeds it into the app. No
in-app LLM extraction; the pipeline consumes this typed document
deterministically.

Schema scope:

- **~45 document types** across numeric (financial statements),
  narrative (investor materials + correspondence), regulatory
  (SEC comment/response letters, FDA), and industry-specific
  (Pillar 3, SFCR, ICAAP, NI 43-101) buckets.
- **Comprehensive statements** — every IFRS / US-GAAP line an analyst
  would bother tracking, all :class:`Decimal` | None so partial
  disclosures (interim with no CF) parse cleanly.
- **17 note types** covering the canonical disclosure set: taxes,
  leases, provisions, goodwill, intangibles, PP&E, inventory,
  employee benefits, SBC, pensions, financial instruments,
  commitments + contingencies, acquisitions, discontinued ops,
  subsequent events, related parties — plus an
  :class:`UnknownSectionItem` bucket for anything else the extractor
  flags for review.
- **Extensions dicts** on statements, notes, and historical so
  company-specific lines survive without schema edits.
- **Operational KPIs + narrative content** carried on the same
  schema so one YAML is the complete artefact per document.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from portfolio_thesis_engine.schemas.base import BaseSchema
from portfolio_thesis_engine.schemas.common import (
    Currency,
    ISODate,
    Ticker,
)


# ======================================================================
# Enums
# ======================================================================
class DocumentType(StrEnum):
    """Source-document kind. Drives which sections the extractor
    expects and which validation checks apply."""

    # --- Numeric: financial statements + regulatory filings ----------
    ANNUAL_REPORT = "annual_report"
    FORM_10K = "form_10k"
    FORM_20F = "form_20f"
    FORM_10Q = "form_10q"
    FORM_6K = "form_6k"
    FORM_8K = "form_8k"
    INTERIM_REPORT = "interim_report"
    QUARTERLY_UPDATE = "quarterly_update"
    PRELIMINARY_ANNOUNCEMENT = "preliminary_announcement"
    AIF = "aif"  # Canadian Annual Information Form
    HKEX_ANNOUNCEMENT = "hkex_announcement"
    PRESS_RELEASE = "press_release"
    PRC_ANNUAL = "prc_annual"
    TDNET_DISCLOSURE = "tdnet_disclosure"
    REIT_SUPPLEMENT = "reit_supplement"
    OPERATING_STATISTICS = "operating_statistics"

    # --- Narrative: investor materials ----------------------------
    EARNINGS_CALL = "earnings_call"
    EARNINGS_CALL_SLIDES = "earnings_call_slides"
    INVESTOR_PRESENTATION = "investor_presentation"
    INVESTOR_DAY = "investor_day"
    ANALYST_DAY = "analyst_day"
    MDA_STANDALONE = "mda_standalone"
    STRATEGIC_REPORT = "strategic_report"
    DIRECTORS_REPORT = "directors_report"
    FORM_DEF14A = "form_def14a"
    PROXY_CIRCULAR = "proxy_circular"
    ESG_REPORT = "esg_report"
    SUSTAINABILITY_REPORT = "sustainability_report"
    CDP_SUBMISSION = "cdp_submission"
    PROSPECTUS = "prospectus"
    INVESTOR_LETTER = "investor_letter"
    RESEARCH_REPORT_COMPANY_PRODUCED = "research_report_company_produced"

    # --- Regulatory correspondence -------------------------------
    SEC_COMMENT_LETTER = "sec_comment_letter"
    SEC_RESPONSE_LETTER = "sec_response_letter"
    SEC_NO_ACTION_LETTER = "sec_no_action_letter"
    FDA_WARNING_LETTER = "fda_warning_letter"

    # --- Industry-specific ---------------------------------------
    PILLAR_3 = "pillar_3"  # Banks — Basel III disclosure
    SFCR = "sfcr"  # Insurance — Solvency II public disclosure
    ICAAP = "icaap"  # Banks — internal capital adequacy
    ORSA = "orsa"  # Insurance — own risk and solvency assessment
    NI_43_101 = "ni_43_101"  # Mining — Canadian technical report

    # --- Catchall ------------------------------------------------
    OTHER = "other"


class ExtractionType(StrEnum):
    """Whether the document produces numeric statements or narrative
    content. Drives which sections of :class:`RawExtraction` are
    required vs optional."""

    NUMERIC = "numeric"
    NARRATIVE = "narrative"


UnitScale = Literal["units", "thousands", "millions"]
PeriodType = Literal["FY", "H1", "H2", "Q1", "Q2", "Q3", "Q4", "YTD", "LTM"]
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
SubsequentEventImpact = Literal[
    "material_negative",
    "material_positive",
    "neutral",
    "pending",
]


# ======================================================================
# Metadata
# ======================================================================
class FiscalPeriodData(BaseSchema):
    """One row in :class:`DocumentMetadata.fiscal_periods`.

    ``period`` is the label keying the IS / BS / CF dicts; ``end_date``
    is the last calendar day of the period. ``period_type`` lets
    guardrails reason about year-vs-interim scope.
    """

    period: str = Field(min_length=1)
    end_date: ISODate
    is_primary: bool = False
    period_type: PeriodType = "FY"


class DocumentMetadata(BaseSchema):
    """Identity + provenance for one source document.

    ``source_file_sha256`` lets the pipeline detect accidental re-runs
    on a re-extracted-but-identical PDF. ``extraction_version`` +
    ``extractor`` create an audit trail if Hugo revises a prior
    extraction.
    """

    ticker: Ticker
    company_name: str = Field(min_length=1)
    document_type: DocumentType
    extraction_type: ExtractionType
    reporting_currency: Currency
    unit_scale: UnitScale
    fiscal_year: int = Field(ge=1900, le=2100)
    extraction_date: ISODate
    extractor: str = "Claude.ai + human validation"
    source_file_sha256: str | None = None
    extraction_version: int = Field(default=1, ge=1)
    extraction_notes: str = ""
    fiscal_periods: list[FiscalPeriodData]


# ======================================================================
# Statements — lenient (every line Decimal | None)
# ======================================================================
class IncomeStatementPeriod(BaseSchema):
    """Income statement for one fiscal period."""

    # ── Top line ───────────────────────────────────────────────
    revenue: Decimal | None = None
    cost_of_sales: Decimal | None = None
    gross_profit: Decimal | None = None
    # ── Operating expenses ─────────────────────────────────────
    selling_marketing: Decimal | None = None
    general_administrative: Decimal | None = None
    selling_general_administrative: Decimal | None = None
    research_development: Decimal | None = None
    other_operating_expenses: Decimal | None = None
    operating_expenses_total: Decimal | None = None
    depreciation_amortization: Decimal | None = None
    # ── Operating subtotals ───────────────────────────────────
    operating_income: Decimal | None = None
    ebitda_reported: Decimal | None = None
    # ── Below the line ─────────────────────────────────────────
    finance_income: Decimal | None = None
    finance_expenses: Decimal | None = None
    net_finance: Decimal | None = None
    share_of_associates: Decimal | None = None
    non_operating_income: Decimal | None = None
    income_before_tax: Decimal | None = None
    income_tax: Decimal | None = None
    net_income_from_continuing: Decimal | None = None
    net_income_from_discontinued: Decimal | None = None
    net_income: Decimal | None = None
    net_income_minority: Decimal | None = None
    net_income_parent: Decimal | None = None
    # ── Per-share ──────────────────────────────────────────────
    eps_basic: Decimal | None = None
    eps_diluted: Decimal | None = None
    shares_basic_weighted_avg: Decimal | None = None
    shares_diluted_weighted_avg: Decimal | None = None

    extensions: dict[str, Decimal] = Field(default_factory=dict)


class BalanceSheetPeriod(BaseSchema):
    """Balance sheet for one fiscal period."""

    # ── Current assets ─────────────────────────────────────────
    cash_and_equivalents: Decimal | None = None
    short_term_investments: Decimal | None = None
    accounts_receivable: Decimal | None = None
    inventory: Decimal | None = None
    current_assets_other: Decimal | None = None
    total_current_assets: Decimal | None = None
    # ── Non-current assets ─────────────────────────────────────
    ppe_gross: Decimal | None = None
    accumulated_depreciation: Decimal | None = None
    ppe_net: Decimal | None = None
    rou_assets: Decimal | None = None
    goodwill: Decimal | None = None
    intangibles_other: Decimal | None = None
    investments: Decimal | None = None
    deferred_tax_assets: Decimal | None = None
    non_current_assets_other: Decimal | None = None
    total_non_current_assets: Decimal | None = None
    total_assets: Decimal | None = None
    # ── Current liabilities ─────────────────────────────────────
    accounts_payable: Decimal | None = None
    short_term_debt: Decimal | None = None
    lease_liabilities_current: Decimal | None = None
    deferred_revenue_current: Decimal | None = None
    current_liabilities_other: Decimal | None = None
    total_current_liabilities: Decimal | None = None
    # ── Non-current liabilities ─────────────────────────────────
    long_term_debt: Decimal | None = None
    lease_liabilities_noncurrent: Decimal | None = None
    deferred_tax_liabilities: Decimal | None = None
    provisions: Decimal | None = None
    pension_obligations: Decimal | None = None
    non_current_liabilities_other: Decimal | None = None
    total_non_current_liabilities: Decimal | None = None
    total_liabilities: Decimal | None = None
    # ── Equity ───────────────────────────────────────────────
    share_capital: Decimal | None = None
    share_premium: Decimal | None = None
    retained_earnings: Decimal | None = None
    other_reserves: Decimal | None = None
    treasury_shares: Decimal | None = None
    total_equity_parent: Decimal | None = None
    non_controlling_interests: Decimal | None = None
    total_equity: Decimal | None = None

    extensions: dict[str, Decimal] = Field(default_factory=dict)


class CashFlowPeriod(BaseSchema):
    """Cash flow statement for one fiscal period."""

    # ── Operating ────────────────────────────────────────────
    net_income_cf: Decimal | None = None
    depreciation_amortization_cf: Decimal | None = None
    working_capital_changes: Decimal | None = None
    operating_cash_flow_other: Decimal | None = None
    operating_cash_flow: Decimal | None = None
    # ── Investing ────────────────────────────────────────────
    capex: Decimal | None = None
    acquisitions: Decimal | None = None
    divestitures: Decimal | None = None
    investments_other: Decimal | None = None
    investing_cash_flow: Decimal | None = None
    # ── Financing ────────────────────────────────────────────
    dividends_paid: Decimal | None = None
    debt_issuance: Decimal | None = None
    debt_repayment: Decimal | None = None
    share_issuance: Decimal | None = None
    share_repurchases: Decimal | None = None
    financing_other: Decimal | None = None
    financing_cash_flow: Decimal | None = None
    # ── Reconciliation ───────────────────────────────────────
    fx_effect: Decimal | None = None
    net_change_in_cash: Decimal | None = None

    extensions: dict[str, Decimal] = Field(default_factory=dict)


# ======================================================================
# Notes
# ======================================================================
class TaxReconciliationItem(BaseSchema):
    """One row in the statutory→effective tax-rate reconciliation."""

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
    short_term_lease_expense: Decimal | None = None
    variable_lease_payments: Decimal | None = None


class ProvisionItem(BaseSchema):
    """One row of the provisions note. Module B classifies these."""

    description: str = Field(min_length=1)
    amount: Decimal
    classification: ProvisionClassification = "other"


class GoodwillNote(BaseSchema):
    """Goodwill movement + impairment by cash-generating unit."""

    opening: Decimal | None = None
    additions: Decimal | None = None
    impairment: Decimal | None = None
    closing: Decimal | None = None
    by_cgu: dict[str, Decimal] = Field(default_factory=dict)


class IntangiblesNote(BaseSchema):
    """Intangibles (non-goodwill) movement + split by type."""

    opening: Decimal | None = None
    additions: Decimal | None = None
    amortization: Decimal | None = None
    impairment: Decimal | None = None
    closing: Decimal | None = None
    by_type: dict[str, Decimal] = Field(default_factory=dict)


class PPENote(BaseSchema):
    """Property / plant / equipment movement table."""

    opening_gross: Decimal | None = None
    additions: Decimal | None = None
    disposals: Decimal | None = None
    transfers: Decimal | None = None
    closing_gross: Decimal | None = None
    accumulated_depreciation: Decimal | None = None


class InventoryNote(BaseSchema):
    """Inventory split by stage + provisions."""

    raw_materials: Decimal | None = None
    wip: Decimal | None = None
    finished_goods: Decimal | None = None
    provisions: Decimal | None = None
    total: Decimal | None = None


class EmployeeBenefitsNote(BaseSchema):
    """Headcount + compensation summary."""

    headcount: Decimal | None = None
    avg_compensation: Decimal | None = None
    total_compensation: Decimal | None = None
    pension_expense: Decimal | None = None
    sbc_expense: Decimal | None = None


class SBCNote(BaseSchema):
    """Stock-based compensation grant + outstanding schedule."""

    stock_options_granted: Decimal | None = None
    stock_options_exercised: Decimal | None = None
    stock_options_outstanding: Decimal | None = None
    rsus_granted: Decimal | None = None
    rsus_vested: Decimal | None = None
    rsus_outstanding: Decimal | None = None
    expense: Decimal | None = None


class PensionNote(BaseSchema):
    """Defined-benefit pension movement table."""

    dbo_opening: Decimal | None = None
    dbo_closing: Decimal | None = None
    plan_assets_opening: Decimal | None = None
    plan_assets_closing: Decimal | None = None
    service_cost: Decimal | None = None
    interest_cost: Decimal | None = None
    actuarial_gains_losses: Decimal | None = None


class FinancialInstrumentsNote(BaseSchema):
    """Free-form risk summaries (narrative — no Decimal)."""

    credit_risk: str = ""
    liquidity_risk: str = ""
    market_risk: str = ""


class CommitmentsNote(BaseSchema):
    """Off-balance-sheet commitments + contingencies."""

    capital_commitments: Decimal | None = None
    operating_lease_future: Decimal | None = None
    guarantees_provided: Decimal | None = None
    contingent_liabilities: Decimal | None = None


class AcquisitionItem(BaseSchema):
    """One acquisition during the period."""

    name: str = Field(min_length=1)
    date: ISODate
    consideration: Decimal
    fair_value: Decimal | None = None
    goodwill_recognized: Decimal | None = None


class AcquisitionsNote(BaseSchema):
    items: list[AcquisitionItem] = Field(default_factory=list)


class DiscontinuedOpsNote(BaseSchema):
    """Discontinued operations summary per the period."""

    revenue: Decimal | None = None
    operating_income: Decimal | None = None
    net_income: Decimal | None = None


class SubsequentEventItem(BaseSchema):
    description: str = Field(min_length=1)
    date: ISODate | None = None
    impact: SubsequentEventImpact = "pending"


class RelatedPartyItem(BaseSchema):
    counterparty: str = Field(min_length=1)
    nature: str = Field(min_length=1)
    amount: Decimal | None = None


class UnknownSectionItem(BaseSchema):
    """Catchall for sections the extractor can't map to the canonical
    schema. Flags for human review rather than dropping silently."""

    title: str = Field(min_length=1)
    page_range: str | None = None
    content_summary: str = ""
    extracted_values: dict[str, Decimal] = Field(default_factory=dict)
    reviewer_flag: bool = True


class NotesContainer(BaseSchema):
    """All note-level disclosures for one document."""

    taxes: TaxNote | None = None
    leases: LeaseNote | None = None
    provisions: list[ProvisionItem] = Field(default_factory=list)
    goodwill: GoodwillNote | None = None
    intangibles: IntangiblesNote | None = None
    ppe: PPENote | None = None
    inventory: InventoryNote | None = None
    trade_receivables: dict[str, Decimal] = Field(default_factory=dict)
    trade_payables: dict[str, Decimal] = Field(default_factory=dict)
    employee_benefits: EmployeeBenefitsNote | None = None
    share_based_compensation: SBCNote | None = None
    pensions: PensionNote | None = None
    financial_instruments: FinancialInstrumentsNote | None = None
    commitments_contingencies: CommitmentsNote | None = None
    acquisitions: AcquisitionsNote | None = None
    discontinued_ops: DiscontinuedOpsNote | None = None
    subsequent_events: list[SubsequentEventItem] = Field(default_factory=list)
    related_parties: list[RelatedPartyItem] = Field(default_factory=list)
    unknown_sections: list[UnknownSectionItem] = Field(default_factory=list)
    extensions: dict[str, Any] = Field(default_factory=dict)


# ======================================================================
# Segments + historical + KPIs
# ======================================================================
class Segments(BaseSchema):
    """Multi-dimensional segment data. Outer key = period label; inner
    key = segment name; innermost = metric → value."""

    by_geography: dict[str, dict[str, dict[str, Decimal]]] | None = None
    by_product: dict[str, dict[str, dict[str, Decimal]]] | None = None
    by_business_line: dict[str, dict[str, dict[str, Decimal]]] | None = None


class HistoricalData(BaseSchema):
    """Multi-year time series. Keyed by year label (``"2023"``, …)."""

    revenue_by_year: dict[str, Decimal] = Field(default_factory=dict)
    net_income_by_year: dict[str, Decimal] = Field(default_factory=dict)
    total_assets_by_year: dict[str, Decimal] = Field(default_factory=dict)
    total_equity_by_year: dict[str, Decimal] = Field(default_factory=dict)
    free_cash_flow_by_year: dict[str, Decimal] = Field(default_factory=dict)
    shares_outstanding_by_year: dict[str, Decimal] = Field(default_factory=dict)
    dividends_by_year: dict[str, Decimal] = Field(default_factory=dict)
    extensions: dict[str, dict[str, Decimal]] = Field(default_factory=dict)


class OperationalKPIs(BaseSchema):
    """Company-specific operational metrics.

    Outer key = metric name; inner key = period label; value is
    numeric (Decimal) or a narrative string. Free-form because every
    sector has different KPIs (RPO for SaaS, occupancy for REITs,
    same-store sales for retail).
    """

    metrics: dict[str, dict[str, Decimal | str]] = Field(default_factory=dict)


# ======================================================================
# Narrative (schema-only in Phase 1.5; processing in Phase 2)
# ======================================================================
class GuidanceChangeItem(BaseSchema):
    metric: str = Field(min_length=1)
    old: str = ""
    new: str = ""
    direction: Literal["up", "down", "unchanged"] = "unchanged"


class QAItem(BaseSchema):
    question: str = Field(min_length=1)
    answer: str = Field(min_length=1)
    speaker: str = ""
    topic: str = ""


class NarrativeContent(BaseSchema):
    """Qualitative content from narrative documents (earnings calls,
    MD&A, investor presentations). Phase 1.5 defines the shape;
    Phase 2 wires the processing pipeline."""

    key_themes: list[str] = Field(default_factory=list)
    guidance_changes: list[GuidanceChangeItem] = Field(default_factory=list)
    risks_mentioned: list[str] = Field(default_factory=list)
    q_and_a_highlights: list[QAItem] = Field(default_factory=list)
    forward_looking_statements: list[str] = Field(default_factory=list)
    capital_allocation_comments: list[str] = Field(default_factory=list)


# ======================================================================
# Top-level
# ======================================================================
class RawExtraction(BaseSchema):
    """Complete human-produced extraction for one source document."""

    metadata: DocumentMetadata
    income_statement: dict[str, IncomeStatementPeriod] = Field(default_factory=dict)
    balance_sheet: dict[str, BalanceSheetPeriod] = Field(default_factory=dict)
    cash_flow: dict[str, CashFlowPeriod] = Field(default_factory=dict)
    notes: NotesContainer = Field(default_factory=NotesContainer)
    segments: Segments | None = None
    historical: HistoricalData | None = None
    operational_kpis: OperationalKPIs | None = None
    narrative: NarrativeContent | None = None

    # ── Validators ──────────────────────────────────────────────
    @model_validator(mode="after")
    def validate_completeness(self) -> RawExtraction:
        """Extraction-type-driven completeness.

        Numeric documents must have at least one fiscal period with
        IS + BS populated for the primary period. Narrative documents
        can omit statements but must have at least one of the
        narrative content buckets populated.
        """
        meta = self.metadata
        if not meta.fiscal_periods:
            raise ValueError("metadata.fiscal_periods must have at least one entry")

        primaries = [fp for fp in meta.fiscal_periods if fp.is_primary]
        if len(primaries) > 1:
            raise ValueError(
                f"at most one fiscal period may have is_primary=true; "
                f"found {len(primaries)}: {[p.period for p in primaries]}"
            )
        primary = primaries[0] if primaries else meta.fiscal_periods[0]

        if meta.extraction_type == ExtractionType.NUMERIC:
            if primary.period not in self.income_statement:
                raise ValueError(
                    f"numeric extraction: primary period {primary.period!r} "
                    f"has no income_statement entry"
                )
            if primary.period not in self.balance_sheet:
                raise ValueError(
                    f"numeric extraction: primary period {primary.period!r} "
                    f"has no balance_sheet entry"
                )
        else:  # NARRATIVE
            if self.narrative is None or self._narrative_empty():
                raise ValueError(
                    "narrative extraction: narrative section must be populated "
                    "(key_themes, guidance_changes, risks_mentioned, …)"
                )
        return self

    def _narrative_empty(self) -> bool:
        """True when every list on :attr:`narrative` is empty."""
        n = self.narrative
        if n is None:
            return True
        return not any(
            [
                n.key_themes,
                n.guidance_changes,
                n.risks_mentioned,
                n.q_and_a_highlights,
                n.forward_looking_statements,
                n.capital_allocation_comments,
            ]
        )

    # ── Convenience ─────────────────────────────────────────────
    @property
    def primary_period(self) -> FiscalPeriodData:
        """Period flagged ``is_primary``, or the first if none set."""
        for fp in self.metadata.fiscal_periods:
            if fp.is_primary:
                return fp
        return self.metadata.fiscal_periods[0]

    @property
    def primary_is(self) -> IncomeStatementPeriod | None:
        return self.income_statement.get(self.primary_period.period)

    @property
    def primary_bs(self) -> BalanceSheetPeriod | None:
        return self.balance_sheet.get(self.primary_period.period)

    @property
    def primary_cf(self) -> CashFlowPeriod | None:
        return self.cash_flow.get(self.primary_period.period)
