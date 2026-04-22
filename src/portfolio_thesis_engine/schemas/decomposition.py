"""Phase 1.5.10 — Module D Universal Note Decomposer schemas.

Every aggregated :class:`LineItem` that carries a ``source_note`` and
has a matching note table can be decomposed into sub-items and
classified on two dimensions:

- **Operational** vs **non-operational** — is this part of the core
  business (core opex, revenue-driving activities) or ancillary
  (gains on disposal of PPE, FV remeasurements of contingent
  consideration, investment gains, etc.)?
- **Recurring** vs **non-recurring** — can we expect this to repeat
  each period (government subsidies that come with the operating
  licence), or is it a one-off (exceptional, restructuring, acquisition
  costs)?

Only the intersection (**operational AND recurring**) flows into the
sustainable operating income the DCF projects forward. Everything
else is excluded with an explicit rationale so the analyst can audit
the decision.

Ambiguous cases (no pattern matched, or a pattern with ``low``
confidence) are flagged for user review via an
``overrides.yaml`` file. Conservative default when the analyst hasn't
overridden: exclude.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Literal

from pydantic import Field

from portfolio_thesis_engine.schemas.base import BaseSchema

OperationalClass = Literal["operational", "non_operational", "ambiguous"]
RecurrenceClass = Literal["recurring", "non_recurring", "ambiguous"]
SubItemAction = Literal["include", "exclude", "flag_for_review"]
DecompositionMethod = Literal["note_table", "label_fallback", "not_decomposable"]
ConfidenceLevel = Literal["high", "medium", "low"]
ParentStatement = Literal["IS", "BS", "CF", "Note"]


class SubItem(BaseSchema):
    """One atomic sub-item of a decomposed parent line.

    ``value`` carries the signed figure as reported by the note table
    (same sign convention as the parent line — a gain is positive, an
    expense / loss is negative when the statement groups them with
    operating items).

    ``needs_multi_year_validation`` is set for Phase 1 single-year
    runs: the classification confidence is at best "medium" without
    multi-year history, so Phase 2 consumers know the flag deserves a
    second look once historical statements are loaded.
    """

    label: str = Field(min_length=1)
    value: Decimal
    operational_classification: OperationalClass
    recurrence_classification: RecurrenceClass
    action: SubItemAction
    matched_rule: str
    rationale: str
    confidence: ConfidenceLevel
    source_page: int | None = Field(default=None, ge=0)
    needs_multi_year_validation: bool = False


class LineDecomposition(BaseSchema):
    """One parent line's decomposition.

    ``sustainable_addition`` is the sum of ``sub_items`` with
    ``action == "include"`` — i.e. the contribution to sustainable
    operating income. ``excluded_total`` and ``flagged_total`` mirror
    the other two actions for audit / display.

    ``method`` records how the decomposition was produced:

    - ``"note_table"`` — the ``source_note`` reference matched a note
      whose table rows summed (±5 %) to the parent value.
    - ``"label_fallback"`` — no note reference or no matching table;
      the parent's own label was classified as a single sub-item.
    - ``"not_decomposable"`` — no note reference *and* the parent
      label didn't match any pattern.
    """

    parent_statement: ParentStatement
    parent_label: str = Field(min_length=1)
    parent_value: Decimal
    source_note_number: str | None = None
    source_note_title: str | None = None
    method: DecompositionMethod
    confidence: ConfidenceLevel
    sub_items: list[SubItem] = Field(default_factory=list)
    sustainable_addition: Decimal = Decimal("0")
    excluded_total: Decimal = Decimal("0")
    flagged_total: Decimal = Decimal("0")


class DecompositionCoverage(BaseSchema):
    """Phase 1.5.10 — snapshot-level summary of how much of each
    statement was decomposed. Populated per run and persisted on the
    :class:`~portfolio_thesis_engine.schemas.valuation.ValuationSnapshot`
    so ``pte show --detail`` can surface coverage at a glance."""

    is_total: int = 0
    is_decomposed: int = 0
    is_fallback: int = 0
    is_not_decomposable: int = 0
    bs_total: int = 0
    bs_decomposed: int = 0
    bs_fallback: int = 0
    bs_not_decomposable: int = 0
    cf_total: int = 0
    cf_decomposed: int = 0
    cf_fallback: int = 0
    cf_not_decomposable: int = 0
