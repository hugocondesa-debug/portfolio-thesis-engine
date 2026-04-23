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

from pydantic import Field

from portfolio_thesis_engine.schemas.base import BaseSchema
from portfolio_thesis_engine.schemas.company import CompanyIdentity
from portfolio_thesis_engine.schemas.ficha import NarrativeSummary
from portfolio_thesis_engine.schemas.raw_extraction import (
    AuditStatus,
    DocumentType,
)


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
    that need only a handful of metrics."""

    period: str
    period_start: date
    period_end: date
    period_type: HistoricalPeriodType
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

    # Phase 1.5.14 narrative snapshot
    narrative_summary: NarrativeSummary | None = None


class RestatementEvent(BaseSchema):
    """Emitted when the same period appears in two canonical states
    with materially different values (|Δ %| > 1 %). Source A is
    typically the earlier / lower-audit source (e.g. preliminary);
    source B is the eventual audited restatement."""

    period: str
    source_a_canonical_id: str
    source_a_audit: AuditStatus
    source_a_value: Decimal
    source_b_canonical_id: str
    source_b_audit: AuditStatus
    source_b_value: Decimal
    metric: str
    delta_absolute: Decimal
    delta_pct: Decimal
    is_material: bool
    detected_at: datetime


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
    notes_evolution: list[NotesEvolution] = Field(default_factory=list)
    narrative_timeline: NarrativeTimeline = Field(
        default_factory=NarrativeTimeline
    )

    generated_at: datetime
    source_canonical_state_ids: list[str] = Field(default_factory=list)
