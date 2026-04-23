"""Phase 2 Sprint 1 — multi-period historical time-series schemas.

Elevates single-period canonical states into a time-series view with
restatement detection, fiscal-year change tracking, TTM construction,
and narrative evolution. Consumed by the ``pte historicals`` CLI and
downstream analytical layers (DuPont, peer comparison — Sprint 2+).

All schemas are read-only analytical artefacts derived from existing
canonical states; nothing here mutates the upstream pipeline.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import Field

from portfolio_thesis_engine.schemas.base import BaseSchema
from portfolio_thesis_engine.schemas.company import CompanyIdentity
from portfolio_thesis_engine.schemas.economic_bs import EconomicBalanceSheet
from portfolio_thesis_engine.schemas.ficha import NarrativeSummary
from portfolio_thesis_engine.schemas.raw_extraction import (
    AuditStatus,
    DocumentType,
)


class DuPont3Way(BaseSchema):
    """Phase 2 Sprint 2A — three-way ROE decomposition.

    ``ROE = net_margin × asset_turnover × financial_leverage``
    """

    period: str
    net_margin: Decimal | None = None
    asset_turnover: Decimal | None = None
    financial_leverage: Decimal | None = None
    roe_computed: Decimal | None = None
    roe_reported: Decimal | None = None
    reconciliation_delta: Decimal | None = None


class ROEDriverAttribution(BaseSchema):
    """Decompose a ROE delta between two periods into per-driver
    contributions."""

    period_from: str
    period_to: str
    roe_delta_bps: Decimal
    margin_contribution_bps: Decimal
    turnover_contribution_bps: Decimal
    leverage_contribution_bps: Decimal
    cross_residual_bps: Decimal


class DuPont5Way(BaseSchema):
    """Phase 2 Sprint 2B Part A — five-way ROE decomposition.

    ``ROE = tax_burden × interest_burden × operating_margin
           × asset_turnover × financial_leverage``

    Where:

    - ``tax_burden``        = NI / PBT        (1 − effective tax rate)
    - ``interest_burden``   = PBT / EBIT      (retention after interest)
    - ``operating_margin``  = EBIT / Revenue
    - ``asset_turnover``    = Revenue / Total Assets
    - ``financial_leverage`` = Total Assets / Total Equity
    """

    period: str
    tax_burden: Decimal | None = None
    interest_burden: Decimal | None = None
    operating_margin: Decimal | None = None
    asset_turnover: Decimal | None = None
    financial_leverage: Decimal | None = None
    roe_computed: Decimal | None = None
    roe_reported: Decimal | None = None
    reconciliation_delta: Decimal | None = None


class ROE5WayAttribution(BaseSchema):
    """Period-over-period attribution of ΔROE across the five DuPont-5
    drivers. Cross-residual absorbs interaction terms (the 5-way
    additive approximation sheds about 2–5 % of the total in the
    residual, which is acceptable for a diagnostic)."""

    period_from: str
    period_to: str
    roe_delta_bps: Decimal
    tax_burden_contribution_bps: Decimal
    interest_burden_contribution_bps: Decimal
    operating_margin_contribution_bps: Decimal
    asset_turnover_contribution_bps: Decimal
    financial_leverage_contribution_bps: Decimal
    cross_residual_bps: Decimal


_ValueSignal = Literal["DESTROYING", "NEUTRAL", "MODEST", "STRONG"]


class ROICDecomposition(BaseSchema):
    """Phase 2 Sprint 2A — two-way ROIC decomposition.

    ``ROIC = nopat_margin × ic_turnover``
    """

    period: str
    nopat_margin: Decimal | None = None
    ic_turnover: Decimal | None = None
    roic_computed: Decimal | None = None
    roic_reported: Decimal | None = None
    wacc: Decimal | None = None
    spread_bps: Decimal | None = None
    value_signal: _ValueSignal | None = None


class ROICDriverAttribution(BaseSchema):
    period_from: str
    period_to: str
    roic_delta_bps: Decimal
    nopat_margin_contribution_bps: Decimal
    ic_turnover_contribution_bps: Decimal
    cross_residual_bps: Decimal


class QualityOfEarnings(BaseSchema):
    """Phase 2 Sprint 2A — custom weighted earnings quality score with
    every component ratio exposed for drill-down.

    Weights: accruals 30 %, CFO/NI 20 %, AR-vs-revenue 15 %, non-
    recurring share 20 %, audit 15 %. Total 100.
    """

    period: str

    # Component ratios (raw, audit-friendly)
    accruals_to_assets: Decimal | None = None
    cfo_to_ni_ratio: Decimal | None = None
    ar_growth_vs_revenue_growth_delta: Decimal | None = None
    non_recurring_items_share: Decimal | None = None
    audit_status_numeric: Decimal | None = None

    # Component scores (0-100 each)
    accruals_quality_score: int | None = None
    cfo_ni_score: int | None = None
    ar_revenue_score: int | None = None
    non_recurring_score: int | None = None
    audit_score: int | None = None

    composite_score: int | None = None
    flags: list[str] = Field(default_factory=list)


_Trajectory = Literal["ACCELERATING", "STABLE", "DECELERATING"]
_MarginTrajectory = Literal["EXPANDING", "STABLE", "CONTRACTING"]
_ROICTrajectory = Literal["IMPROVING", "STABLE", "DECLINING"]
_CapexTrajectory = Literal["INCREASING", "STABLE", "DECREASING"]


class TrendAnalysis(BaseSchema):
    """Phase 2 Sprint 2A — cross-period trend summary."""

    period_start: str
    period_end: str

    revenue_cagr_2y: Decimal | None = None
    revenue_cagr_3y: Decimal | None = None
    revenue_cagr_5y: Decimal | None = None
    # Phase 2 Sprint 2A.1 — YoY growth surfaces when fewer than three
    # annual records are available, so the CAGR columns can stay blank
    # without hiding the one number we can still compute.
    revenue_yoy_growth: Decimal | None = None
    annuals_used_for_cagr: int = 0
    revenue_trajectory: _Trajectory = "STABLE"

    # Phase 2 Sprint 2B Polish 5 — preliminary signal kept separate
    # from audited/reviewed trajectory so the PM gets both the rigorous
    # view and the forward-looking signal without the CAGR math being
    # corrupted by a 15-month preliminary period.
    revenue_yoy_growth_preliminary: Decimal | None = None
    revenue_trajectory_incl_preliminary: _Trajectory = "STABLE"
    preliminary_signal_period: str | None = None

    operating_margin_delta_bps: Decimal | None = None
    operating_margin_trajectory: _MarginTrajectory = "STABLE"

    roic_delta_bps: Decimal | None = None
    roic_trajectory: _ROICTrajectory = "STABLE"
    roic_spread_latest_vs_wacc: Decimal | None = None
    # Phase 2 Sprint 2B Part C — spread trend tracks the direction of
    # ROIC-vs-WACC over the analysed window.
    roic_spread_trend: Literal[
        "IMPROVING_SPREAD", "STABLE_SPREAD", "DETERIORATING_SPREAD"
    ] = "STABLE_SPREAD"

    capex_revenue_ratio: Decimal | None = None
    capex_revenue_trajectory: _CapexTrajectory = "STABLE"
    working_capital_intensity: Decimal | None = None
    cfo_revenue_ratio: Decimal | None = None

    days_sales_outstanding: Decimal | None = None
    days_inventory: Decimal | None = None
    days_payables: Decimal | None = None
    cash_conversion_cycle: Decimal | None = None


_ValueCreation = Literal["DESTROYING", "NEUTRAL", "CREATING"]
_GrowthQuality = Literal["ORGANIC", "ACQUISITIVE", "MIXED", "UNKNOWN"]
_EfficiencyTrend = Literal["IMPROVING", "STABLE", "DETERIORATING"]
_BSStrength = Literal["STRONG", "ADEQUATE", "WEAK", "UNKNOWN"]
_CredibilityTag = Literal["HIGH", "MODERATE", "LOW", "UNKNOWN"]


class InvestmentSignal(BaseSchema):
    """Phase 2 Sprint 2A — synthesised signal for the CLI ``pte
    analyze`` report. Rule-based classification (no ML)."""

    current_value_creation: _ValueCreation = "NEUTRAL"
    current_value_spread_bps: int | None = None

    growth_trajectory: _Trajectory = "STABLE"
    growth_quality: _GrowthQuality = "UNKNOWN"

    capital_efficiency_trend: _EfficiencyTrend = "STABLE"
    margin_trend: _MarginTrajectory = "STABLE"

    earnings_quality_score: int | None = None
    balance_sheet_strength: _BSStrength = "UNKNOWN"

    management_credibility: _CredibilityTag = "UNKNOWN"

    # Phase 2 Sprint 2B Polish 4 + 5 — caveat fields distinguish the
    # rigorous audited trajectory from the preliminary forward signal.
    earnings_quality_source_period: str | None = None
    preliminary_caveat_bullets: list[str] = Field(default_factory=list)

    summary_bullets: list[str] = Field(default_factory=list)
    positioning_considerations: list[str] = Field(default_factory=list)


class HistoricalPeriodType(StrEnum):
    """Record-level classification — distinguishes annual vs interim vs
    preliminary-unaudited vs synthetic TTM entries. More specific than
    the raw ``PeriodType`` label (``FY``/``H1``/``Q1``/...) because the
    analytical layer cares about audit posture + period length, not the
    issuer's internal fiscal-period label."""

    ANNUAL = "annual"
    INTERIM = "interim"
    PRELIMINARY = "preliminary"
    TTM = "ttm"


class HistoricalRecord(BaseSchema):
    """Single period observation sourced from one canonical_state (or
    synthesised, in the case of TTM). Multiple records compose a
    :class:`CompanyTimeSeries`. Financial + ratio + narrative fields
    are flattened here for convenience of downstream analytical passes
    that need only a handful of metrics.

    Phase 2 Sprint 2A: :attr:`period_relation` distinguishes records
    unpacked from a canonical state's primary period (``"primary"``)
    vs. its comparative periods (``"comparative"``). The dedupe pass
    prefers primary over comparative for the same ``period``.
    """

    period: str
    period_start: date
    period_end: date
    period_type: HistoricalPeriodType
    period_relation: Literal["primary", "comparative"] = "primary"
    fiscal_year_basis: str

    audit_status: AuditStatus
    source_canonical_state_id: str
    source_document_type: DocumentType | str
    source_document_date: date

    # Financial snapshot
    revenue: Decimal | None = None
    operating_income: Decimal | None = None
    sustainable_operating_income: Decimal | None = None
    net_income: Decimal | None = None
    # Phase 2 Sprint 2B — PBT + income_tax_expense + finance_income/
    # finance_expense anchor the DuPont 5-way decomposition (tax burden,
    # interest burden drivers).
    pbt: Decimal | None = None
    income_tax_expense: Decimal | None = None
    finance_income: Decimal | None = None
    finance_expense: Decimal | None = None
    ebitda: Decimal | None = None
    total_assets: Decimal | None = None
    total_equity: Decimal | None = None
    invested_capital: Decimal | None = None
    nopat: Decimal | None = None
    cash_and_equivalents: Decimal | None = None
    financial_debt: Decimal | None = None
    lease_liabilities: Decimal | None = None

    # Ratios snapshot
    operating_margin_reported: Decimal | None = None
    operating_margin_sustainable: Decimal | None = None
    roic_primary: Decimal | None = None
    roic_reported: Decimal | None = None
    roe: Decimal | None = None
    capex_revenue_ratio: Decimal | None = None

    # Phase 2 Sprint 2A.1 — cost of capital + QoE inputs that don't live
    # on the canonical state's per-period analysis block.
    wacc: Decimal | None = None
    cfo: Decimal | None = None
    accounts_receivable: Decimal | None = None
    non_recurring_items_share: Decimal | None = None

    # Phase 1.5.14 narrative snapshot
    narrative_summary: NarrativeSummary | None = None

    # Phase 2 Sprint 2A — analytical attachments
    economic_balance_sheet: EconomicBalanceSheet | None = None
    dupont_3way: DuPont3Way | None = None
    dupont_5way: DuPont5Way | None = None
    roic_decomposition: ROICDecomposition | None = None
    quality_of_earnings: QualityOfEarnings | None = None


_RestatementSeverity = Literal[
    "NEGLIGIBLE",
    "MINOR",
    "MATERIAL",
    "SIGNIFICANT",
    "ADVERSE",
]


_MetricClass = Literal["headline", "secondary", "memo"]
_RestatementDirection = Literal["UPWARD", "DOWNWARD"]
_RestatementPatternClass = Literal[
    "ONE_OFF_ADJUSTMENT",
    "POLICY_CHANGE",
    "RECLASSIFICATION",
    "ERROR_CORRECTION",
    "UNKNOWN",
]


class RestatementEvent(BaseSchema):
    """Emitted when the same period appears in two canonical states
    with materially different values.

    Phase 2 Sprint 2A widens the schema with ``period_relation``
    fields (primary vs comparative source of the disagreement) and a
    five-level :attr:`severity` classifier. The legacy ``is_material``
    flag stays for backwards compat; new callers should filter on
    ``severity != 'NEGLIGIBLE'``.

    Phase 2 Sprint 2B Part B adds ``metric_class`` (headline /
    secondary / memo) so the render can bucket events, and
    ``direction`` so pattern detection across a period comparison can
    classify systemic moves.
    """

    period: str
    source_a_canonical_id: str
    source_a_audit: AuditStatus
    source_a_value: Decimal
    source_a_period_relation: Literal["primary", "comparative"] | None = None
    source_b_canonical_id: str
    source_b_audit: AuditStatus
    source_b_value: Decimal
    source_b_period_relation: Literal["primary", "comparative"] | None = None
    metric: str
    metric_class: _MetricClass = "secondary"
    direction: _RestatementDirection | None = None
    delta_absolute: Decimal
    delta_pct: Decimal
    is_material: bool
    severity: _RestatementSeverity = "NEGLIGIBLE"
    detected_at: datetime


class RestatementPattern(BaseSchema):
    """Phase 2 Sprint 2B Part B — pattern summary for a set of
    :class:`RestatementEvent` rows that cover the same period
    comparison (same ``(source_a, source_b)`` pair). Classifies the
    systemic shape when 3+ events move in the same direction."""

    period_comparison: str
    event_count: int
    dominant_direction: Literal["UPWARD", "DOWNWARD", "MIXED"] = "MIXED"
    systemic_flag: bool = False
    classification: _RestatementPatternClass = "UNKNOWN"
    affected_metric_classes: list[_MetricClass] = Field(default_factory=list)


class RestatementNarrativeLink(BaseSchema):
    """Links a restatement pattern to a later period's narrative
    context that plausibly explains the restatement (e.g. accounting
    policy note)."""

    restatement_period: str
    narrative_period: str
    linked_theme: str
    relevance: Literal["DIRECT", "INFERRED", "NONE"] = "INFERRED"


class FiscalYearChangeEvent(BaseSchema):
    """Emitted when the ``(month, day)`` of period_end shifts between
    two consecutive annual records — typical signal of a fiscal-year
    end change (e.g. EuroEyes announcing Dec 31 → Mar 31)."""

    detected_at_period: str
    previous_fiscal_year_end: str
    new_fiscal_year_end: str
    transition_period_months: int
    detection_source: str


# ----------------------------------------------------------------------
# Notes evolution (minimal Phase-2 Sprint 1 scaffolding)
# ----------------------------------------------------------------------
class NoteDelta(BaseSchema):
    """A specific note whose value changed materially between periods."""

    note_title: str
    metric: str
    prior_value: Decimal
    current_value: Decimal
    delta_pct: Decimal


class NotesEvolution(BaseSchema):
    """Period-over-period note changes. Phase 2 Sprint 1 delivers the
    scaffolding; richer diffing lives in Sprint 2+ once canonical_state
    persists full note structure beyond the Module D decomposition
    cache."""

    period: str
    notes_added: list[str] = Field(default_factory=list)
    notes_removed: list[str] = Field(default_factory=list)
    notes_changed: list[NoteDelta] = Field(default_factory=list)


# ----------------------------------------------------------------------
# Narrative timeline — period-over-period narrative evolution
# ----------------------------------------------------------------------
class ThemeOccurrence(BaseSchema):
    theme_text: str
    periods_mentioned: list[str] = Field(default_factory=list)
    first_seen: str
    last_seen: str
    was_consistent: bool = False
    sources: list[str] = Field(default_factory=list)


class RiskOccurrence(BaseSchema):
    risk_text: str
    periods_mentioned: list[str] = Field(default_factory=list)
    first_seen: str
    last_seen: str
    was_consistent: bool = False
    sources: list[str] = Field(default_factory=list)


class GuidanceOccurrence(BaseSchema):
    guidance_text: str
    periods_mentioned: list[str] = Field(default_factory=list)
    first_seen: str
    last_seen: str
    was_consistent: bool = False


class CapitalAllocationOccurrence(BaseSchema):
    capital_allocation_text: str
    periods_mentioned: list[str] = Field(default_factory=list)
    first_seen: str
    last_seen: str
    was_consistent: bool = False


class NarrativeTimeline(BaseSchema):
    """Aggregated narrative-evolution view across records. Phase 1.5.14
    populates ``HistoricalRecord.narrative_summary``; this schema
    exposes period-over-period occurrence tracking."""

    themes_evolution: list[ThemeOccurrence] = Field(default_factory=list)
    risks_evolution: list[RiskOccurrence] = Field(default_factory=list)
    guidance_evolution: list[GuidanceOccurrence] = Field(default_factory=list)
    capital_allocation_evolution: list[CapitalAllocationOccurrence] = Field(
        default_factory=list
    )


# ----------------------------------------------------------------------
# Top-level time series
# ----------------------------------------------------------------------
class CompanyTimeSeries(BaseSchema):
    """Aggregate multi-period view for a company.

    Records sorted ascending by ``period_end``. Derivation artefacts
    (restatement_events, fiscal_year_changes, notes_evolution,
    narrative_timeline) sit alongside the records so the CLI + markdown
    exporter can render everything from a single object.
    """

    ticker: str
    identity: CompanyIdentity
    records: list[HistoricalRecord] = Field(default_factory=list)
    fiscal_year_changes: list[FiscalYearChangeEvent] = Field(
        default_factory=list
    )
    restatement_events: list[RestatementEvent] = Field(default_factory=list)
    restatement_patterns: list[RestatementPattern] = Field(
        default_factory=list
    )
    restatement_narrative_links: list[RestatementNarrativeLink] = Field(
        default_factory=list
    )
    notes_evolution: list[NotesEvolution] = Field(default_factory=list)
    narrative_timeline: NarrativeTimeline = Field(
        default_factory=NarrativeTimeline
    )

    # Phase 2 Sprint 2A — top-level analytics
    trends: TrendAnalysis | None = None
    investment_signal: InvestmentSignal | None = None

    generated_at: datetime
    source_canonical_state_ids: list[str] = Field(default_factory=list)
