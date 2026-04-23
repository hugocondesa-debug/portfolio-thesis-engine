"""Phase 2 Sprint 1 — :class:`HistoricalNormalizer`.

Walks every canonical_state persisted for a ticker, turns each period
(primary + comparatives) into a :class:`HistoricalRecord`, de-duplicates
by ``(period, audit_priority)`` preferring higher audit posture, emits
:class:`RestatementEvent` for material deltas between audited /
preliminary sources, detects fiscal-year changes, and constructs a TTM
record when interim + prior-year interim + base annual are all present.

Read-only: never mutates canonical states, never writes back.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from portfolio_thesis_engine.schemas.company import (
    CanonicalCompanyState,
    CompanyIdentity,
)
from portfolio_thesis_engine.schemas.historicals import (
    CapitalAllocationOccurrence,
    CompanyTimeSeries,
    FiscalYearChangeEvent,
    GuidanceOccurrence,
    HistoricalPeriodType,
    HistoricalRecord,
    NarrativeTimeline,
    RestatementEvent,
    RiskOccurrence,
    ThemeOccurrence,
)
from portfolio_thesis_engine.schemas.raw_extraction import (
    AuditStatus,
    DocumentType,
    audit_status_for_document_type,
)
from portfolio_thesis_engine.storage.yaml_repo import CompanyStateRepository

# ----------------------------------------------------------------------
# Constants
# ----------------------------------------------------------------------
_RESTATEMENT_MATERIALITY_PCT = Decimal("0.5")
_RESTATEMENT_METRICS = (
    "revenue",
    "operating_income",
    "net_income",
    "total_assets",
    "total_equity",
)


def _classify_restatement_severity(delta_pct: Decimal) -> str:
    abs_pct = abs(delta_pct)
    if abs_pct < Decimal("0.5"):
        return "NEGLIGIBLE"
    if abs_pct < Decimal("1"):
        return "MINOR"
    if abs_pct < Decimal("5"):
        return "MATERIAL"
    if abs_pct < Decimal("10"):
        return "SIGNIFICANT"
    return "ADVERSE"
_AUDIT_PRIORITY = {
    AuditStatus.AUDITED: 0,
    AuditStatus.REVIEWED: 1,
    AuditStatus.UNAUDITED: 2,
}

_PERIOD_YEAR_PATTERN = re.compile(r"(\d{4})")


# ----------------------------------------------------------------------
# Normalizer
# ----------------------------------------------------------------------
class HistoricalNormalizer:
    """Build a :class:`CompanyTimeSeries` for a ticker by iterating
    every stored canonical state.

    The normalizer is read-only — it never writes back to the
    canonical-state repository. Persisting the derived time series is
    the CLI caller's concern.
    """

    def __init__(
        self, state_repo: CompanyStateRepository | None = None
    ) -> None:
        self.state_repo = state_repo or CompanyStateRepository()

    # ------------------------------------------------------------------
    def normalize(self, ticker: str) -> CompanyTimeSeries:
        states = self._load_all_states(ticker)
        if not states:
            return self._empty_series(ticker)

        identity = self._pick_identity(states)
        records: list[HistoricalRecord] = []
        for state in states:
            records.append(self._record_from_primary(state))
            records.extend(self._records_from_comparatives(state))

        deduped, restatements = _dedupe_with_restatements(
            records, primary_wins=True
        )
        ttm = _build_ttm_record(deduped)
        if ttm is not None:
            deduped.append(ttm)
        sorted_records = sorted(deduped, key=lambda r: r.period_end)

        # Phase 2 Sprint 2A — analytical enrichment. Populates
        # economic_balance_sheet + DuPont + ROIC decomposition + QoE
        # per record; trends + investment_signal at the top level.
        _enrich_records_with_analytics(sorted_records, states, ticker=ticker)
        fy_changes = _detect_fiscal_year_changes(sorted_records)
        narrative_timeline = _build_narrative_timeline(sorted_records)
        trends = _compute_trends_wrapper(sorted_records)
        latest_roic = _latest_roic_decomposition(sorted_records)
        latest_qoe = _latest_qoe(sorted_records)
        signal = _synthesise_signal(
            sorted_records, trends, latest_roic, latest_qoe
        )

        return CompanyTimeSeries(
            ticker=ticker,
            identity=identity,
            records=sorted_records,
            fiscal_year_changes=fy_changes,
            restatement_events=restatements,
            narrative_timeline=narrative_timeline,
            trends=trends,
            investment_signal=signal,
            generated_at=datetime.now(UTC),
            source_canonical_state_ids=[s.extraction_id for s in states],
        )

    # ------------------------------------------------------------------
    # State loading
    # ------------------------------------------------------------------
    def _load_all_states(
        self, ticker: str
    ) -> list[CanonicalCompanyState]:
        """Every stored canonical state for ``ticker``, deduped by
        ``(primary_period, source_document_type)`` keeping the newest
        by ``extraction_date``.

        Phase 2 Sprint 1.1 — raw version lists contain every re-run of
        ``pte process`` (36+ timestamped variants for a single AR in
        real workflows). Deduping here keeps the time-series semantic
        ("one observation per period+source") and drops the noise
        before downstream record construction.
        """
        versions = self.state_repo.list_versions(ticker)
        all_states: list[CanonicalCompanyState] = []
        for version in versions:
            state = self.state_repo.get_version(ticker, version)
            if state is not None:
                all_states.append(state)

        grouped: dict[tuple[str, str], CanonicalCompanyState] = {}
        for state in all_states:
            key = (
                _infer_primary_period_label(state),
                _resolve_source_document_type(state),
            )
            current = grouped.get(key)
            if current is None or state.extraction_date > current.extraction_date:
                grouped[key] = state

        return sorted(grouped.values(), key=lambda s: s.extraction_date)

    def _pick_identity(
        self, states: list[CanonicalCompanyState]
    ) -> CompanyIdentity:
        """Use the most recent state's identity — that's the one the
        rest of the system treats as canonical for the ticker."""
        return states[-1].identity

    def _empty_series(self, ticker: str) -> CompanyTimeSeries:
        return CompanyTimeSeries(
            ticker=ticker,
            identity=CompanyIdentity(
                ticker=ticker,
                name=ticker,
                reporting_currency="USD",  # type: ignore[arg-type]
                profile="P1",  # type: ignore[arg-type]
                fiscal_year_end_month=12,
                country_domicile="XX",
                exchange="UNKNOWN",
            ),
            records=[],
            generated_at=datetime.now(UTC),
            source_canonical_state_ids=[],
        )

    # ------------------------------------------------------------------
    # Record building
    # ------------------------------------------------------------------
    def _record_from_primary(
        self, state: CanonicalCompanyState
    ) -> HistoricalRecord:
        period_label = _infer_primary_period_label(state)
        period_end = _parse_period_end(state.as_of_date) or _period_end_from_label(
            period_label,
            fallback_month=state.identity.fiscal_year_end_month,
        )
        period_type = _classify_period_type(
            period_label=period_label,
            audit_status=state.validation.confidence_rating,
            document_type=getattr(state.methodology, "source_document_type", None),
            audit_status_value=getattr(state.methodology, "audit_status", "audited"),
        )
        period_start = _period_start_for(period_end, period_type)
        audit_status = _resolve_audit_status(state)
        return _build_record(
            state=state,
            period_label=period_label,
            period_start=period_start,
            period_end=period_end,
            period_type=period_type,
            audit_status=audit_status,
            primary=True,
        )

    def _records_from_comparatives(
        self, state: CanonicalCompanyState
    ) -> list[HistoricalRecord]:
        """Phase 2 Sprint 2A — walk every reclassified statement after
        the primary ([0]) and emit one record per comparative. NOPAT
        bridge + invested capital + ratios remain primary-only
        (AnalysisDeriver hasn't been multi-period-ified yet); comparative
        records expose revenue / operating_income / net_income / total
        assets / equity from the IS + BS line lists.
        """
        if len(state.reclassified_statements) <= 1:
            return []
        primary_audit = _resolve_audit_status(state)
        doc_type = _resolve_source_document_type(state)
        source_id = state.extraction_id
        source_date = (
            state.extraction_date.date()
            if isinstance(state.extraction_date, datetime)
            else date.today()
        )
        out: list[HistoricalRecord] = []
        for rs in state.reclassified_statements[1:]:
            label = rs.period.label
            period_end = _period_end_from_label(
                label,
                fallback_month=state.identity.fiscal_year_end_month,
            )
            period_type = _classify_period_type(
                period_label=label,
                audit_status=state.validation.confidence_rating,
                document_type=doc_type,
                audit_status_value=primary_audit.value,
            )
            period_start = _period_start_for(period_end, period_type)
            out.append(
                _build_comparative_record(
                    rs=rs,
                    period_label=label,
                    period_start=period_start,
                    period_end=period_end,
                    period_type=period_type,
                    audit_status=primary_audit,
                    source_id=source_id,
                    source_document_type=doc_type,
                    source_document_date=source_date,
                )
            )
        return out


# ----------------------------------------------------------------------
# Helpers — record construction
# ----------------------------------------------------------------------
def _resolve_audit_status(state: CanonicalCompanyState) -> AuditStatus:
    """Phase 2 Sprint 1.1 — 3-tier audit resolution mirrored from the
    :class:`DocumentMetadata` schema.

    Canonical states persisted before Phase 1.5.13.3 stored the
    Pydantic default ``"audited"`` even for interim / preliminary
    sources, so trusting the stored value blindly mis-classifies old
    artefacts. Policy:

    1. If the stored value is explicitly ``reviewed`` / ``unaudited``,
       honour it (the analyst set it on purpose).
    2. Otherwise, consult the document-type default
       (``interim_report`` → ``reviewed``, ``investor_presentation`` →
       ``unaudited``, ``annual_report`` → ``audited``, ...).
    3. Fall through to :class:`AuditStatus.AUDITED` when neither the
       stored value nor the document type is informative.
    """
    stored = str(
        getattr(state.methodology, "audit_status", "audited") or "audited"
    ).lower()
    if stored in ("reviewed", "unaudited"):
        try:
            return AuditStatus(stored)
        except ValueError:
            pass
    doc_type = _resolve_source_document_type(state)
    derived = audit_status_for_document_type(doc_type)
    try:
        return AuditStatus(derived)
    except ValueError:
        return AuditStatus.AUDITED


def _resolve_source_document_type(state: CanonicalCompanyState) -> str:
    """Phase 2 Sprint 1.1 — infer document type for legacy canonical
    states that pre-date Phase 1.5.11's :attr:`MethodologyMetadata.
    source_document_type` field.

    Resolution order:

    1. ``methodology.source_document_type`` when populated.
    2. Primary period label heuristic — ``FY*`` → ``annual_report``,
       ``H1*`` / ``H2*`` / ``Q*`` → ``interim_report``.
    3. Final fallback ``"annual_report"`` — the safest default for
       canonical states that only carry a plain ``as_of_date``.
    """
    stored = getattr(state.methodology, "source_document_type", None)
    if stored:
        return str(stored).lower()
    label = _infer_primary_period_label(state)
    upper = label.upper()
    if upper.startswith(("H1", "H2", "Q")):
        return "interim_report"
    if "PRELIMINARY" in upper:
        return "preliminary_results"
    return "annual_report"


def _infer_primary_period_label(state: CanonicalCompanyState) -> str:
    if state.reclassified_statements:
        return state.reclassified_statements[0].period.label
    return state.as_of_date


def _parse_period_end(iso_string: str) -> date | None:
    try:
        return date.fromisoformat(iso_string)
    except (TypeError, ValueError):
        return None


def _period_end_from_label(
    label: str, *, fallback_month: int = 12
) -> date:
    """Best-effort period_end derivation from a label like ``FY2024``
    or ``H1_2025``. Defaults to Dec 31 for FY, Jun 30 for H1."""
    year_match = _PERIOD_YEAR_PATTERN.search(label)
    year = int(year_match.group(1)) if year_match else datetime.now(UTC).year
    upper = label.upper()
    if upper.startswith("H1"):
        return date(year, 6, 30)
    if upper.startswith("H2"):
        return date(year, 12, 31)
    if upper.startswith("Q1"):
        return date(year, 3, 31)
    if upper.startswith("Q2"):
        return date(year, 6, 30)
    if upper.startswith("Q3"):
        return date(year, 9, 30)
    if upper.startswith("Q4"):
        return date(year, 12, 31)
    # FY default — fiscal year end month.
    month = fallback_month
    try:
        # Approximate month-end via last day calc: move to 1st of
        # next month, minus one day.
        if month == 12:
            return date(year, 12, 31)
        return date(year, month + 1, 1) - timedelta(days=1)
    except ValueError:
        return date(year, 12, 31)


def _period_start_for(
    period_end: date, period_type: HistoricalPeriodType
) -> date:
    if period_type == HistoricalPeriodType.INTERIM:
        # Half-year default — 6 months before period_end.
        return (period_end - timedelta(days=180)).replace(day=1)
    # Annual / preliminary / TTM: 12-month window ending at period_end.
    try:
        start_year = period_end.year - 1
        start_month = period_end.month + 1
        if start_month > 12:
            start_month -= 12
            start_year += 1
        return date(start_year, start_month, 1)
    except ValueError:
        return period_end - timedelta(days=365)


def _classify_period_type(
    period_label: str,
    audit_status: str,
    document_type: str | None,
    audit_status_value: str,
) -> HistoricalPeriodType:
    upper = period_label.upper()
    doc = (document_type or "").lower()
    if audit_status_value == AuditStatus.UNAUDITED.value:
        return HistoricalPeriodType.PRELIMINARY
    if upper.startswith(("H1", "H2", "Q")) or "interim" in doc:
        return HistoricalPeriodType.INTERIM
    return HistoricalPeriodType.ANNUAL


def _build_record(
    *,
    state: CanonicalCompanyState,
    period_label: str,
    period_start: date,
    period_end: date,
    period_type: HistoricalPeriodType,
    audit_status: AuditStatus,
    primary: bool,
) -> HistoricalRecord:
    _ = primary
    bridge = (
        state.analysis.nopat_bridge_by_period[0]
        if state.analysis.nopat_bridge_by_period
        else None
    )
    ic = (
        state.analysis.invested_capital_by_period[0]
        if state.analysis.invested_capital_by_period
        else None
    )
    ratios = (
        state.analysis.ratios_by_period[0]
        if state.analysis.ratios_by_period
        else None
    )
    revenue = _first_matching_line(
        state,
        labels=("revenue", "total revenue", "sales", "turnover"),
        statement="income_statement",
    )
    # Phase 2 Sprint 1.1 — the NOPATBridge stores op_income only
    # post-1.5.9.1; legacy canonical states persist NOPAT but leave the
    # field empty. Fall back to the IS line walk so the record surfaces
    # the same value the analyst sees in the original statement.
    operating_income_value = bridge.operating_income if bridge is not None else None
    if operating_income_value is None:
        operating_income_value = _first_matching_line(
            state,
            labels=(
                "operating profit",
                "operating income",
                "profit from operations",
            ),
            statement="income_statement",
            subtotal_ok=True,
        )
    net_income = _first_matching_line(
        state,
        labels=("profit for the year", "profit for the period",
                "net income", "net profit"),
        statement="income_statement",
        subtotal_ok=True,
    )
    # Phase 2 Sprint 2A.1 — canonical BS line lists don't persist
    # "Total assets"/"Total equity" subtotal rows (issuers report them
    # only in narrative summaries). Fall back to category-sum when the
    # subtotal line is absent so DuPont has the denominators it needs.
    total_assets = _first_matching_line(
        state,
        labels=("total assets",),
        statement="balance_sheet",
        subtotal_ok=True,
    )
    if total_assets is None:
        total_assets = _sum_bs_categories(
            state, {"non_current_assets", "current_assets"}
        )
    total_equity = _first_matching_line(
        state,
        labels=("total equity", "total shareholders' equity",
                "equity attributable to owners"),
        statement="balance_sheet",
        subtotal_ok=True,
    )
    if total_equity is None:
        total_equity = _sum_bs_categories(state, {"equity"})

    # Phase 2 Sprint 2A.1 — CFO, AR, non-recurring share feed Sprint 2A
    # QoE scoring and DuPont. CFO = "Cash generated from operations" +
    # taxes paid + interest received (operating section net). Trade
    # receivables come from the BS line list. Non-recurring share =
    # |non_recurring_operating_items| ÷ reported operating income.
    cfo = _derive_cfo(state)
    accounts_receivable = _first_matching_line(
        state,
        labels=("trade receivables", "trade and other receivables",
                "accounts receivable"),
        statement="balance_sheet",
        subtotal_ok=False,
    )
    non_recurring_share: Decimal | None = None
    if bridge is not None and bridge.non_recurring_operating_items and operating_income_value:
        non_recurring_share = (
            abs(bridge.non_recurring_operating_items) / abs(operating_income_value)
        )

    # Phase 2 Sprint 1.1 — always resolve to a non-'unknown' label via
    # the heuristic helper. Legacy canonical states without an explicit
    # source_document_type fall back to period-label inference.
    doc_type_label = _resolve_source_document_type(state)
    try:
        source_doc_type: DocumentType | str = DocumentType(doc_type_label)
    except ValueError:
        source_doc_type = str(doc_type_label)

    narrative_summary = None
    if state.narrative_context is not None:
        # We re-use the Ficha condenser so the record's narrative
        # matches what downstream consumers see.
        from portfolio_thesis_engine.ficha.composer import _condense_narrative

        narrative_summary = _condense_narrative(state.narrative_context)

    return HistoricalRecord(
        period=period_label,
        period_start=period_start,
        period_end=period_end,
        period_type=period_type,
        period_relation="primary",
        fiscal_year_basis=f"calendar_{period_end.month:02d}",
        audit_status=audit_status,
        source_canonical_state_id=state.extraction_id,
        source_document_type=source_doc_type,
        source_document_date=(
            state.extraction_date.date()
            if isinstance(state.extraction_date, datetime)
            else date.today()
        ),
        revenue=revenue,
        operating_income=operating_income_value,
        sustainable_operating_income=(
            bridge.operating_income_sustainable if bridge is not None else None
        ),
        net_income=net_income,
        ebitda=bridge.ebitda if bridge is not None else None,
        total_assets=total_assets,
        total_equity=total_equity,
        invested_capital=ic.invested_capital if ic is not None else None,
        nopat=bridge.nopat if bridge is not None else None,
        cash_and_equivalents=ic.financial_assets if ic is not None else None,
        financial_debt=ic.bank_debt if ic is not None else None,
        lease_liabilities=ic.lease_liabilities if ic is not None else None,
        operating_margin_reported=(
            ratios.operating_margin if ratios is not None else None
        ),
        operating_margin_sustainable=(
            ratios.sustainable_operating_margin
            if ratios is not None
            else None
        ),
        roic_primary=ratios.roic if ratios is not None else None,
        roic_reported=(
            ratios.roic_reported if ratios is not None else None
        ),
        roe=ratios.roe if ratios is not None else None,
        cfo=cfo,
        accounts_receivable=accounts_receivable,
        non_recurring_items_share=non_recurring_share,
        narrative_summary=narrative_summary,
    )


def _build_comparative_record(
    *,
    rs: Any,
    period_label: str,
    period_start: date,
    period_end: date,
    period_type: HistoricalPeriodType,
    audit_status: AuditStatus,
    source_id: str,
    source_document_type: str,
    source_document_date: date,
) -> HistoricalRecord:
    """Construct a comparative record from a single ReclassifiedStatements
    entry (no NOPAT bridge / IC / ratios available — primary-only for
    those in Sprint 2A)."""
    from portfolio_thesis_engine.schemas.raw_extraction import DocumentType

    def _find(lines: list[Any], labels: tuple[str, ...]) -> Decimal | None:
        normalised = tuple(lbl.lower() for lbl in labels)
        for line in lines:
            if line.label.lower() in normalised:
                return line.value
        return None

    try:
        source_doc_enum: DocumentType | str = DocumentType(source_document_type)
    except ValueError:
        source_doc_enum = source_document_type

    total_assets = _find(rs.balance_sheet, ("total assets",))
    if total_assets is None:
        total_assets = _sum_bs_category_from_lines(
            rs.balance_sheet, {"non_current_assets", "current_assets"}
        )
    total_equity = _find(
        rs.balance_sheet,
        (
            "total equity",
            "total shareholders' equity",
            "equity attributable to owners",
        ),
    )
    if total_equity is None:
        total_equity = _sum_bs_category_from_lines(
            rs.balance_sheet, {"equity"}
        )

    revenue = _find(
        rs.income_statement,
        ("revenue", "total revenue", "sales", "turnover"),
    )
    operating_income = _find(
        rs.income_statement,
        (
            "operating profit",
            "operating income",
            "profit from operations",
        ),
    )
    # Phase 2 Sprint 2A.1 — derive operating_margin_reported for
    # comparatives so trend analysis can compute margin_delta_bps against
    # the primary period.
    operating_margin = (
        (operating_income / revenue) * Decimal("100")
        if operating_income is not None and revenue not in (None, Decimal("0"))
        else None
    )

    return HistoricalRecord(
        period=period_label,
        period_start=period_start,
        period_end=period_end,
        period_type=period_type,
        period_relation="comparative",
        fiscal_year_basis=f"calendar_{period_end.month:02d}",
        audit_status=audit_status,
        source_canonical_state_id=source_id,
        source_document_type=source_doc_enum,
        source_document_date=source_document_date,
        revenue=revenue,
        operating_income=operating_income,
        net_income=_find(
            rs.income_statement,
            (
                "profit for the year",
                "profit for the period",
                "net income",
                "net profit",
            ),
        ),
        total_assets=total_assets,
        total_equity=total_equity,
        accounts_receivable=_find(
            rs.balance_sheet,
            ("trade receivables", "trade and other receivables",
             "accounts receivable"),
        ),
        operating_margin_reported=operating_margin,
    )


def _first_matching_line(
    state: CanonicalCompanyState,
    labels: tuple[str, ...],
    statement: str,
    subtotal_ok: bool = False,
) -> Decimal | None:
    if not state.reclassified_statements:
        return None
    rs = state.reclassified_statements[0]
    if statement == "income_statement":
        lines = rs.income_statement
    elif statement == "balance_sheet":
        lines = rs.balance_sheet
    elif statement == "cash_flow":
        lines = rs.cash_flow
    else:
        return None
    normalised = tuple(lbl.lower() for lbl in labels)
    for line in lines:
        if not subtotal_ok and getattr(line, "is_adjusted", False):
            continue
        if line.label.lower() in normalised:
            return line.value
    return None


def _sum_bs_categories(
    state: CanonicalCompanyState, categories: set[str]
) -> Decimal | None:
    """Phase 2 Sprint 2A.1 — sum BS lines whose ``category`` is in
    ``categories``. Returns ``None`` when no line matches."""
    if not state.reclassified_statements:
        return None
    total: Decimal | None = None
    for line in state.reclassified_statements[0].balance_sheet:
        if line.category in categories:
            total = line.value if total is None else total + line.value
    return total


def _sum_bs_category_from_lines(
    lines: list[Any], categories: set[str]
) -> Decimal | None:
    total: Decimal | None = None
    for line in lines:
        if line.category in categories:
            total = line.value if total is None else total + line.value
    return total


_CFO_LABELS = (
    "cash generated from operations",
    "net cash from operating activities",
    "net cash generated from operating activities",
    "net cash inflow from operating activities",
    "cash flow from operating activities",
)


def _derive_cfo(state: CanonicalCompanyState) -> Decimal | None:
    """Extract CFO from the canonical cash-flow statement.

    Prefer explicit labels like ``"Net cash from operating activities"``.
    Fall back to ``"Cash generated from operations" + interest received
    − income tax paid`` — the sub-total + reconciliation items as many
    IFRS issuers (EuroEyes) present them.
    """
    if not state.reclassified_statements:
        return None
    lines = state.reclassified_statements[0].cash_flow
    normalised = tuple(lbl for lbl in _CFO_LABELS)
    for line in lines:
        if line.label.lower() in normalised:
            return line.value
    # Fallback: sum of operating-section lines.
    operating_total: Decimal | None = None
    for line in lines:
        if line.category == "operating":
            operating_total = (
                line.value if operating_total is None else operating_total + line.value
            )
    return operating_total


# ----------------------------------------------------------------------
# Restatement detection
# ----------------------------------------------------------------------
_RELATION_PRIORITY = {"primary": 0, "comparative": 1}


def _dedupe_with_restatements(
    records: list[HistoricalRecord],
    primary_wins: bool = True,
) -> tuple[list[HistoricalRecord], list[RestatementEvent]]:
    """Group by period, pick the winner per the priority hierarchy
    (period_relation → audit_status), compare every non-winner against
    the winner and emit :class:`RestatementEvent` on material deltas.

    Phase 2 Sprint 2A — with ``primary_wins=True`` the dedupe honours
    the Sprint 2A convention that a period's primary observation
    (from an AR whose PRIMARY period is that period) beats any later
    comparative (from an AR whose primary was *another* period but
    included this one as a prior-year comparison column).
    """
    grouped: dict[str, list[HistoricalRecord]] = {}
    for record in records:
        grouped.setdefault(record.period, []).append(record)

    def _sort_key(r: HistoricalRecord) -> tuple[int, int, float]:
        relation_rank = (
            _RELATION_PRIORITY.get(r.period_relation, 2)
            if primary_wins
            else 0
        )
        audit_rank = _AUDIT_PRIORITY.get(r.audit_status, 3)
        # Most recent source_document_date tiebreaker (negated so newer
        # sorts earlier).
        date_rank = -r.source_document_date.toordinal()
        return relation_rank, audit_rank, date_rank

    deduped: list[HistoricalRecord] = []
    restatements: list[RestatementEvent] = []
    for _period, group in grouped.items():
        group.sort(key=_sort_key)
        winner = group[0]
        deduped.append(winner)
        for secondary in group[1:]:
            restatements.extend(_compare_records(winner, secondary))
    return deduped, restatements


def _compare_records(
    primary: HistoricalRecord, secondary: HistoricalRecord
) -> list[RestatementEvent]:
    """Phase 2 Sprint 2A — produce one :class:`RestatementEvent` per
    metric whose value disagrees by ≥ 0.5 % between ``primary`` (the
    winner) and ``secondary``. Severity classified on five levels;
    NEGLIGIBLE deltas are skipped."""
    events: list[RestatementEvent] = []
    for metric in _RESTATEMENT_METRICS:
        a = getattr(primary, metric)
        b = getattr(secondary, metric)
        if a is None or b is None or b == 0:
            continue
        delta_abs = a - b
        delta_pct = abs(delta_abs / b) * Decimal("100")
        severity = _classify_restatement_severity(delta_pct)
        if severity == "NEGLIGIBLE":
            continue
        events.append(
            RestatementEvent(
                period=primary.period,
                source_a_canonical_id=secondary.source_canonical_state_id,
                source_a_audit=secondary.audit_status,
                source_a_value=b,
                source_a_period_relation=secondary.period_relation,
                source_b_canonical_id=primary.source_canonical_state_id,
                source_b_audit=primary.audit_status,
                source_b_value=a,
                source_b_period_relation=primary.period_relation,
                metric=metric,
                delta_absolute=delta_abs,
                delta_pct=delta_pct,
                is_material=severity in ("MATERIAL", "SIGNIFICANT", "ADVERSE"),
                severity=severity,
                detected_at=datetime.now(UTC),
            )
        )
    return events


# ----------------------------------------------------------------------
# Fiscal year change detection
# ----------------------------------------------------------------------
def _detect_fiscal_year_changes(
    records: list[HistoricalRecord],
) -> list[FiscalYearChangeEvent]:
    annuals = sorted(
        [r for r in records if r.period_type == HistoricalPeriodType.ANNUAL],
        key=lambda r: r.period_end,
    )
    events: list[FiscalYearChangeEvent] = []
    for i in range(1, len(annuals)):
        prev = annuals[i - 1]
        curr = annuals[i]
        if (prev.period_end.month, prev.period_end.day) != (
            curr.period_end.month,
            curr.period_end.day,
        ):
            transition_months = (
                (curr.period_end.year - prev.period_end.year) * 12
                + (curr.period_end.month - prev.period_end.month)
            )
            events.append(
                FiscalYearChangeEvent(
                    detected_at_period=curr.period,
                    previous_fiscal_year_end=(
                        f"{prev.period_end.month:02d}-{prev.period_end.day:02d}"
                    ),
                    new_fiscal_year_end=(
                        f"{curr.period_end.month:02d}-{curr.period_end.day:02d}"
                    ),
                    transition_period_months=transition_months,
                    detection_source=curr.source_canonical_state_id,
                )
            )
    return events


# ----------------------------------------------------------------------
# TTM construction
# ----------------------------------------------------------------------
def _build_ttm_record(
    records: list[HistoricalRecord],
) -> HistoricalRecord | None:
    """TTM = latest_interim + (base_annual − prior_year_interim).

    Skips silently when any of the three operands is missing — a
    ``None`` return is the caller's signal to not append anything.
    """
    interims = sorted(
        [r for r in records if r.period_type == HistoricalPeriodType.INTERIM],
        key=lambda r: r.period_end,
        reverse=True,
    )
    if not interims:
        return None
    latest_interim = interims[0]

    prior_interim: HistoricalRecord | None = None
    for candidate in interims[1:]:
        if (candidate.period_end.month, candidate.period_end.day) == (
            latest_interim.period_end.month,
            latest_interim.period_end.day,
        ) and candidate.period_end.year == latest_interim.period_end.year - 1:
            prior_interim = candidate
            break
    if prior_interim is None:
        return None

    base_annual: HistoricalRecord | None = None
    for candidate in records:
        if candidate.period_type != HistoricalPeriodType.ANNUAL:
            continue
        if candidate.period_end.year == prior_interim.period_end.year:
            base_annual = candidate
            break
    if base_annual is None:
        return None

    def _ttm(metric: str) -> Decimal | None:
        a = getattr(base_annual, metric)
        b = getattr(prior_interim, metric)
        c = getattr(latest_interim, metric)
        if a is None or b is None or c is None:
            return None
        return a - b + c

    ttm_label = f"TTM_{latest_interim.period_end.strftime('%b_%Y')}"
    return HistoricalRecord(
        period=ttm_label,
        period_start=base_annual.period_end + timedelta(days=1) - timedelta(days=365),
        period_end=latest_interim.period_end,
        period_type=HistoricalPeriodType.TTM,
        fiscal_year_basis=base_annual.fiscal_year_basis,
        audit_status=AuditStatus.UNAUDITED,
        source_canonical_state_id="derived:ttm",
        source_document_type="derived",
        source_document_date=latest_interim.source_document_date,
        revenue=_ttm("revenue"),
        operating_income=_ttm("operating_income"),
        sustainable_operating_income=_ttm("sustainable_operating_income"),
        net_income=_ttm("net_income"),
        ebitda=_ttm("ebitda"),
        total_assets=latest_interim.total_assets,
        total_equity=latest_interim.total_equity,
        invested_capital=latest_interim.invested_capital,
        nopat=_ttm("nopat"),
        cash_and_equivalents=latest_interim.cash_and_equivalents,
        financial_debt=latest_interim.financial_debt,
        lease_liabilities=latest_interim.lease_liabilities,
    )


# ----------------------------------------------------------------------
# Narrative timeline
# ----------------------------------------------------------------------
def _build_narrative_timeline(
    records: list[HistoricalRecord],
) -> NarrativeTimeline:
    """Aggregate narrative items across records by exact text equality.
    ``was_consistent`` is true when the item appears in every record
    (sorted by period_end) between its first and last observation."""
    records_with_narrative = [
        r for r in records
        if r.narrative_summary is not None
    ]
    if not records_with_narrative:
        return NarrativeTimeline()

    period_order = [r.period for r in records_with_narrative]

    def _aggregate(
        extractor: callable,
    ) -> dict[str, tuple[list[str], list[str]]]:
        acc: dict[str, tuple[list[str], list[str]]] = {}
        for record in records_with_narrative:
            items = extractor(record.narrative_summary)
            for item in items:
                periods, sources = acc.setdefault(item, ([], []))
                if record.period not in periods:
                    periods.append(record.period)
                    sources.append(
                        str(record.source_document_type)
                    )
        return acc

    def _consistency(periods: list[str]) -> bool:
        if len(periods) < 2:
            return len(periods) == len(period_order)
        first = period_order.index(periods[0])
        last = period_order.index(periods[-1])
        return periods == period_order[first : last + 1]

    themes = _aggregate(lambda n: n.key_themes)
    risks = _aggregate(lambda n: n.primary_risks)
    guidance = _aggregate(lambda n: n.management_guidance)
    cap_alloc = _aggregate(lambda n: n.capital_allocation)

    theme_occurrences = [
        ThemeOccurrence(
            theme_text=text,
            periods_mentioned=list(periods),
            first_seen=periods[0],
            last_seen=periods[-1],
            was_consistent=_consistency(periods),
            sources=list(sources),
        )
        for text, (periods, sources) in themes.items()
    ]
    risk_occurrences = [
        RiskOccurrence(
            risk_text=text,
            periods_mentioned=list(periods),
            first_seen=periods[0],
            last_seen=periods[-1],
            was_consistent=_consistency(periods),
            sources=list(sources),
        )
        for text, (periods, sources) in risks.items()
    ]
    guidance_occurrences = [
        GuidanceOccurrence(
            guidance_text=text,
            periods_mentioned=list(periods),
            first_seen=periods[0],
            last_seen=periods[-1],
            was_consistent=_consistency(periods),
        )
        for text, (periods, _sources) in guidance.items()
    ]
    cap_alloc_occurrences = [
        CapitalAllocationOccurrence(
            capital_allocation_text=text,
            periods_mentioned=list(periods),
            first_seen=periods[0],
            last_seen=periods[-1],
            was_consistent=_consistency(periods),
        )
        for text, (periods, _sources) in cap_alloc.items()
    ]

    return NarrativeTimeline(
        themes_evolution=theme_occurrences,
        risks_evolution=risk_occurrences,
        guidance_evolution=guidance_occurrences,
        capital_allocation_evolution=cap_alloc_occurrences,
    )


# ----------------------------------------------------------------------
# Phase 2 Sprint 2A — analytical enrichment
# ----------------------------------------------------------------------
def _enrich_records_with_analytics(
    records: list[HistoricalRecord],
    states: list[CanonicalCompanyState],
    ticker: str | None = None,
) -> None:
    """Populate economic_balance_sheet + DuPont + ROIC decomposition +
    quality_of_earnings on every record that has the inputs."""
    from portfolio_thesis_engine.analytical.analyze import (
        compute_dupont_3way,
        compute_qoe,
        compute_roic_decomposition,
    )
    from portfolio_thesis_engine.analytical.economic_bs import (
        EconomicBSBuilder,
    )

    state_by_id: dict[str, CanonicalCompanyState] = {
        s.extraction_id: s for s in states
    }
    bs_builder = EconomicBSBuilder()

    # Phase 2 Sprint 2A.1 — WACC flows from the ticker's
    # wacc_inputs.md. Loading is best-effort: tickers without the file
    # simply keep ``record.wacc = None`` and ROIC decomposition skips the
    # spread calculation.
    wacc_pct = _load_wacc_for_ticker(ticker)

    # Build a secondary lookup: (canonical_state_id, period_label) → rs
    # so comparative records can find their comparative
    # ReclassifiedStatements without walking the list twice.
    comparative_rs_by_key: dict[tuple[str, str], Any] = {}
    for state in states:
        for rs in state.reclassified_statements[1:]:
            comparative_rs_by_key[(state.extraction_id, rs.period.label)] = rs

    # Track prior-year annual record per metric so YoY-sensitive scoring
    # (CFO/NI ratios, AR growth) has a reference point when wired.
    records_by_year: dict[int, HistoricalRecord] = {
        r.period_end.year: r
        for r in records
        if r.period_type == HistoricalPeriodType.ANNUAL
    }

    for record in records:
        state = state_by_id.get(record.source_canonical_state_id)

        # WACC attaches regardless of IC availability.
        if wacc_pct is not None:
            record.wacc = wacc_pct

        # DuPont + ROIC need no canonical-state-side lookup beyond record
        # fields; QoE uses CFO/non-recurring share fed from the record.
        record.dupont_3way = compute_dupont_3way(record)
        record.roic_decomposition = compute_roic_decomposition(
            record, wacc_pct=wacc_pct
        )

        prior = records_by_year.get(record.period_end.year - 1)
        record.quality_of_earnings = compute_qoe(
            record,
            cfo=record.cfo,
            prior_revenue=prior.revenue if prior is not None else None,
            prior_ar=prior.accounts_receivable if prior is not None else None,
            non_recurring_items_share=record.non_recurring_items_share,
        )

        # Economic BS:
        #   - primary records: full view (uses IC block)
        #   - comparative records: BS-only view (IC block absent)
        #   - TTM / derived records: skipped (no source canonical state)
        if state is None:
            continue
        if record.period_relation == "primary":
            record.economic_balance_sheet = bs_builder.build(
                state, record.period
            )
            continue
        rs = comparative_rs_by_key.get(
            (record.source_canonical_state_id, record.period)
        )
        if rs is not None and rs.balance_sheet:
            record.economic_balance_sheet = bs_builder.build(
                state, record.period
            )


def _load_wacc_for_ticker(ticker: str | None) -> Decimal | None:
    """Phase 2 Sprint 2A.1 — look up ``wacc_inputs.md`` for the ticker
    and return ``WACCInputs.wacc`` as a percentage. Silently returns
    ``None`` when the ticker is missing, the file is absent, or the file
    fails to parse — analytical enrichment must not crash when WACC
    inputs haven't been prepared."""
    if not ticker:
        return None
    try:
        from portfolio_thesis_engine.ingestion.wacc_parser import (
            parse_wacc_inputs,
        )
        from portfolio_thesis_engine.shared.config import settings
        from portfolio_thesis_engine.storage.base import normalise_ticker

        path = (
            settings.data_dir
            / "documents"
            / normalise_ticker(ticker)
            / "wacc_inputs"
            / "wacc_inputs.md"
        )
        if not path.exists():
            return None
        wacc_inputs = parse_wacc_inputs(path)
        return wacc_inputs.wacc
    except Exception:
        return None


def _compute_trends_wrapper(
    records: list[HistoricalRecord],
) -> Any:
    from portfolio_thesis_engine.analytical.analyze import compute_trends

    return compute_trends(records)


def _latest_roic_decomposition(records: list[HistoricalRecord]) -> Any:
    for record in reversed(records):
        if record.roic_decomposition is not None:
            return record.roic_decomposition
    return None


def _latest_qoe(records: list[HistoricalRecord]) -> Any:
    for record in reversed(records):
        if record.quality_of_earnings is not None:
            return record.quality_of_earnings
    return None


def _synthesise_signal(
    records: list[HistoricalRecord], trends: Any, latest_roic: Any, latest_qoe: Any
) -> Any:
    from portfolio_thesis_engine.analytical.analyze import (
        synthesise_investment_signal,
    )

    return synthesise_investment_signal(records, trends, latest_roic, latest_qoe)


__all__ = [
    "HistoricalNormalizer",
    "_build_ttm_record",
    "_build_narrative_timeline",
    "_compare_records",
    "_dedupe_with_restatements",
    "_detect_fiscal_year_changes",
]
