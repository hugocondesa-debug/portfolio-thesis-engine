"""Raw extraction — human/Claude.ai boundary.

Phase 1.5.3 migration: moved from a fixed-field statements schema to
an **as-reported structured** schema. The extractor captures the
company's line items verbatim, in reading order, without mapping them
to a predefined field taxonomy. Classification (operational /
non-operational, working capital / financial, etc.) happens 100%
downstream in the extraction modules.

Rationale: the fixed-field schema forced the extractor to make
judgements during extraction ("does 'Selling expenses' map to
selling_marketing or general_administrative?"). Each such decision
was a source of error. The observed EuroEyes extraction double-
counted D&A because the extractor filled ``depreciation_amortization``
from Note 5 while D&A was already embedded in the opex line subtotal.

New model:

- **`LineItem`** carries one row of a statement with its verbatim
  label, value, reading order, subtotal flag, and optional section
  (for BS / CF grouping). The extractor preserves the PDF's
  structure; the validator walks the list checking subtotals sum
  from preceding non-subtotals.

- **`Note`** carries zero or more **`NoteTable`**s (columns + rows)
  with a verbatim title. Modules scan notes by title pattern
  (``/income tax|taxation/``, ``/leases/``, etc.) and walk the table
  rows looking for known row labels.

- Segments, historical, operational KPIs follow the same spirit:
  preserve what the company reports, with verbatim labels.

Schema scope carried forward from Phase 1.5:

- 42 :class:`DocumentType` values, four buckets (numeric, narrative,
  regulatory, industry-specific).
- Full narrative section for :class:`ExtractionType.NARRATIVE`
  documents.
- :class:`DocumentMetadata` + :class:`FiscalPeriodData`.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from portfolio_thesis_engine.schemas.base import BaseSchema, FlexibleSchema
from portfolio_thesis_engine.schemas.common import (
    Currency,
    ISODate,
    Ticker,
)


# ======================================================================
# Enums
# ======================================================================
class AuditStatus(StrEnum):
    """Audit status of the source document.

    Phase 1.5.11: drives validator relaxation, cross-check skip, and
    confidence downgrade. Defaults to :attr:`AUDITED` for backwards
    compatibility — every extraction produced pre-1.5.11 is treated
    as audited.
    """

    AUDITED = "audited"
    REVIEWED = "reviewed"  # auditor reviewed but not full audit
    UNAUDITED = "unaudited"


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
    # Phase 1.5.11 — investor-presentation / pre-audit preliminary
    # figures (broader than the formal regulatory announcement).
    PRELIMINARY_RESULTS = "preliminary_results"
    AIF = "aif"
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
    PILLAR_3 = "pillar_3"
    SFCR = "sfcr"
    ICAAP = "icaap"
    ORSA = "orsa"
    NI_43_101 = "ni_43_101"

    # --- Catchall ------------------------------------------------
    OTHER = "other"


class ExtractionType(StrEnum):
    """Whether the document produces numeric statements or narrative
    content."""

    NUMERIC = "numeric"
    NARRATIVE = "narrative"


UnitScale = Literal["units", "thousands", "millions"]
PeriodType = Literal["FY", "H1", "H2", "Q1", "Q2", "Q3", "Q4", "YTD", "LTM"]

# Balance-sheet section grouping (verbatim labels the extractor uses
# on :class:`LineItem.section`). Cash-flow section grouping reuses
# ``operating`` / ``investing`` / ``financing`` / ``fx_effect`` /
# ``subtotal``. Income statements may leave ``section`` unset.
BalanceSheetSection = Literal[
    "current_assets",
    "non_current_assets",
    "total_assets",
    "current_liabilities",
    "non_current_liabilities",
    "total_liabilities",
    "equity",
]
CashFlowSection = Literal[
    "operating",
    "investing",
    "financing",
    "fx_effect",
    "subtotal",
]


# ======================================================================
# Metadata
# ======================================================================
class FiscalPeriodData(BaseSchema):
    """One row in :class:`DocumentMetadata.fiscal_periods`.

    ``period`` is the label keying the IS / BS / CF dicts; ``end_date``
    is the last calendar day of the period. ``period_type`` lets
    downstream logic reason about year-vs-interim scope.
    """

    period: str = Field(min_length=1)
    end_date: ISODate
    is_primary: bool = False
    period_type: PeriodType = "FY"


class PreliminaryFlag(BaseSchema):
    """Phase 1.5.11 — preliminary / pre-audit provenance for display +
    restatement tracking."""

    pending_audit: bool = True
    expected_audit_date: ISODate | None = None
    source_document: str = Field(
        default="",
        description=(
            "Where the preliminary data came from — e.g. "
            "'Investor presentation dated 2026-03-15', "
            "'HKEX announcement 2026-03-10'."
        ),
    )
    caveat_text: str = Field(
        default="",
        description=(
            "Human-readable caveat to surface in the display banner. "
            "Pulled verbatim from the source presentation where possible."
        ),
    )


class DocumentMetadata(FlexibleSchema):
    """Identity + provenance for one source document.

    Flexible — extractors may add arbitrary metadata fields
    (``source_file_name``, upstream-ingestion IDs, etc.) without
    schema edits.

    Phase 1.5.11 — :attr:`audit_status` drives validator relaxation,
    cross-check skip, confidence downgrade and the unaudited display
    banner. Default is :attr:`AuditStatus.AUDITED` so Phase-1
    extractions keep their behaviour unchanged.
    """

    ticker: Ticker
    company_name: str = Field(min_length=1)
    document_type: DocumentType
    extraction_type: ExtractionType
    reporting_currency: Currency
    unit_scale: UnitScale
    fiscal_year: int | None = Field(default=None, ge=1900, le=2100)
    extraction_date: ISODate
    extractor: str = "human + Claude.ai Project"
    source_file_sha256: str | None = None
    extraction_version: int = Field(default=1, ge=1)
    extraction_notes: str = ""
    fiscal_periods: list[FiscalPeriodData] = Field(default_factory=list)
    audit_status: AuditStatus = AuditStatus.AUDITED
    preliminary_flag: PreliminaryFlag | None = None


# ======================================================================
# Statement line items
# ======================================================================
class LineItem(BaseSchema):
    """One row of a financial statement, captured verbatim.

    ``order`` preserves reading order — the validator walks items in
    order to verify subtotals. ``is_subtotal`` flags lines like
    "Gross profit", "Operating profit", "Profit before tax", "Profit
    for the year", and BS subtotals ("Total current assets", "Total
    assets", "Total equity"). The validator verifies that each
    subtotal equals the running sum of preceding non-subtotal items
    (scoped to the section, for BS / CF).
    """

    order: int = Field(ge=0)
    label: str = Field(min_length=1)
    value: Decimal | None = None
    is_subtotal: bool = False
    skip_in_waterfall: bool = False
    """True for **nested subtotals** that are sub-sums of adjacent
    lines and should NOT reset the waterfall running sum — e.g. IFRS
    IS "Finance income/(expenses), net" which sums the preceding
    finance lines but doesn't participate in the OP→PBT→NI waterfall.

    The validator still verifies the nested subtotal equals the sum
    of its component lines (via running_sum − last_waterfall_anchor);
    it just doesn't reset the waterfall anchor.
    """
    section: str | None = None
    source_note: str | None = None
    """Note reference as reported. Free-form string so composite /
    sub-note identifiers round-trip verbatim: ``"13"``, ``"3.3, 35"``,
    ``"29(d)"``, ``"32(a)"``, ``"38(b)"``, etc.

    A YAML-scalar integer (``source_note: 5``) is coerced to
    ``"5"`` so legacy extractions parse without edits.
    """
    source_page: int | None = Field(default=None, ge=0)
    notes: str | None = None

    @field_validator("source_note", mode="before")
    @classmethod
    def _coerce_source_note(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, str):
            return value
        if isinstance(value, bool):  # bool is int — exclude
            return str(value)
        if isinstance(value, int | float):
            return str(value)
        return value


class ProfitAttribution(BaseSchema):
    """Standard IS attribution footer: profit for the year split
    between equity holders of the parent and NCI."""

    parent: Decimal | None = None
    non_controlling_interests: Decimal | None = None
    total: Decimal | None = None


class EarningsPerShare(BaseSchema):
    """Standard IS EPS footer. Units captured verbatim ("HK cents",
    "USD", etc.) so downstream code can reason about the
    denomination."""

    basic_value: Decimal | None = None
    basic_unit: str | None = None
    diluted_value: Decimal | None = None
    diluted_unit: str | None = None
    basic_weighted_avg_shares: Decimal | None = None
    diluted_weighted_avg_shares: Decimal | None = None
    shares_unit: str | None = None


class IncomeStatementPeriod(FlexibleSchema):
    """Income statement for one fiscal period. Flexible — allows
    extras like ``total_comprehensive_income_attribution``,
    ``continuing_vs_discontinued_split``, etc."""

    reporting_period_label: str | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    profit_attribution: ProfitAttribution | None = None
    earnings_per_share: EarningsPerShare | None = None


class BalanceSheetPeriod(FlexibleSchema):
    """Balance sheet for one fiscal period. Items are grouped by
    ``section`` (current_assets / non_current_assets / equity / etc.)
    so the validator can verify section-level sums. Flexible — extras
    like ``as_at_date_note`` / ``currency_translation_disclosure``
    survive."""

    period_end_date: ISODate | None = None
    line_items: list[LineItem] = Field(default_factory=list)


class CashFlowPeriod(FlexibleSchema):
    """Cash flow statement for one fiscal period. Items are grouped by
    ``section`` (operating / investing / financing / fx_effect /
    subtotal). Flexible — extras like ``cash_reconciliation_note``
    survive."""

    reporting_period_label: str | None = None
    line_items: list[LineItem] = Field(default_factory=list)


# ======================================================================
# Notes — free-form tabular capture
# ======================================================================
class NoteTable(BaseSchema):
    """One table inside a note. Captured as columns + rows, with an
    optional sub-caption.

    Row cells are ``list[Any]``: text labels stay strings, numeric
    cells are coerced to :class:`Decimal` by a validator so downstream
    modules don't have to guess (YAML-quoted numbers arrive as
    strings otherwise)."""

    table_label: str | None = None
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    unit_note: str | None = None

    @field_validator("rows", mode="before")
    @classmethod
    def _coerce_numeric_cells(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        coerced: list[list[Any]] = []
        for row in value:
            if not isinstance(row, list):
                coerced.append(row)
                continue
            coerced.append([_maybe_decimal(cell) for cell in row])
        return coerced


class Note(FlexibleSchema):
    """One note from the document, verbatim.

    ``note_number`` preserves the issuer's numbering ("5", "5(a)",
    "3.1"). Modules find relevant notes by matching ``title``
    against regex patterns and iterate the ``tables`` list looking
    for known row labels. Flexible — allows extra fields like
    ``narrative_summary_fr`` or sector-specific annotations.
    """

    note_number: str | None = None
    title: str = Field(min_length=1)
    source_pages: list[int] = Field(default_factory=list)
    tables: list[NoteTable] = Field(default_factory=list)
    narrative_summary: str | None = None


# ======================================================================
# Segments + historical + KPIs
# ======================================================================
class SegmentMetrics(BaseSchema):
    """One segment's metrics for one period. ``metrics`` is free-form
    so different issuers can surface different per-segment disclosures
    (revenue, gross profit, op income, EBITDA, headcount, ...)."""

    segment_name: str = Field(min_length=1)
    metrics: dict[str, Decimal | None] = Field(default_factory=dict)


class SegmentReporting(FlexibleSchema):
    """All segment data for one reporting period along one axis
    (geography / product / business_line / ...).

    Flexible — allows extras like ``source_note``,
    ``reconciliation_to_group``, ``extraction_caveat``,
    ``reconciliation_ebitda_to_profit`` that some filings
    provide alongside the segment tables.
    """

    period: str = Field(min_length=1)
    segment_type: str = Field(min_length=1)
    segments: list[SegmentMetrics] = Field(default_factory=list)
    inter_segment_eliminations: dict[str, Decimal | None] | None = None


class HistoricalDataSeries(BaseSchema):
    """Multi-year summary table. Source + year list + per-metric
    parallel value arrays. Null entries preserve alignment when a
    metric wasn't disclosed for a specific year."""

    source: str = Field(min_length=1)
    years: list[int] = Field(default_factory=list)
    metrics: dict[str, list[Decimal | None]] = Field(default_factory=dict)


class OperationalKPI(FlexibleSchema):
    """One operational KPI. Free-form so companies can disclose
    sector-specific metrics without a schema change.

    ``values`` entries are coerced: numeric-looking strings become
    :class:`Decimal`; non-numeric strings stay as strings; ``None``
    passes through. Flexible — extras like per-metric ``notes``
    or ``methodology`` commentary survive."""

    metric_label: str = Field(min_length=1)
    source: str = Field(min_length=1)
    unit: str | None = None
    values: dict[str, Decimal | str | None] = Field(default_factory=dict)

    @field_validator("values", mode="before")
    @classmethod
    def _coerce_kpi_values(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            return value
        return {k: _maybe_decimal(v) for k, v in value.items()}


# ======================================================================
# Narrative
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
    MD&A, investor presentations). Phase 1.5.3 keeps the shape; Phase
    2 wires the processing pipeline."""

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
    notes: list[Note] = Field(default_factory=list)
    segments: list[SegmentReporting] = Field(default_factory=list)
    historical: HistoricalDataSeries | None = None
    operational_kpis: list[OperationalKPI] = Field(default_factory=list)
    narrative: NarrativeContent | None = None

    # ── Validators ──────────────────────────────────────────────
    @model_validator(mode="after")
    def validate_basics(self) -> RawExtraction:
        """Extraction-type-driven completeness.

        Numeric documents must have at least one fiscal period with
        IS + BS populated for the primary period with non-empty
        line_items on the IS. Narrative documents can omit
        statements but must have at least one of the narrative
        content buckets populated.
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
            if not self.income_statement[primary.period].line_items:
                raise ValueError(
                    f"numeric extraction: primary period {primary.period!r} "
                    f"income_statement has no line_items"
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


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _maybe_decimal(value: Any) -> Any:
    """Coerce ``value`` to :class:`Decimal` if it looks numeric; else
    return it unchanged. Used by the ``NoteTable.rows`` and
    ``OperationalKPI.values`` validators to normalise YAML-quoted
    numbers at schema-validation time.

    - ``Decimal`` / ``int`` / ``float`` → coerced.
    - ``str`` that parses as ``Decimal`` → coerced.
    - Non-numeric strings / ``None`` / other → unchanged.
    """
    if isinstance(value, Decimal):
        return value
    if isinstance(value, bool):  # bool is int — exclude
        return value
    if isinstance(value, int | float):
        return Decimal(str(value))
    if isinstance(value, str):
        try:
            return Decimal(value)
        except Exception:  # noqa: BLE001
            return value
    return value
