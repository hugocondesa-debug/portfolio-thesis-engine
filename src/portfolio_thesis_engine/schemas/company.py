"""Canonical Company State — output of the extraction system.

Top-level schema :class:`CanonicalCompanyState` is immutable and composed from
many sub-entities. Consumed by the valuation module as input and by the
portfolio module for ratios / display.
"""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field

from portfolio_thesis_engine.schemas.base import BaseSchema, ImmutableSchema
from portfolio_thesis_engine.schemas.common import (
    ConfidenceTag,
    Currency,
    FiscalPeriod,
    Money,
    Percentage,
    Profile,
    Source,
)
from portfolio_thesis_engine.schemas.decomposition import (
    DecompositionCoverage,
    LineDecomposition,
    SubItem,
)


class CompanyIdentity(BaseSchema):
    """Basic company identification."""

    ticker: str = Field(min_length=1, max_length=20)
    isin: str | None = Field(default=None, pattern=r"^[A-Z]{2}[A-Z0-9]{9}\d$")
    name: str
    legal_name: str | None = None
    reporting_currency: Currency
    profile: Profile
    sector_gics: str | None = None
    industry_gics: str | None = None
    fiscal_year_end_month: int = Field(ge=1, le=12)
    country_domicile: str
    exchange: str
    shares_outstanding: Decimal | None = None
    market_contexts: list[str] = Field(default_factory=list)


class IncomeStatementLine(BaseSchema):
    """Single line in a reclassified IS."""

    label: str
    value: Money
    is_adjusted: bool = False
    adjustment_note: str | None = None
    source: Source | None = None


class BalanceSheetLine(BaseSchema):
    """Single line in a reclassified BS (Invested Capital view for P1)."""

    label: str
    value: Money
    category: str
    is_adjusted: bool = False
    source: Source | None = None


class CashFlowLine(BaseSchema):
    """Single line in CF (economic view)."""

    label: str
    value: Money
    category: str
    is_adjusted: bool = False


class ReclassifiedStatements(BaseSchema):
    """Reclassified financial statements for one fiscal period."""

    period: FiscalPeriod
    income_statement: list[IncomeStatementLine]
    balance_sheet: list[BalanceSheetLine]
    cash_flow: list[CashFlowLine]
    bs_checksum_pass: bool
    is_checksum_pass: bool
    cf_checksum_pass: bool
    checksum_notes: list[str] = Field(default_factory=list)


class ModuleAdjustment(BaseSchema):
    """Single adjustment from a module (A–F or Patches)."""

    module: str
    description: str
    amount: Money
    affected_periods: list[FiscalPeriod]
    rationale: str
    source: Source | None = None


class AdjustmentsApplied(BaseSchema):
    """All adjustments applied during extraction.

    Phase 1.5.10: :attr:`module_d_note_decompositions` stores the
    universal note decomposer output — keyed by ``"{statement}:{label}"``
    so the analysis layer and display layer can look up any line's
    sub-items without re-running Module D. Coverage summary lives on
    :attr:`module_d_coverage` for quick audit.
    """

    module_a_taxes: list[ModuleAdjustment] = Field(default_factory=list)
    module_b_provisions: list[ModuleAdjustment] = Field(default_factory=list)
    module_c_leases: list[ModuleAdjustment] = Field(default_factory=list)
    module_d_pensions: list[ModuleAdjustment] = Field(default_factory=list)
    module_d_note_decompositions: dict[str, LineDecomposition] = Field(
        default_factory=dict
    )
    module_d_coverage: DecompositionCoverage | None = None
    module_e_sbc: list[ModuleAdjustment] = Field(default_factory=list)
    module_f_capitalize: list[ModuleAdjustment] = Field(default_factory=list)
    patches: list[ModuleAdjustment] = Field(default_factory=list)
    decision_log: list[str] = Field(default_factory=list)
    estimates_log: list[str] = Field(default_factory=list)


class InvestedCapital(BaseSchema):
    """Invested Capital summary (P1, P4).

    Phase 1.5.9.1: :attr:`financial_liabilities` stays as the aggregate
    (bank debt + leases) to preserve the IC identity, but :attr:`bank_debt`
    and :attr:`lease_liabilities` expose the split needed by the equity
    bridge. :attr:`operating_working_capital` (current operating assets −
    current operating liabilities) feeds the DCF's per-year ΔWC projection.
    """

    period: FiscalPeriod
    operating_assets: Money
    operating_liabilities: Money
    invested_capital: Money
    financial_assets: Money
    financial_liabilities: Money
    bank_debt: Money = Decimal("0")
    lease_liabilities: Money = Decimal("0")
    operating_working_capital: Money = Decimal("0")
    equity_claims: Money
    nci_claims: Money = Decimal("0")
    cross_check_residual: Money


class NOPATBridge(BaseSchema):
    """Operating profit → EBITA → NOPAT → NI bridge.

    Phase 1.5.9.1: :attr:`nopat` is the **sustainable-basis** NOPAT
    (primary metric for investment decisions), while :attr:`nopat_reported`
    tracks the reported-basis NOPAT for reconciliation with accounting
    statements. :attr:`which_used_for_nopat` records which was used as
    the primary anchor (``"sustainable"`` when non-recurring items were
    detected, otherwise ``"reported"``). The DCF reads ``nopat`` for its
    Year-0 display so reported NOPAT never contradicts the forward
    projection (which has always used sustainable margin).

    Structure, per Phase 1.5.9::

        NOPAT = EBITA × (1 − t)
              = (sustainable_ebit + amortisation) × (1 − t)     [primary]
        FCFF  = NOPAT + Depreciation − CapEx − ΔWC

    When amortisation can't be isolated, :attr:`nopat_methodology`
    records ``"ebit_based_no_amort_detected"`` and the anchor falls back
    to EBIT × (1 − t).

    :attr:`operating_income_sustainable` strips non-recurring below-the-
    line items (``Other gains, net``, government grants, gain on disposal,
    FV remeasurements of contingent consideration, exceptional /
    restructuring).
    """

    period: FiscalPeriod
    ebitda: Money
    ebita: Money | None = None
    operating_income: Money | None = None
    operating_income_sustainable: Money | None = None
    non_recurring_operating_items: Money = Decimal("0")
    # Phase 1.5.10 — when Module D runs, it populates these with the
    # exact sub-items that contributed to the sustainable adjustment
    # so the display can show each rationale.
    non_recurring_items_detail: list[SubItem] = Field(default_factory=list)
    operational_adjustments_detail: list[SubItem] = Field(default_factory=list)
    depreciation: Money = Decimal("0")
    amortisation: Money = Decimal("0")
    nopat_methodology: str = "ebita_based"
    which_used_for_nopat: str = "reported"
    operating_taxes: Money
    nopat: Money
    nopat_reported: Money | None = None
    financial_income: Money
    financial_expense: Money
    non_operating_items: Money
    reported_net_income: Money


class KeyRatios(BaseSchema):
    """Ratios derived from reclassified statements.

    Phase 1.5.9.1 — :attr:`roic` is the **sustainable-basis** ROIC
    (primary metric). :attr:`roic_reported` tracks the reported-basis
    ROIC for reconciliation. Same convention as :class:`NOPATBridge`:
    sustainable first, reported as audit trail.
    """

    period: FiscalPeriod
    roic: Percentage | None = None
    roic_reported: Percentage | None = None
    roic_adj_leases: Percentage | None = None
    roe: Percentage | None = None
    ros: Percentage | None = None
    operating_margin: Percentage | None = None
    sustainable_operating_margin: Percentage | None = None
    ebitda_margin: Percentage | None = None
    net_debt_ebitda: Decimal | None = None
    capex_revenue: Percentage | None = None
    dso: Decimal | None = None
    dpo: Decimal | None = None
    dio: Decimal | None = None
    sector_specific: dict[str, Decimal] = Field(default_factory=dict)


class CapitalAllocationHistory(BaseSchema):
    """Capital allocation tracking across multiple years."""

    periods: list[FiscalPeriod]
    cfo_total: Money
    capex_total: Money
    acquisitions_total: Money
    dividends_total: Money
    buybacks_total: Money
    debt_change: Money
    equity_issuance: Money
    allocation_mix: dict[str, Percentage] = Field(default_factory=dict)


class AnalysisDerived(BaseSchema):
    """All derived analysis artefacts."""

    invested_capital_by_period: list[InvestedCapital]
    nopat_bridge_by_period: list[NOPATBridge]
    ratios_by_period: list[KeyRatios]
    capital_allocation: CapitalAllocationHistory | None = None
    dupont_decomposition: dict[str, Any] | None = None
    cf_quality_analysis: dict[str, Any] | None = None
    unit_economics: dict[str, Any] | None = None


class QuarterlyData(BaseSchema):
    """Quarterly IS + BS snapshot."""

    latest_quarter: FiscalPeriod
    quarterly_is_lines: list[dict[str, Any]]
    seasonality: str
    seasonality_method_used: str
    bs_snapshot_date: str
    bs_snapshot: dict[str, Money]
    material_changes_since_fye: list[str] = Field(default_factory=list)


class ValidationResult(BaseSchema):
    """Single validation check result."""

    check_id: str
    name: str
    status: str
    detail: str
    blocking: bool = False


class ValidationResults(BaseSchema):
    """All validation results from extraction."""

    universal_checksums: list[ValidationResult]
    profile_specific_checksums: list[ValidationResult]
    confidence_rating: str
    blocking_issues: list[str] = Field(default_factory=list)


class VintageTag(BaseSchema):
    """Vintage tag documenting temporal provenance."""

    value_reference: str
    confidence: ConfidenceTag
    original_date: str
    latest_restatement: str | None = None
    notes: str | None = None


class CascadeEntry(BaseSchema):
    """Documents a restatement cascade."""

    original_period: FiscalPeriod
    restated_in: FiscalPeriod
    affected_metrics: list[str]
    reason: str
    impact_summary: str


class VintageAndCascade(BaseSchema):
    """Vintage tags and cascade log."""

    vintage_tags: list[VintageTag] = Field(default_factory=list)
    cascade_log: list[CascadeEntry] = Field(default_factory=list)


class MethodologyMetadata(BaseSchema):
    """What methodology was used to produce this state."""

    extraction_system_version: str
    profile_applied: Profile
    protocols_activated: list[str]
    sub_modules_active: dict[str, bool] = Field(default_factory=dict)
    tiers: dict[str, int] = Field(default_factory=dict)
    llm_calls_summary: dict[str, int] = Field(default_factory=dict)
    total_api_cost_usd: Decimal | None = None


class CanonicalCompanyState(ImmutableSchema):
    """Immutable output of the extraction system for a company.

    Represents a complete, reclassified, validated view of the company's
    financial state as of a specific extraction date. Consumed by the
    valuation module (as input) and the portfolio module (for ratios).
    """

    extraction_id: str
    extraction_date: datetime
    as_of_date: str

    identity: CompanyIdentity
    reclassified_statements: list[ReclassifiedStatements]
    adjustments: AdjustmentsApplied
    analysis: AnalysisDerived
    quarterly: QuarterlyData | None = None

    validation: ValidationResults
    vintage: VintageAndCascade
    methodology: MethodologyMetadata

    source_documents: list[str] = Field(default_factory=list)
