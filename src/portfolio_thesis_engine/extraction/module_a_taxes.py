"""Module A — Operating Taxes (subset A.1–A.5).

Phase 1.5.3 rewrite: modules classify locally now that the schema is
as-reported-structured. There is no longer a typed ``TaxNote`` with a
closed ``classification`` enum per reconciling item. Module A:

1. Finds the tax note by title pattern (``/income tax|taxation/``).
2. Within the note, finds a rate-reconciliation table by table_label
   pattern (``/reconciliation|effective.*rate/``) OR the first table
   whose columns look like a reconciliation (amount column + one
   label column).
3. Parses each row as ``(description, amount)``.
4. Classifies each row locally (operating vs non-operating) using
   label keywords — exactly the same classification intent as Phase
   1.5, but the signal now lives on the label, not a schema field.

Scope shipped here:

- **A.1** tax hierarchy → emit operating tax rate adjustment.
- **A.2.0** materiality test → skip split when non-op items are tiny.
- **A.2.1–A.2.5** operating vs non-operating classification by
  label keyword.
- **A.4** cash taxes — if a CF line matches the label
  ``/cash taxes paid|income taxes paid/``, log the delta vs
  reported tax.
- **A.5** BS treatment note.

OUT of Phase 1: A.3 DTA/DTL (requires BS walk post-Phase 2), A.6+
(TLCF valuation, sector extensions).

Deterministic — no LLM calls.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from portfolio_thesis_engine.extraction.base import ExtractionContext, ExtractionModule
from portfolio_thesis_engine.llm.anthropic_provider import AnthropicProvider
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.common import Source
from portfolio_thesis_engine.schemas.company import ModuleAdjustment
from portfolio_thesis_engine.schemas.raw_extraction import Note, NoteTable, RawExtraction

_TAX_NOTE_PATTERN = re.compile(r"income tax|taxation", re.IGNORECASE)
_RECON_TABLE_PATTERN = re.compile(
    r"reconciliation|effective.*rate|rate.*reconciliation", re.IGNORECASE
)
_STATUTORY_ROW_PATTERN = re.compile(
    r"tax at (the )?statutory|statutory (tax )?rate|tax calculated",
    re.IGNORECASE,
)
_EFFECTIVE_ROW_PATTERN = re.compile(
    r"effective (tax )?rate|effective rate\b|tax (expense|charge) for the",
    re.IGNORECASE,
)
_PBT_LABEL = re.compile(
    r"profit before (tax|taxation)|income before (income )?tax", re.IGNORECASE
)
_INCOME_TAX_LABEL = re.compile(
    r"^income tax|^taxation|tax (expense|charge)", re.IGNORECASE
)
_CASH_TAX_LABEL = re.compile(
    r"cash (taxes|income tax)|(income )?taxes paid", re.IGNORECASE
)

# Label heuristics → non-operating bucket.
_NON_OPERATING_LABEL_KEYWORDS: tuple[str, ...] = (
    "goodwill",
    "impairment",
    "disposal",
    "restructuring",
    "one-off",
    "one off",
    "prior year",
    "prior-year",
    "acquisition",
    "settlement",
    "litigation",
    "discontinued",
    "gain on",
    "loss on",
)

_MATERIALITY_THRESHOLD = Decimal("0.05")


class ModuleATaxes(ExtractionModule):
    """Operating taxes reclassification from a :class:`RawExtraction`."""

    module_id = "A"

    def __init__(
        self,
        llm: AnthropicProvider,
        cost_tracker: CostTracker,
    ) -> None:
        self.llm = llm
        self.cost_tracker = cost_tracker

    # ------------------------------------------------------------------
    async def apply(self, context: ExtractionContext) -> ExtractionContext:
        raw = context.raw_extraction
        reported_tax, pbt = _derive_tax_facts(raw)

        # Phase 1.5.6: effective rate sources in priority order:
        # 1. IS arithmetic — |income_tax| / PBT (most reliable).
        # 2. Tax-note "Effective tax rate" row — when parse succeeds.
        # 3. Statutory rate from WACCInputs (loud fallback).
        effective_rate_from_is: Decimal | None = None
        if reported_tax is not None and pbt is not None and pbt != 0:
            effective_rate_from_is = (reported_tax / pbt) * Decimal("100")

        tax_note = _find_note(raw.notes, _TAX_NOTE_PATTERN)
        effective_rate_from_note: Decimal | None = None
        statutory_rate: Decimal | None = None
        recon_items: list[tuple[str, Decimal]] = []
        if tax_note is not None:
            effective_rate_from_note, statutory_rate, recon_items = _parse_tax_recon(
                tax_note
            )

        # Choose the rate. IS-derived wins; note is fallback; statutory is last.
        effective_rate = effective_rate_from_is or effective_rate_from_note
        rate_source = (
            "IS arithmetic (|income_tax| / PBT)"
            if effective_rate_from_is is not None
            else "tax note recon row"
            if effective_rate_from_note is not None
            else None
        )

        if effective_rate is None or reported_tax is None:
            self._fallback_to_statutory(
                context,
                reason=(
                    "IS missing income_tax/PBT and no tax-note rate parseable"
                ),
            )
            return context

        context.decision_log.append(
            f"Module A.1: effective tax rate = {effective_rate:.2f}% "
            f"(source: {rate_source})."
        )

        # Classify reconciling items.
        operating_items: list[tuple[str, Decimal]] = []
        non_operating_items: list[tuple[str, Decimal]] = []
        for description, amount in recon_items:
            bucket = _classify_label(description)
            if bucket == "non_operating":
                non_operating_items.append((description, amount))
            else:
                operating_items.append((description, amount))

        non_operating_sum = sum(
            (a for _, a in non_operating_items), start=Decimal("0")
        )
        operating_sum = sum((a for _, a in operating_items), start=Decimal("0"))

        # A.2.0 — materiality.
        statutory_tax: Decimal | None = None
        if pbt is not None and statutory_rate is not None:
            statutory_tax = pbt * statutory_rate / Decimal("100")

        immaterial = False
        if statutory_tax and statutory_tax != 0:
            ratio = abs(non_operating_sum) / abs(statutory_tax)
            immaterial = ratio < _MATERIALITY_THRESHOLD

        if immaterial:
            operating_tax_rate = effective_rate
            context.decision_log.append(
                f"Module A.2.0: non-operating reconciling items "
                f"{non_operating_sum} vs statutory_tax {statutory_tax} "
                f"below {_MATERIALITY_THRESHOLD:.0%} threshold — using "
                f"effective rate {effective_rate:.2f}% as operating."
            )
        else:
            effective_pbt = pbt
            if effective_pbt is None and effective_rate != 0:
                effective_pbt = reported_tax / (effective_rate / Decimal("100"))
            if effective_pbt is None or effective_pbt == 0:
                self._fallback_to_statutory(
                    context, reason="could not derive profit_before_tax"
                )
                return context

            operating_tax_expense = reported_tax - non_operating_sum
            operating_tax_rate = (
                operating_tax_expense / effective_pbt
            ) * Decimal("100")
            context.decision_log.append(
                f"Module A.2: operating tax rate = {operating_tax_rate:.2f}% "
                f"(effective {effective_rate:.2f}%, "
                f"{len(non_operating_items)} non-operating reconciling item"
                f"{'' if len(non_operating_items) == 1 else 's'} removed, "
                f"sum {non_operating_sum})."
            )

        source = Source(
            document=(
                f"notes[{tax_note.title!r}]"
                if tax_note is not None
                else "income_statement"
            )
        )
        for description, amount in non_operating_items:
            context.adjustments.append(
                ModuleAdjustment(
                    module="A.2",
                    description=f"Non-operating tax reconciling item: {description}",
                    amount=amount,
                    affected_periods=[context.primary_period],
                    rationale=(
                        "Classified as non-operating by label heuristic "
                        "(keyword match); removed from operating tax base "
                        "per A.2.2."
                    ),
                    source=source,
                )
            )

        # A.1
        context.adjustments.append(
            ModuleAdjustment(
                module="A.1",
                description="Operating tax rate",
                amount=operating_tax_rate,
                affected_periods=[context.primary_period],
                rationale=(
                    "Rate used for NOPAT: effective_rate minus non-operating "
                    "reconciling items (A.2.0 materiality applied)."
                ),
                source=source,
            )
        )

        # A.4 — cash taxes from CF line (if present).
        cf = raw.primary_cf
        if cf is not None:
            for item in cf.line_items:
                if not _CASH_TAX_LABEL.search(item.label):
                    continue
                if item.value is None:
                    continue
                cash_tax = abs(item.value)
                delta = reported_tax - cash_tax
                context.decision_log.append(
                    f"Module A.4: cash taxes paid {cash_tax} vs reported "
                    f"{reported_tax} (Δ={delta}); kept on cash-flow view."
                )
                break

        # A.5
        context.decision_log.append(
            "Module A.5: tax payables/receivables classified as operating "
            "working capital (applied in BS reclassification)."
        )

        if pbt is None:
            context.estimates_log.append(
                "Module A: profit_before_tax derived from reported_tax / "
                "effective_rate (not directly disclosed on the IS)."
            )
        if operating_items:
            context.decision_log.append(
                f"Module A.2.1: {len(operating_items)} operating reconciling "
                f"item{'' if len(operating_items) == 1 else 's'} retained "
                f"(sum {operating_sum})."
            )

        return context

    # ------------------------------------------------------------------
    def _fallback_to_statutory(
        self, context: ExtractionContext, *, reason: str
    ) -> None:
        statutory = context.wacc_inputs.cost_of_capital.tax_rate_for_wacc
        # Phase 1.5.11 — augment the note when the underlying source is
        # unaudited so the analyst knows the fallback is expected (not
        # an extraction bug) and will auto-upgrade once the AR lands.
        from portfolio_thesis_engine.schemas.raw_extraction import AuditStatus

        audit = context.raw_extraction.metadata.audit_status
        suffix = ""
        if audit == AuditStatus.UNAUDITED:
            suffix = (
                " Preliminary / unaudited source — full tax reconciliation "
                "will appear in the formal annual report; re-run the "
                "pipeline then to upgrade from statutory."
            )
        context.estimates_log.append(
            f"Module A: falling back to statutory tax rate {statutory}% "
            f"from WACCInputs ({reason}).{suffix}"
        )
        context.adjustments.append(
            ModuleAdjustment(
                module="A.1",
                description="Operating tax rate (statutory fallback)",
                amount=statutory,
                affected_periods=[context.primary_period],
                rationale=(
                    f"Statutory rate used as operating proxy — {reason}. "
                    f"Upgrade once a tax reconciliation is available."
                ),
            )
        )
        context.decision_log.append(
            f"Module A.1: operating tax rate = {statutory}% (statutory fallback)."
        )


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _find_note(notes: list[Note], pattern: re.Pattern[str]) -> Note | None:
    for note in notes:
        if pattern.search(note.title):
            return note
    return None


def _parse_tax_recon(
    tax_note: Note,
) -> tuple[Decimal | None, Decimal | None, list[tuple[str, Decimal]]]:
    """Return ``(effective_rate_pct, statutory_rate_pct,
    [(description, amount), ...])`` from a tax note.

    Walks every table in the note. Identifies rate rows (statutory
    / effective) by label pattern. Non-rate rows with numeric
    amounts become reconciling items. The order of precedence for
    picking the reconciliation table: first table whose label
    matches ``/reconciliation|effective.*rate/``; else first table
    with more than two rows.
    """
    recon_table = _pick_recon_table(tax_note)
    if recon_table is None:
        return None, None, []

    effective_rate: Decimal | None = None
    statutory_rate: Decimal | None = None
    items: list[tuple[str, Decimal]] = []

    for row in recon_table.rows:
        if not row:
            continue
        description = str(row[0]) if row[0] is not None else ""
        if not description:
            continue
        # Numeric cells after the label
        numeric_cells = [c for c in row[1:] if isinstance(c, Decimal)]
        if not numeric_cells:
            continue
        amount = numeric_cells[0]
        # Rate rows
        if _STATUTORY_ROW_PATTERN.search(description):
            # Some tables put both the statutory rate AND statutory tax
            # amount. Heuristic: rate values are small (<= 100) with
            # no decimals beyond 2 dp; tax amounts can be much larger.
            # When multiple numerics exist, the LAST one is often the
            # rate (% column) — but filings vary.
            statutory_rate = _maybe_rate(numeric_cells)
            continue
        if _EFFECTIVE_ROW_PATTERN.search(description):
            effective_rate = _maybe_rate(numeric_cells)
            continue
        items.append((description, amount))

    return effective_rate, statutory_rate, items


def _pick_recon_table(note: Note) -> NoteTable | None:
    """Select the reconciliation table within a tax note."""
    if not note.tables:
        return None
    for table in note.tables:
        if table.table_label and _RECON_TABLE_PATTERN.search(table.table_label):
            return table
    # Fallback: first table with more than one row.
    for table in note.tables:
        if len(table.rows) > 1:
            return table
    return note.tables[0]


def _maybe_rate(numeric_cells: list[Decimal]) -> Decimal | None:
    """Pick the cell most likely to be a rate (percentage).

    Heuristic: a rate is ≤ 100 in absolute value. When multiple cells
    qualify, the last one wins (some filings put ``(amount, rate)``).
    """
    rate_candidates = [c for c in numeric_cells if abs(c) <= Decimal("100")]
    return rate_candidates[-1] if rate_candidates else None


def _derive_tax_facts(raw: RawExtraction) -> tuple[Decimal | None, Decimal | None]:
    """Return ``(reported_tax_expense, profit_before_tax)`` from the
    primary IS by label match. Values are positive (absolute)."""
    is_data = raw.primary_is
    if is_data is None:
        return None, None
    reported_tax: Decimal | None = None
    pbt: Decimal | None = None
    for item in is_data.line_items:
        if item.value is None:
            continue
        if reported_tax is None and _INCOME_TAX_LABEL.search(item.label):
            reported_tax = abs(item.value)
        if pbt is None and _PBT_LABEL.search(item.label):
            pbt = item.value
    return reported_tax, pbt


def _classify_label(description: str) -> str:
    """Return ``"operating"`` or ``"non_operating"`` based on keyword
    match."""
    lowered = description.lower()
    if any(kw in lowered for kw in _NON_OPERATING_LABEL_KEYWORDS):
        return "non_operating"
    return "operating"


def compute_operational_tax_rate_from_reconciliation(
    tax_note_decomposition: Any | None,
    income_tax_total: Decimal | None,
    profit_before_tax: Decimal | None,
) -> Decimal:
    """Phase 1.5.10 stub — strip one-time items from the tax
    reconciliation to derive an *operational* tax rate.

    Phase 2 Sprint 1 will parse ``tax_note_decomposition.sub_items``
    (e.g. "Effect of non-deductible expenses", "Tax credits",
    "Withholding tax adjustments") and subtract one-off effects before
    computing the rate. For Phase 1.5.10 this preserves current
    behaviour: effective rate when both inputs are present, 30 %
    statutory fallback otherwise.

    Arg ``tax_note_decomposition`` is the
    :class:`~portfolio_thesis_engine.schemas.decomposition.LineDecomposition`
    for the income-tax line (may be ``None`` when the note wasn't
    decomposable) — unused by the stub; reserved for the Phase-2
    implementation.
    """
    _ = tax_note_decomposition  # Phase 2 Sprint 1
    if (
        income_tax_total is not None
        and profit_before_tax is not None
        and profit_before_tax != 0
    ):
        return abs(income_tax_total) / profit_before_tax
    return Decimal("0.30")
