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

    Phase 1.5.12: accepts case-insensitive input ("UNAUDITED" →
    :attr:`UNAUDITED`). The Claude.ai extractor prompt tends to emit
    uppercase enum values; rejecting them would be needlessly strict.
    """

    AUDITED = "audited"
    REVIEWED = "reviewed"  # auditor reviewed but not full audit
    UNAUDITED = "unaudited"

    @classmethod
    def _missing_(cls, value: Any) -> AuditStatus | None:
        if isinstance(value, str):
            lowered = value.lower()
            for member in cls:
                if member.value == lowered:
                    return member
        return None


# Phase 1.5.13.3 — canonical document-type → audit-status mapping used
# both by :class:`DocumentMetadata` (when a YAML omits the top-level
# ``audit_status``) and the pipeline selector (
# :func:`portfolio_thesis_engine.pipeline.coordinator._audit_from_document_type`).
# Centralising here avoids a circular import and keeps the heuristic
# in one place.
_AUDIT_STATUS_BY_DOC_TYPE: dict[str, str] = {
    "annual_report": "audited",
    "form_10k": "audited",
    "form_20f": "audited",
    "aif": "audited",
    "prc_annual": "audited",
    "interim_report": "reviewed",
    "form_10q": "reviewed",
    "form_6k": "reviewed",
    "quarterly_update": "reviewed",
    "preliminary_results": "unaudited",
    "preliminary_announcement": "unaudited",
    "investor_presentation": "unaudited",
    "earnings_call_transcript": "unaudited",
    "earnings_call": "unaudited",
    "earnings_call_slides": "unaudited",
    "press_release": "unaudited",
    # Legacy safest-default buckets.
    "wacc_inputs": "audited",
    "other": "audited",
    "unknown": "audited",
}


def audit_status_for_document_type(doc_type: str) -> str:
    """Return the document-type default audit status. Safe fallback:
    unknown / unmapped types default to ``"audited"``."""
    return _AUDIT_STATUS_BY_DOC_TYPE.get(doc_type.lower(), "audited")


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
    EARNINGS_CALL_TRANSCRIPT = "earnings_call_transcript"
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

    Phase 1.5.13.3 — optional :attr:`audit_status` per period. Interim
    reports commonly disclose one audit status per period (``H1_2025``
    unaudited / reviewed, ``H1_2024`` audited); the document-level
    :class:`DocumentMetadata.audit_status` is then derived from the
    *primary* period's flag via the 3-tier resolver.
    """

    period: str = Field(min_length=1)
    end_date: ISODate
    is_primary: bool = False
    audit_status: str | None = None
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

    @field_validator("preliminary_flag", mode="before")
    @classmethod
    def _coerce_bool_preliminary_flag(cls, value: Any) -> Any:
        """Phase 1.5.12 — ``preliminary_flag: false`` (common extractor
        output when the source is fully audited) is coerced to ``None``.
        Bare ``true`` is rejected — if the source is preliminary, the
        extractor MUST supply ``source_document`` + ``caveat_text`` so
        the display banner has content to render.
        """
        if value is False:
            return None
        if value is True:
            raise ValueError(
                "preliminary_flag: true is not allowed without "
                "source_document and caveat_text. Provide a mapping "
                "with at least those fields, or omit the flag entirely."
            )
        return value

    @model_validator(mode="before")
    @classmethod
    def _derive_audit_status(cls, values: Any) -> Any:
        """Phase 1.5.13.3 — same 3-tier audit-status resolution the
        pipeline selector uses:

        1. explicit top-level ``audit_status`` wins,
        2. primary ``fiscal_periods[*].audit_status`` (interim YAMLs
           typically carry it per-period),
        3. document-type default via
           :func:`audit_status_for_document_type`
           (``interim_report`` → ``reviewed``, ``preliminary_results``
           → ``unaudited``, ``annual_report`` → ``audited``).

        Fixes the cascading bug where interim YAMLs without a top-level
        ``audit_status`` defaulted to ``AUDITED`` at Pydantic load time
        and bypassed the Phase 1.5.11 cross-check skip.
        """
        if not isinstance(values, dict):
            return values
        if values.get("audit_status"):
            return values
        # Tier 2 — per-period fallback (primary, then first).
        fps = values.get("fiscal_periods") or []
        primary_audit: Any = None
        for fp in fps:
            if isinstance(fp, dict) and fp.get("is_primary"):
                primary_audit = fp.get("audit_status")
                break
        if primary_audit is None and fps and isinstance(fps[0], dict):
            primary_audit = fps[0].get("audit_status")
        if primary_audit:
            values["audit_status"] = str(primary_audit).lower()
            return values
        # Tier 3 — document-type default.
        doc_type = values.get("document_type")
        if doc_type:
            doc_label = (
                doc_type.value
                if hasattr(doc_type, "value")
                else str(doc_type)
            )
            values["audit_status"] = audit_status_for_document_type(doc_label)
        return values


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
    denomination.

    Phase 1.5.12 — :attr:`source_note` captures the note number the
    EPS footer points to (e.g. ``"13"``). Int values are coerced to
    str so legacy extractions (``source_note: 13``) validate; the
    field stays optional so older fixtures without it keep working.
    """

    basic_value: Decimal | None = None
    basic_unit: str | None = None
    diluted_value: Decimal | None = None
    diluted_unit: str | None = None
    basic_weighted_avg_shares: Decimal | None = None
    diluted_weighted_avg_shares: Decimal | None = None
    shares_unit: str | None = None
    source_note: str | None = None

    @field_validator("source_note", mode="before")
    @classmethod
    def _coerce_eps_source_note(cls, value: Any) -> Any:
        if value is None:
            return None
        if isinstance(value, bool):
            return str(value)
        if isinstance(value, int | float):
            return str(value)
        return value


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

    Phase 1.5.12 — :attr:`source_pages` accepts either ``int`` (wrapped
    to ``[int]``) or ``list[int]``. Some extractors emit a single int
    when the note occupies one page; the validator normalises without
    forcing the extractor to wrap.
    """

    note_number: str | None = None
    title: str = Field(min_length=1)
    source_pages: list[int] = Field(default_factory=list)
    tables: list[NoteTable] = Field(default_factory=list)
    narrative_summary: str | None = None

    @field_validator("source_pages", mode="before")
    @classmethod
    def _wrap_int_source_pages(cls, value: Any) -> Any:
        # Phase 1.5.12.1 — synthesized "absence" notes may carry
        # ``source_pages: None`` (the extractor acknowledging the note
        # exists in the report but not citing a page). Normalise to an
        # empty list instead of rejecting.
        if value is None:
            return []
        if isinstance(value, int) and not isinstance(value, bool):
            return [value]
        return value


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


# ======================================================================
# Phase 1.5.12 — Segments rich block + Operational-KPI block
# ======================================================================
class SegmentMeta(FlexibleSchema):
    """Qualitative context for segment disclosures (reporting basis,
    CODM reference, customer concentration, etc.).

    Phase 1.5.12.1 — ``extra="allow"`` (via :class:`FlexibleSchema`)
    so issuers can add fields like
    ``operating_profit_by_segment_disclosed`` or
    ``rationale_no_op_profit`` without schema edits. Also accepts
    ``segments_identified`` as an integer count (coerced to empty
    list) — count-only metadata carries no semantic value without the
    names, so we treat it as equivalent to "not disclosed in list form".
    """

    reporting_basis: str | None = None
    segments_identified: list[str] = Field(default_factory=list)
    codm: str | None = None
    non_segment_disclosures: str | None = None
    customer_concentration: str | None = None

    @field_validator("segments_identified", mode="before")
    @classmethod
    def _coerce_int_segments_identified(cls, value: Any) -> Any:
        if value is None:
            return []
        if isinstance(value, int) and not isinstance(value, bool):
            return []
        return value


class SegmentsBlock(FlexibleSchema):
    """Rich segment disclosure block.

    Accepts nested ``{period: {segment_name: metrics}}`` maps across
    multiple axes (geography, product, channel) plus per-period non-
    current-asset snapshots and EBITDA→PAT reconciliation bridges.
    Flexible — issuer-specific axes (``by_therapeutic_area``,
    ``by_business_line``, ...) survive without schema edits.

    When an extractor emits the legacy Phase-1 list shape, the
    :meth:`RawExtraction._normalise_segments` validator wraps the list
    into ``segment_meta.segments_identified`` so downstream callers
    see a consistent :class:`SegmentsBlock`.
    """

    by_geography: dict[str, dict[str, dict[str, Any]]] | None = None
    by_product: dict[str, dict[str, dict[str, Any]]] | None = None
    by_channel: dict[str, dict[str, dict[str, Any]]] | None = None
    non_current_assets_by_location: dict[str, dict[str, Decimal | None]] | None = None
    ebitda_to_pat_bridge: dict[str, dict[str, Decimal | None]] | None = None
    segment_meta: SegmentMeta | None = None
    # Legacy list-shape data persisted when the Phase-1 list form
    # arrives (callers that ignore SegmentsBlock can still reach it).
    legacy_periods: list[SegmentReporting] = Field(default_factory=list)


class OperationalKPIsBlock(FlexibleSchema):
    """Rich operational-KPI disclosure block.

    ``metrics`` keyed by metric name, value is a dict mapping period →
    raw value (``"H1_2025": 47`` or ``"total_revenue_hkd": "377.1M"``).
    ``metric_sources`` is a parallel map for attribution; Phase
    1.5.12.1 widens the value type to ``str | list[str]`` so the
    extractor can cite multiple notes / sections at once
    (``primary_notes: ["6", "7", "13"]``). ``targets`` is optional —
    populated when the extractor captures KPI targets alongside
    actuals.

    When the legacy Phase-1 ``list[OperationalKPI]`` shape arrives,
    :meth:`RawExtraction._normalise_kpis` folds each entry into
    :attr:`legacy_kpis`.
    """

    metrics: dict[str, dict[str, Any]] = Field(default_factory=dict)
    metric_sources: dict[str, str | list[str]] = Field(default_factory=dict)
    targets: dict[str, dict[str, Any]] | None = None
    # Legacy list form persisted verbatim for callers that iterate it.
    legacy_kpis: list[OperationalKPI] = Field(default_factory=list)

    @field_validator("metric_sources", mode="before")
    @classmethod
    def _validate_metric_sources(cls, value: Any) -> Any:
        if value is None:
            return {}
        if not isinstance(value, dict):
            return value
        for key, val in value.items():
            if isinstance(val, (str, list)):
                continue
            raise ValueError(
                f"metric_sources[{key!r}] must be str or list[str], "
                f"got {type(val).__name__}"
            )
        return value


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
# Narrative — Phase 1.5.12 structured types
# ======================================================================
_Confidence = Literal["high", "medium", "low"]
_Severity = Literal["high", "medium", "low"]


class NarrativeItem(BaseSchema):
    """Phase 1.5.12 — structured narrative entry (key theme, forward-
    looking statement, Q&A highlight, ...). Plain strings are auto-
    promoted to ``NarrativeItem(text=...)`` by the parent :class:`Narrative`
    validators, so legacy ``list[str]`` fixtures validate unchanged.
    """

    text: str = Field(min_length=1)
    tag: str | None = None
    supporting_facts: list[str] = Field(default_factory=list)
    source: str | None = None
    page: int | None = None
    confidence: _Confidence | None = None


class RiskItem(BaseSchema):
    """Phase 1.5.12 — structured risk disclosure."""

    risk: str = Field(min_length=1)
    detail: str | None = None
    severity: _Severity | None = None
    source: str | None = None
    page: int | None = None


class GuidanceItem(BaseSchema):
    """Phase 1.5.12 — structured forward guidance / target disclosure.

    Supersedes the Phase-1 ``GuidanceChangeItem`` (which had only
    metric / old / new / direction). Legacy dicts with that shape are
    accepted by the :class:`Narrative._normalise_guidance_items`
    validator and translated into ``statement`` + ``direction`` fields.
    """

    metric: str = Field(min_length=1)
    direction: str | None = None
    value: str | None = None
    period: str | None = None
    statement: str | None = None
    source: str | None = None


class CapitalAllocationItem(BaseSchema):
    """Phase 1.5.12 — capital-allocation commentary entry."""

    area: str = Field(min_length=1)
    detail: str | None = None
    amount: str | None = None
    period: str | None = None
    source: str | None = None


# Phase-1 legacy names preserved as thin aliases so existing imports keep
# working. Tests / pipeline code pinning the old names continues to work;
# the schema fields below use the new superset types.
GuidanceChangeItem = GuidanceItem
QAItem = NarrativeItem


class NarrativeContent(BaseSchema):
    """Qualitative content from narrative documents (earnings calls,
    MD&A, investor presentations).

    Phase 1.5.12 — every list accepts either structured items
    (:class:`NarrativeItem` / :class:`RiskItem` / :class:`GuidanceItem`
    / :class:`CapitalAllocationItem`) or plain strings. Plain strings
    are auto-promoted via field validators so Phase-1 fixtures stay
    valid.
    """

    key_themes: list[NarrativeItem] = Field(default_factory=list)
    guidance_changes: list[GuidanceItem] = Field(default_factory=list)
    risks_mentioned: list[RiskItem] = Field(default_factory=list)
    q_and_a_highlights: list[NarrativeItem] = Field(default_factory=list)
    forward_looking_statements: list[NarrativeItem] = Field(default_factory=list)
    capital_allocation_comments: list[CapitalAllocationItem] = Field(default_factory=list)

    # ── Backward-compat promotion validators ─────────────────────
    @field_validator(
        "key_themes", "forward_looking_statements", mode="before"
    )
    @classmethod
    def _promote_strings_to_narrative_items(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        promoted: list[Any] = []
        for item in value:
            if isinstance(item, str):
                promoted.append({"text": item})
            elif isinstance(item, dict) and "text" not in item:
                # Heuristic mapping for the Claude.ai extractor output
                # {theme|statement, fact?, source?}.
                text = (
                    item.get("theme")
                    or item.get("statement")
                    or item.get("fact")
                    or ""
                )
                promoted.append(
                    {
                        "text": text or "(empty)",
                        "tag": item.get("theme"),
                        "supporting_facts": (
                            [item["fact"]] if item.get("fact") else []
                        ),
                        "source": item.get("source"),
                        "page": item.get("page"),
                    }
                )
            else:
                promoted.append(item)
        return promoted

    @field_validator("q_and_a_highlights", mode="before")
    @classmethod
    def _promote_qa_items(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        promoted: list[Any] = []
        for item in value:
            if isinstance(item, str):
                promoted.append({"text": item})
            elif isinstance(item, dict) and "text" not in item:
                # Legacy QAItem shape {question, answer, speaker, topic}.
                q = item.get("question", "")
                a = item.get("answer", "")
                text = (
                    f"Q: {q}\nA: {a}" if q and a
                    else (q or a or "(empty)")
                )
                promoted.append(
                    {
                        "text": text,
                        "tag": item.get("speaker") or item.get("topic"),
                        "source": item.get("source"),
                        "page": item.get("page"),
                    }
                )
            else:
                promoted.append(item)
        return promoted

    @field_validator("risks_mentioned", mode="before")
    @classmethod
    def _promote_risks(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        promoted: list[Any] = []
        for item in value:
            if isinstance(item, str):
                promoted.append({"risk": item})
            elif isinstance(item, dict) and "risk" not in item:
                risk = (
                    item.get("theme")
                    or item.get("name")
                    or item.get("title")
                    or item.get("detail")
                    or "(unspecified)"
                )
                promoted.append(
                    {
                        "risk": risk,
                        "detail": item.get("detail"),
                        "severity": item.get("severity"),
                        "source": item.get("source"),
                        "page": item.get("page"),
                    }
                )
            else:
                promoted.append(item)
        return promoted

    @field_validator("capital_allocation_comments", mode="before")
    @classmethod
    def _promote_capital_allocation(cls, value: Any) -> Any:
        if not isinstance(value, list):
            return value
        promoted: list[Any] = []
        for item in value:
            if isinstance(item, str):
                promoted.append({"area": "General", "detail": item})
            elif isinstance(item, dict) and "area" not in item:
                area = (
                    item.get("category")
                    or item.get("bucket")
                    or item.get("theme")
                    or "General"
                )
                promoted.append(
                    {
                        "area": area,
                        "detail": item.get("detail") or item.get("statement"),
                        "amount": item.get("amount"),
                        "period": item.get("period"),
                        "source": item.get("source"),
                    }
                )
            else:
                promoted.append(item)
        return promoted

    @field_validator("guidance_changes", mode="before")
    @classmethod
    def _promote_guidance(cls, value: Any) -> Any:
        """Legacy shapes accepted:

        - plain str ``"Revenue to grow 10 %"`` → ``metric="unspecified"``
          + ``statement=str``.
        - ``{guidance, statement, period, source}`` (Claude.ai extractor):
          → ``metric=guidance``.
        - ``{metric, old, new, direction}`` (Phase 1 ``GuidanceChangeItem``)
          → ``metric`` kept, ``statement=f"{old} → {new}"``.
        """
        if not isinstance(value, list):
            return value
        promoted: list[Any] = []
        for item in value:
            if isinstance(item, str):
                promoted.append({"metric": "unspecified", "statement": item})
            elif isinstance(item, dict) and "metric" not in item:
                metric = (
                    item.get("guidance")
                    or item.get("kpi")
                    or item.get("measure")
                    or "unspecified"
                )
                promoted.append(
                    {
                        "metric": metric,
                        "direction": item.get("direction"),
                        "value": item.get("value"),
                        "period": item.get("period"),
                        "statement": item.get("statement"),
                        "source": item.get("source"),
                    }
                )
            elif isinstance(item, dict) and (
                "old" in item or "new" in item
            ):
                # Phase-1 GuidanceChangeItem shape — bridge old/new into
                # a single statement for the new schema.
                old = item.get("old") or ""
                new = item.get("new") or ""
                statement = (
                    f"{old} → {new}".strip(" →") if (old or new) else None
                )
                promoted.append(
                    {
                        "metric": item["metric"],
                        "direction": item.get("direction"),
                        "statement": statement,
                    }
                )
            else:
                promoted.append(item)
        return promoted


# ======================================================================
# Top-level
# ======================================================================
class RawExtraction(BaseSchema):
    """Complete human-produced extraction for one source document.

    Phase 1.5.12 — ``segments`` and ``operational_kpis`` accept either
    the legacy Phase-1 list shape (preserved verbatim on
    :attr:`SegmentsBlock.legacy_periods` /
    :attr:`OperationalKPIsBlock.legacy_kpis`) or the richer dict shape
    emitted by the Claude.ai extractor (by_geography / metrics /
    metric_sources / ...).
    """

    metadata: DocumentMetadata
    income_statement: dict[str, IncomeStatementPeriod] = Field(default_factory=dict)
    balance_sheet: dict[str, BalanceSheetPeriod] = Field(default_factory=dict)
    cash_flow: dict[str, CashFlowPeriod] = Field(default_factory=dict)
    notes: list[Note] = Field(default_factory=list)
    segments: SegmentsBlock = Field(default_factory=SegmentsBlock)
    historical: HistoricalDataSeries | None = None
    operational_kpis: OperationalKPIsBlock = Field(
        default_factory=lambda: OperationalKPIsBlock()
    )
    narrative: NarrativeContent | None = None

    @field_validator("segments", mode="before")
    @classmethod
    def _normalise_segments(cls, value: Any) -> Any:
        if value is None:
            return SegmentsBlock()
        if isinstance(value, list):
            # Legacy Phase-1 form: list[SegmentReporting].
            return SegmentsBlock(legacy_periods=value)
        return value

    @field_validator("operational_kpis", mode="before")
    @classmethod
    def _normalise_kpis(cls, value: Any) -> Any:
        if value is None:
            return OperationalKPIsBlock()
        if isinstance(value, list):
            return OperationalKPIsBlock(legacy_kpis=value)
        return value

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
            # Phase 1.5.12.1 — BS + CF required only for audited /
            # reviewed documents. Preliminary investor presentations
            # commonly disclose IS only; the pipeline surfaces the
            # consequences (W.CAPEX / W.CF / BS-identity SKIP) via the
            # validator + banner rather than blocking at load time.
            is_unaudited = meta.audit_status == AuditStatus.UNAUDITED
            if not is_unaudited and primary.period not in self.balance_sheet:
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
