"""Module B — Provisions & non-operating items (minimal, B.0–B.2).

Phase 1.5.3 rewrite: classification happens locally by scanning the
as-reported structured schema.

Sources Module B consults:

1. **Goodwill note** (title ~ /goodwill/) — look for an impairment
   row in the movement table; when found, emit
   ``B.2.goodwill_impairment``.
2. **Provisions note** (title ~ /provisions/) — classify each row by
   label keyword. Restructuring / impairment / litigation keywords
   → non-operating buckets.
3. **Discontinued-operations note** (title ~ /discontinued/) — log
   presence; the IS has the NI figure directly.
4. **Income statement line items** — scan for labels containing
   "non-operating income", "share of associates", "discontinued",
   "impairment", "restructuring"; each becomes its own ``B.2.*``
   adjustment when non-zero.

OUT of Phase 1: B.3–B.10.
"""

from __future__ import annotations

import re
from decimal import Decimal

from portfolio_thesis_engine.extraction.base import ExtractionContext, ExtractionModule
from portfolio_thesis_engine.llm.anthropic_provider import AnthropicProvider
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.common import Source
from portfolio_thesis_engine.schemas.company import ModuleAdjustment
from portfolio_thesis_engine.schemas.raw_extraction import Note

_GOODWILL_NOTE_PATTERN = re.compile(r"goodwill", re.IGNORECASE)
_PROVISIONS_NOTE_PATTERN = re.compile(r"provisions?\b", re.IGNORECASE)
_DISCONTINUED_NOTE_PATTERN = re.compile(
    r"discontinued operation|discontinued ops", re.IGNORECASE
)

# Within a goodwill movement table, the impairment row label pattern.
_GOODWILL_IMPAIRMENT_ROW = re.compile(r"impairment", re.IGNORECASE)

# Label keyword → subtype.
_PROVISION_NON_OP_KEYWORDS: tuple[tuple[str, str], ...] = (
    ("restructuring", "restructuring"),
    ("litigation", "litigation"),
    ("legal settlement", "litigation"),
    ("impairment of", "asset_impairment"),
    ("asset impairment", "asset_impairment"),
    ("onerous contract", "onerous_contract"),
    ("disposal", "disposal_loss"),
    ("site closure", "restructuring"),
)

_IS_NON_OP_PATTERNS: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"non[- ]operating (income|expense)", re.IGNORECASE),
     "non_operating_other"),
    (re.compile(r"share of (profits?|losses?) of associate", re.IGNORECASE),
     "associates"),
    (re.compile(r"share of associates'? results", re.IGNORECASE), "associates"),
    (re.compile(r"discontinued operation", re.IGNORECASE), "discontinued"),
    (re.compile(r"gain on disposal|loss on disposal", re.IGNORECASE),
     "disposal_gain_loss"),
    (re.compile(r"gain on sale|loss on sale", re.IGNORECASE),
     "disposal_gain_loss"),
    (re.compile(r"goodwill impairment", re.IGNORECASE), "goodwill_impairment"),
    (re.compile(r"restructuring", re.IGNORECASE), "restructuring"),
    (re.compile(r"impairment (of|loss)", re.IGNORECASE), "asset_impairment"),
)


class ModuleBProvisions(ExtractionModule):
    """Provisions / non-operating items minimal reclassification."""

    module_id = "B"

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
        adjustments_added = 0

        # 1. Goodwill impairment (from movement table)
        goodwill_note = _find_note(raw.notes, _GOODWILL_NOTE_PATTERN)
        if goodwill_note is not None:
            impairment = _find_goodwill_impairment(goodwill_note)
            if impairment is not None and impairment != 0:
                context.adjustments.append(
                    ModuleAdjustment(
                        module="B.2.goodwill_impairment",
                        description="Goodwill impairment (from goodwill note)",
                        amount=impairment,
                        affected_periods=[context.primary_period],
                        rationale=(
                            "Goodwill impairment is one-off by nature; "
                            "moved below operating profit per B.2."
                        ),
                        source=Source(document=f"notes[{goodwill_note.title!r}]"),
                    )
                )
                adjustments_added += 1

        # 2. Provisions classified by label keyword
        provisions_note = _find_note(raw.notes, _PROVISIONS_NOTE_PATTERN)
        if provisions_note is not None:
            for description, amount, subtype in _parse_provisions(provisions_note):
                context.adjustments.append(
                    ModuleAdjustment(
                        module=f"B.2.{subtype}",
                        description=f"Non-operating provision: {description}",
                        amount=amount,
                        affected_periods=[context.primary_period],
                        rationale=(
                            f"Label keyword matched non-operating bucket "
                            f"{subtype!r}; moved below operating profit per B.2."
                        ),
                        source=Source(
                            document=f"notes[{provisions_note.title!r}]"
                        ),
                    )
                )
                adjustments_added += 1

        # 3. Discontinued-ops note — log
        disc_note = _find_note(raw.notes, _DISCONTINUED_NOTE_PATTERN)
        if disc_note is not None:
            context.decision_log.append(
                f"Module B: discontinued-ops note present "
                f"({disc_note.title!r}); IS line match drives the adjustment."
            )

        # 4. Scan the IS for non-op labels
        is_data = raw.primary_is
        if is_data is not None:
            is_source = Source(document="income_statement")
            for item in is_data.line_items:
                if item.is_subtotal or item.value is None or item.value == 0:
                    continue
                is_subtype = _classify_is_line(item.label)
                if is_subtype is None:
                    continue
                subtype = is_subtype
                context.adjustments.append(
                    ModuleAdjustment(
                        module=f"B.2.{subtype}",
                        description=f"IS non-operating item: {item.label}",
                        amount=item.value,
                        affected_periods=[context.primary_period],
                        rationale=(
                            f"Label keyword matched non-operating bucket "
                            f"{subtype!r}; kept out of operating NOPAT base."
                        ),
                        source=is_source,
                    )
                )
                adjustments_added += 1

        if adjustments_added == 0:
            context.decision_log.append(
                "Module B.1: no non-operating items surfaced from IS, "
                "provisions, goodwill, or discontinued-ops note; "
                "operating profit left unchanged."
            )
            return context

        total = sum(
            (adj.amount for adj in context.adjustments if adj.module.startswith("B.2")),
            start=Decimal("0"),
        )
        context.decision_log.append(
            f"Module B.1: {adjustments_added} non-operating item"
            f"{'' if adjustments_added == 1 else 's'} reclassified "
            f"(sum {total})."
        )
        return context


# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
def _find_note(notes: list[Note], pattern: re.Pattern[str]) -> Note | None:
    for note in notes:
        if pattern.search(note.title):
            return note
    return None


def _find_goodwill_impairment(note: Note) -> Decimal | None:
    """Scan the goodwill note's tables for an impairment row. Return
    the first Decimal amount found (typically negative — per goodwill
    movement convention)."""
    for table in note.tables:
        for row in table.rows:
            if not row:
                continue
            label = str(row[0]) if row[0] is not None else ""
            if not _GOODWILL_IMPAIRMENT_ROW.search(label):
                continue
            for cell in row[1:]:
                if isinstance(cell, Decimal):
                    return cell
    return None


def _parse_provisions(note: Note) -> list[tuple[str, Decimal, str]]:
    """Walk every row of every table; emit ``(description, amount,
    subtype)`` for rows whose label hits a non-operating keyword."""
    out: list[tuple[str, Decimal, str]] = []
    for table in note.tables:
        for row in table.rows:
            if not row:
                continue
            description = str(row[0]) if row[0] is not None else ""
            if not description:
                continue
            lowered = description.lower()
            subtype: str | None = None
            for keyword, bucket in _PROVISION_NON_OP_KEYWORDS:
                if keyword in lowered:
                    subtype = bucket
                    break
            if subtype is None:
                continue
            for cell in row[1:]:
                if isinstance(cell, Decimal):
                    out.append((description, cell, subtype))
                    break
    return out


def _classify_is_line(label: str) -> str | None:
    """Return the B.2 subtype for an IS line label or None if the
    line is operating. Order matters — ``goodwill impairment`` beats
    generic ``impairment``."""
    for pattern, subtype in _IS_NON_OP_PATTERNS:
        if pattern.search(label):
            return subtype
    return None
