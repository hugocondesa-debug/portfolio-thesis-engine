"""Phase 1.5.10 — Module D: Universal Note Decomposer.

Every aggregated :class:`LineItem` with a ``source_note`` reference
and a matching note table can be broken into sub-items and classified
on two dimensions (operational × recurring). Only the intersection
(operational AND recurring) flows into sustainable operating income.

The decomposer walks IS / BS / CF and attempts, for each line item:

1. ``note_table`` method — resolve ``source_note`` → note → the table
   whose rows sum (±5 %) to the parent value. Each row becomes a
   :class:`SubItem`.
2. ``label_fallback`` method — when no note reference or no matching
   table, treat the parent label as a single sub-item and classify it
   with the same regex tables.
3. ``not_decomposable`` — no regex pattern matched and no note table.
   The line contributes zero to the sustainable adjustment.

Classification uses four ordered regex tables (operational /
non-operational / recurring / non-recurring). The first match wins
per dimension. User overrides loaded from
``{portfolio_dir}/<ticker>/overrides.yaml`` beat the regex tables.

Zero LLM calls.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from portfolio_thesis_engine.schemas.decomposition import (
    ConfidenceLevel,
    DecompositionCoverage,
    LineDecomposition,
    OperationalClass,
    ParentStatement,
    RecurrenceClass,
    SubItem,
    SubItemAction,
)
from portfolio_thesis_engine.schemas.overrides import ModuleDOverrides
from portfolio_thesis_engine.schemas.raw_extraction import (
    BalanceSheetPeriod,
    CashFlowPeriod,
    IncomeStatementPeriod,
    LineItem,
    Note,
    NoteTable,
    RawExtraction,
)

# ----------------------------------------------------------------------
# Regex tables — (pattern, classification, confidence)
#
# Patterns are case-insensitive. Order matters: the first match wins per
# dimension. Put specific patterns above generic ones.
# ----------------------------------------------------------------------
OPERATIONAL_PATTERNS: list[tuple[str, OperationalClass, ConfidenceLevel]] = [
    (r"government\s+(grant|subsid)", "operational", "high"),
    (r"insurance\s+(reimbursement|rebate|recovery)", "operational", "medium"),
    (r"rental\s+income\s+from\s+operation", "operational", "medium"),
    (r"research\s+(income|grant)", "operational", "medium"),
    (r"licen[cs]e.*fee", "operational", "medium"),
    (r"service\s+(fee|income)", "operational", "medium"),
]

NON_OPERATIONAL_PATTERNS: list[tuple[str, OperationalClass, ConfidenceLevel]] = [
    (r"contingent\s+consideration", "non_operational", "high"),
    (r"fair\s*value.*contingent", "non_operational", "high"),
    (r"remeasurement.*contingent", "non_operational", "high"),
    (
        r"(gain|loss).*(?:on\s+)?disposal\s+of\s+(ppe|property|equipment|"
        r"intangib|investment|subsidiar)",
        "non_operational",
        "high",
    ),
    (
        r"(gain|loss)(?:es|s)?\s+on\s+disposal\s+of\s+"
        r"(property|plant|equipment|intangib|investment|subsidiar)",
        "non_operational",
        "high",
    ),
    (r"(gain|loss)\s+on\s+investment", "non_operational", "high"),
    (r"goodwill\s+impairment", "non_operational", "high"),
    (r"litigation.*(settlement|charge|provision)", "non_operational", "medium"),
    (
        r"(dividend|interest)\s+income\s+(from|on)\s+(investment|bank|deposit)",
        "non_operational",
        "high",
    ),
]

RECURRING_PATTERNS: list[tuple[str, RecurrenceClass, ConfidenceLevel]] = [
    (r"government\s+(grant|subsid)", "recurring", "medium"),
    (r"\b(ongoing|annual|recurring)\b", "recurring", "high"),
    (r"service\s+(fee|income).*regular", "recurring", "high"),
    (r"rental\s+income.*recurring", "recurring", "high"),
]

NON_RECURRING_PATTERNS: list[tuple[str, RecurrenceClass, ConfidenceLevel]] = [
    (r"\bone[- ]?(off|time)\b|\bexceptional\b", "non_recurring", "high"),
    (r"acquisition.*(cost|related|transaction)", "non_recurring", "medium"),
    (r"(gain|loss)(?:es|s)?.*disposal", "non_recurring", "high"),
    (r"contingent\s+consideration", "non_recurring", "high"),
    (r"fair\s*value.*contingent", "non_recurring", "high"),
    (r"remeasurement.*contingent", "non_recurring", "high"),
    (r"goodwill\s+impairment", "non_recurring", "high"),
    (r"\bimpairment\b", "non_recurring", "medium"),
    (r"\brestructuring\b", "non_recurring", "medium"),
    (r"\bsettlement\b", "non_recurring", "medium"),
]


_CONFIDENCE_RANK = {"high": 3, "medium": 2, "low": 1}


def _min_confidence(a: ConfidenceLevel, b: ConfidenceLevel) -> ConfidenceLevel:
    return a if _CONFIDENCE_RANK[a] <= _CONFIDENCE_RANK[b] else b


def _match_patterns(
    label: str,
    table: list[tuple[str, Any, ConfidenceLevel]],
) -> tuple[Any | None, ConfidenceLevel]:
    """Return ``(classification, confidence)`` for the first matching
    pattern, or ``(None, "low")`` when nothing matched."""
    for pattern, classification, confidence in table:
        if re.search(pattern, label, re.IGNORECASE):
            return classification, confidence
    return None, "low"


def _decide_action(
    op_class: OperationalClass,
    rec_class: RecurrenceClass,
) -> SubItemAction:
    """Only (operational AND recurring) → include. Any ambiguous
    dimension → flag. Otherwise → exclude (conservative default)."""
    if op_class == "operational" and rec_class == "recurring":
        return "include"
    if op_class == "ambiguous" or rec_class == "ambiguous":
        return "flag_for_review"
    return "exclude"


def _rationale(
    op_class: OperationalClass,
    rec_class: RecurrenceClass,
) -> str:
    return (
        f"operational={op_class}, recurring={rec_class} → "
        f"{_decide_action(op_class, rec_class)} (Module D default rule)."
    )


# ----------------------------------------------------------------------
# ModuleD
# ----------------------------------------------------------------------
class ModuleD:
    """Universal note decomposer.

    Typical usage::

        module_d = ModuleD(overrides=ModuleDOverrides.empty())
        decompositions = module_d.decompose_all(raw_extraction)
        coverage = module_d.compute_coverage(raw_extraction, decompositions)
    """

    def __init__(self, overrides: ModuleDOverrides | None = None) -> None:
        self.overrides = overrides or ModuleDOverrides.empty()

    # ------------------------------------------------------------------
    # Top-level entry point
    # ------------------------------------------------------------------
    def decompose_all(
        self,
        raw_extraction: RawExtraction,
    ) -> dict[str, LineDecomposition]:
        """Walk IS + BS + CF, attempt decomposition for every non-
        subtotal line item. Dict keys are ``"{statement}:{label}"``
        (e.g. ``"IS:Other gains, net"``).

        Decomposition of subtotals is skipped — subtotals are built
        from the very lines we're trying to decompose, so decomposing
        them would double-count.
        """
        results: dict[str, LineDecomposition] = {}

        for statement, data in _iter_statements(raw_extraction):
            if data is None:
                continue
            for item in data.line_items:
                if item.is_subtotal or item.value is None:
                    continue
                decomp = self.decompose_line(item, statement, raw_extraction)
                results[f"{statement}:{item.label}"] = decomp

        return results

    # ------------------------------------------------------------------
    def decompose_line(
        self,
        line_item: LineItem,
        parent_statement: ParentStatement,
        raw_extraction: RawExtraction,
    ) -> LineDecomposition:
        """Try strategies in order: note_table → label_fallback →
        not_decomposable."""
        # Strategy 1 — note_table
        if line_item.source_note is not None:
            note, table, col_idx = _find_note_table(
                raw_extraction,
                source_note=line_item.source_note,
                parent_value=line_item.value or Decimal("0"),
            )
            if note is not None and table is not None and col_idx is not None:
                sub_items = self._classify_table_rows(
                    table=table,
                    note=note,
                    col_idx=col_idx,
                )
                if sub_items:
                    return self._build_decomposition(
                        line_item=line_item,
                        parent_statement=parent_statement,
                        note=note,
                        method="note_table",
                        sub_items=sub_items,
                    )

        # Strategy 2 — label_fallback. Single-label classification when
        # the label itself matches a regex pattern. Useful for lines
        # whose note isn't structured as a sum (e.g. "Impairment
        # charge — goodwill, note 12" pointing at narrative).
        single = self.classify_sub_item(
            label=line_item.label,
            value=line_item.value or Decimal("0"),
            source_page=line_item.source_page,
        )
        if single.operational_classification != "ambiguous" or (
            single.recurrence_classification != "ambiguous"
        ):
            return self._build_decomposition(
                line_item=line_item,
                parent_statement=parent_statement,
                note=None,
                method="label_fallback",
                sub_items=[single],
            )

        # Strategy 3 — not decomposable.
        return LineDecomposition(
            parent_statement=parent_statement,
            parent_label=line_item.label,
            parent_value=line_item.value or Decimal("0"),
            source_note_number=line_item.source_note,
            source_note_title=None,
            method="not_decomposable",
            confidence="low",
            sub_items=[],
        )

    # ------------------------------------------------------------------
    def classify_sub_item(
        self,
        label: str,
        value: Decimal,
        source_page: int | None = None,
    ) -> SubItem:
        """Apply overrides first, then regex rules. Return a populated
        :class:`SubItem`."""
        override = self.overrides.match(label)
        if override is not None and (
            override.operational is not None or override.recurring is not None
        ):
            # Fall through to regex for any dimension the override left None.
            regex_op, regex_op_conf = _match_patterns(label, OPERATIONAL_PATTERNS)
            if regex_op is None:
                regex_op_neg, regex_op_conf_neg = _match_patterns(
                    label, NON_OPERATIONAL_PATTERNS
                )
                regex_op = regex_op_neg
                regex_op_conf = regex_op_conf_neg
            regex_rec, regex_rec_conf = _match_patterns(label, RECURRING_PATTERNS)
            if regex_rec is None:
                regex_rec_neg, regex_rec_conf_neg = _match_patterns(
                    label, NON_RECURRING_PATTERNS
                )
                regex_rec = regex_rec_neg
                regex_rec_conf = regex_rec_conf_neg
            op_class: OperationalClass = override.operational or regex_op or "ambiguous"
            rec_class: RecurrenceClass = override.recurring or regex_rec or "ambiguous"
            action = _decide_action(op_class, rec_class)
            return SubItem(
                label=label,
                value=value,
                operational_classification=op_class,
                recurrence_classification=rec_class,
                action=action,
                matched_rule=f"user_override:{override.label_pattern}",
                rationale=override.rationale,
                confidence="high",
                source_page=source_page,
                needs_multi_year_validation=False,
            )

        op_positive, op_pos_conf = _match_patterns(label, OPERATIONAL_PATTERNS)
        op_negative, op_neg_conf = _match_patterns(label, NON_OPERATIONAL_PATTERNS)
        if op_positive is not None and op_negative is not None:
            # Conflicting signal — higher-confidence rule wins; ties go
            # to non-operational (conservative).
            if _CONFIDENCE_RANK[op_pos_conf] > _CONFIDENCE_RANK[op_neg_conf]:
                op_class = op_positive
                op_conf = op_pos_conf
            else:
                op_class = op_negative
                op_conf = op_neg_conf
        elif op_positive is not None:
            op_class = op_positive
            op_conf = op_pos_conf
        elif op_negative is not None:
            op_class = op_negative
            op_conf = op_neg_conf
        else:
            op_class = "ambiguous"
            op_conf = "low"

        rec_positive, rec_pos_conf = _match_patterns(label, RECURRING_PATTERNS)
        rec_negative, rec_neg_conf = _match_patterns(label, NON_RECURRING_PATTERNS)
        if rec_positive is not None and rec_negative is not None:
            if _CONFIDENCE_RANK[rec_pos_conf] > _CONFIDENCE_RANK[rec_neg_conf]:
                rec_class = rec_positive
                rec_conf = rec_pos_conf
            else:
                rec_class = rec_negative
                rec_conf = rec_neg_conf
        elif rec_positive is not None:
            rec_class = rec_positive
            rec_conf = rec_pos_conf
        elif rec_negative is not None:
            rec_class = rec_negative
            rec_conf = rec_neg_conf
        else:
            rec_class = "ambiguous"
            rec_conf = "low"

        action = _decide_action(op_class, rec_class)
        return SubItem(
            label=label,
            value=value,
            operational_classification=op_class,
            recurrence_classification=rec_class,
            action=action,
            matched_rule=f"regex:{op_class}+{rec_class}",
            rationale=_rationale(op_class, rec_class),
            confidence=_min_confidence(op_conf, rec_conf),
            source_page=source_page,
            needs_multi_year_validation=True,
        )

    # ------------------------------------------------------------------
    def _classify_table_rows(
        self,
        table: NoteTable,
        note: Note,
        col_idx: int,
    ) -> list[SubItem]:
        """Walk table rows, pulling the value from column ``col_idx``
        (identified by :func:`_best_column_match` as the primary-period
        column), and build :class:`SubItem` objects."""
        source_page = note.source_pages[0] if note.source_pages else None
        sub_items: list[SubItem] = []
        for row in table.rows:
            if not row or col_idx >= len(row):
                continue
            label = _first_string(row)
            if label is None:
                continue
            cell = row[col_idx]
            if not isinstance(cell, Decimal):
                continue
            lower = label.lower()
            if lower.startswith("total") or lower.startswith("net total"):
                continue
            sub_items.append(
                self.classify_sub_item(label, cell, source_page=source_page)
            )
        return sub_items

    # ------------------------------------------------------------------
    def _build_decomposition(
        self,
        line_item: LineItem,
        parent_statement: ParentStatement,
        note: Note | None,
        method: str,
        sub_items: list[SubItem],
    ) -> LineDecomposition:
        sustainable = sum(
            (s.value for s in sub_items if s.action == "include"),
            start=Decimal("0"),
        )
        excluded = sum(
            (s.value for s in sub_items if s.action == "exclude"),
            start=Decimal("0"),
        )
        flagged = sum(
            (s.value for s in sub_items if s.action == "flag_for_review"),
            start=Decimal("0"),
        )
        overall_conf: ConfidenceLevel
        if not sub_items:
            overall_conf = "low"
        else:
            overall_conf = sub_items[0].confidence
            for s in sub_items[1:]:
                overall_conf = _min_confidence(overall_conf, s.confidence)
        return LineDecomposition(
            parent_statement=parent_statement,
            parent_label=line_item.label,
            parent_value=line_item.value or Decimal("0"),
            source_note_number=line_item.source_note,
            source_note_title=note.title if note is not None else None,
            method=method,
            confidence=overall_conf,
            sub_items=sub_items,
            sustainable_addition=sustainable,
            excluded_total=excluded,
            flagged_total=flagged,
        )

    # ------------------------------------------------------------------
    def compute_coverage(
        self,
        raw_extraction: RawExtraction,
        decompositions: dict[str, LineDecomposition],
    ) -> DecompositionCoverage:
        """Aggregate counts across IS / BS / CF for ``pte show --detail``."""
        coverage = DecompositionCoverage()
        for statement, data in _iter_statements(raw_extraction):
            if data is None:
                continue
            for item in data.line_items:
                if item.is_subtotal or item.value is None:
                    continue
                key = f"{statement}:{item.label}"
                decomp = decompositions.get(key)
                if statement == "IS":
                    coverage.is_total += 1
                    _bump_counter(coverage, "is", decomp)
                elif statement == "BS":
                    coverage.bs_total += 1
                    _bump_counter(coverage, "bs", decomp)
                elif statement == "CF":
                    coverage.cf_total += 1
                    _bump_counter(coverage, "cf", decomp)
        return coverage


def _bump_counter(
    coverage: DecompositionCoverage,
    prefix: str,
    decomp: LineDecomposition | None,
) -> None:
    if decomp is None:
        setattr(
            coverage,
            f"{prefix}_not_decomposable",
            getattr(coverage, f"{prefix}_not_decomposable") + 1,
        )
        return
    if decomp.method == "note_table":
        setattr(
            coverage,
            f"{prefix}_decomposed",
            getattr(coverage, f"{prefix}_decomposed") + 1,
        )
    elif decomp.method == "label_fallback":
        setattr(
            coverage,
            f"{prefix}_fallback",
            getattr(coverage, f"{prefix}_fallback") + 1,
        )
    else:
        setattr(
            coverage,
            f"{prefix}_not_decomposable",
            getattr(coverage, f"{prefix}_not_decomposable") + 1,
        )


# ----------------------------------------------------------------------
# Statement iteration + note/table discovery
# ----------------------------------------------------------------------
def _iter_statements(
    raw_extraction: RawExtraction,
) -> list[tuple[ParentStatement, Any]]:
    return [
        ("IS", raw_extraction.primary_is),
        ("BS", raw_extraction.primary_bs),
        ("CF", raw_extraction.primary_cf),
    ]


def _find_note_table(
    raw_extraction: RawExtraction,
    source_note: str,
    parent_value: Decimal,
) -> tuple[Note | None, NoteTable | None, int | None]:
    """Find the note whose number matches ``source_note`` and the table
    + column whose rows sum (±5 %) to ``parent_value``.

    Returns ``(note, table, column_index)`` — ``column_index`` is the
    position in each row whose :class:`Decimal` cells should be used as
    the sub-item's value. For a two-column table (``Item | Total``)
    that's index 1; for a three-column period table
    (``Item | 2024 | 2023``) it's the column that matches the parent,
    typically 1 (current period).
    """
    normalised = _normalise_note_number(source_note)
    note = _find_note(raw_extraction, normalised)
    if note is None:
        return None, None, None
    target = abs(parent_value)
    tolerance = target * Decimal("0.05") if target > 0 else Decimal("1")
    best_table: NoteTable | None = None
    best_col: int | None = None
    best_diff: Decimal | None = None
    for table in note.tables:
        col_idx, total = _best_column_match(table, target)
        if col_idx is None or total is None:
            continue
        diff = abs(abs(total) - target)
        if diff <= tolerance and (best_diff is None or diff < best_diff):
            best_table = table
            best_col = col_idx
            best_diff = diff
    return note, best_table, best_col


def _find_note(raw_extraction: RawExtraction, normalised: str) -> Note | None:
    for note in raw_extraction.notes:
        if note.note_number is None:
            continue
        if _normalise_note_number(note.note_number) == normalised:
            return note
    return None


def _normalise_note_number(value: str) -> str:
    """Strip whitespace and sub-note qualifiers (e.g. ``"9(a)"`` →
    ``"9"``) so composite references still find their parent note."""
    stripped = value.strip()
    # Take the first numeric-ish prefix.
    match = re.match(r"\d+", stripped)
    if match:
        return match.group(0)
    return stripped


def _best_column_match(
    table: NoteTable, target: Decimal
) -> tuple[int | None, Decimal | None]:
    """For each numeric column in the table, sum the non-total rows and
    return the column whose sum is closest to ``target``. Multi-period
    tables (Item | 2024 | 2023) pick the column that matches; single-
    total tables (Item | Total) pick the only numeric column."""
    if not table.rows:
        return None, None
    max_len = max((len(r) for r in table.rows), default=0)
    best_col: int | None = None
    best_total: Decimal | None = None
    best_diff: Decimal | None = None
    for col in range(1, max_len):
        total = Decimal("0")
        found = False
        for row in table.rows:
            if not row or col >= len(row):
                continue
            label = _first_string(row) or ""
            if label.lower().startswith("total") or label.lower().startswith("net total"):
                continue
            cell = row[col]
            if not isinstance(cell, Decimal):
                continue
            total += cell
            found = True
        if not found:
            continue
        diff = abs(abs(total) - abs(target))
        if best_diff is None or diff < best_diff:
            best_col = col
            best_total = total
            best_diff = diff
    return best_col, best_total


def _first_string(row: list[Any]) -> str | None:
    for cell in row:
        if isinstance(cell, str) and cell.strip():
            return cell.strip()
    return None


__all__ = [
    "NON_OPERATIONAL_PATTERNS",
    "NON_RECURRING_PATTERNS",
    "OPERATIONAL_PATTERNS",
    "RECURRING_PATTERNS",
    "ModuleD",
]
