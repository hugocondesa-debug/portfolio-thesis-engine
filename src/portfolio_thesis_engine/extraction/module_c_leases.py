"""Module C — Leases (IFRS 16, subset C.0–C.3).

Phase 1.5.3 rewrite: reads the leases note's tables instead of a
typed ``LeaseNote``. Typical leases notes disclose two movement
tables: ROU asset roll-forward and lease-liability roll-forward. The
module scans both by row label pattern.

Scope:

- **C.0** applicability — no leases note ⇒ skip.
- **C.1** base audit-trail — surface ROU closing + liability
  opening/closing.
- **C.2** capitalization — log the liability balance that flows onto
  the BS reclassification.
- **C.3** lease additions for the FCFF economic view. Prefer the
  disclosed "Additions" row in the ROU table; else back out from
  the liability movement identity (``closing − opening +
  principal_payments``).
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
from portfolio_thesis_engine.schemas.raw_extraction import Note

_LEASES_NOTE_PATTERN = re.compile(r"leases?\b", re.IGNORECASE)

# Row-label patterns inside a leases note.
_ROU_ADDITIONS = re.compile(r"addition|new leases? recognised", re.IGNORECASE)
_ROU_DEPRECIATION = re.compile(
    r"depreciation (charge|of (right-of-use|rou))", re.IGNORECASE
)
_ROU_CLOSING = re.compile(r"closing balance|at (31|30) [a-z]+|balance at end",
                          re.IGNORECASE)
_LIAB_OPENING = re.compile(
    r"opening balance|at 1 january|balance at start|balance at beginning",
    re.IGNORECASE,
)
_LIAB_CLOSING = _ROU_CLOSING
_LIAB_INTEREST = re.compile(r"interest (expense|accretion) on lease",
                            re.IGNORECASE)
_LIAB_PRINCIPAL = re.compile(
    r"principal payment|(repayment|payment) of lease (liabilit|principal)",
    re.IGNORECASE,
)


class ModuleCLeases(ExtractionModule):
    """IFRS 16 lease reclassification."""

    module_id = "C"

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
        leases_note = _find_note(raw.notes, _LEASES_NOTE_PATTERN)

        if leases_note is None:
            context.decision_log.append(
                "Module C.0: no leases note; assuming no material IFRS 16 "
                "lease activity."
            )
            return context

        # Scan all tables in the note for the relevant rows.
        rou_closing: Decimal | None = None
        rou_additions: Decimal | None = None
        rou_depreciation: Decimal | None = None
        liab_opening: Decimal | None = None
        liab_closing: Decimal | None = None
        liab_interest: Decimal | None = None
        liab_principal: Decimal | None = None

        for table in leases_note.tables:
            table_label = (table.table_label or "").lower()
            is_liab_table = "liabilit" in table_label
            for row in table.rows:
                if not row:
                    continue
                label = str(row[0]) if row[0] is not None else ""
                if not label:
                    continue
                amount = _first_decimal(row[1:])
                if amount is None:
                    continue
                # Row-label dispatch. A single note may have a combined
                # movement table; set both ROU and liability fields
                # when the table is ambiguous.
                if _ROU_ADDITIONS.search(label) and rou_additions is None:
                    rou_additions = amount
                if _ROU_DEPRECIATION.search(label) and rou_depreciation is None:
                    rou_depreciation = amount
                if _ROU_CLOSING.search(label):
                    if is_liab_table and liab_closing is None:
                        liab_closing = amount
                    elif rou_closing is None:
                        rou_closing = amount
                if _LIAB_OPENING.search(label) and is_liab_table and liab_opening is None:
                    liab_opening = amount
                elif _LIAB_OPENING.search(label) and liab_opening is None and not is_liab_table:
                    # Ambiguous — fall through; only set on liability tables
                    # to avoid capturing ROU opening as lease-liability
                    # opening.
                    pass
                if _LIAB_INTEREST.search(label) and liab_interest is None:
                    liab_interest = amount
                if _LIAB_PRINCIPAL.search(label) and liab_principal is None:
                    liab_principal = amount

        # C.1
        context.decision_log.append(
            f"Module C.1: IFRS 16 base — ROU closing {rou_closing}, "
            f"lease liability opening {liab_opening} / closing {liab_closing}."
        )

        # C.2
        if liab_closing is not None:
            context.decision_log.append(
                f"Module C.2: lease liability capitalized on BS = "
                f"{liab_closing} (downstream BS reclassification)."
            )

        # C.3 — lease additions. Identity:
        #   closing = opening + additions − |principal_payments|
        # ⇒ additions = closing − opening + |principal_payments|
        # Using abs() because different filings report the payment with
        # different signs (some positive for absolute amounts, some
        # negative as an outflow).
        additions = rou_additions
        derived = False
        if (
            additions is None
            and liab_opening is not None
            and liab_closing is not None
        ):
            additions = liab_closing - liab_opening
            if liab_principal is not None:
                additions += abs(liab_principal)
            derived = True

        if additions is None:
            context.estimates_log.append(
                "Module C.3: lease additions could not be derived "
                "(opening/closing balance missing). Skipping adjustment."
            )
            return context

        source = Source(document=f"notes[{leases_note.title!r}]")
        context.adjustments.append(
            ModuleAdjustment(
                module="C.3",
                description="Lease additions for FCFF economic view",
                amount=additions,
                affected_periods=[context.primary_period],
                rationale=(
                    "Included as investment in Total Reinvestment per "
                    "P1 industrial methodology (IFRS 16)."
                    + (
                        " Value derived from closing − opening + principal_payments."
                        if derived
                        else ""
                    )
                ),
                source=source,
            )
        )
        if derived:
            context.estimates_log.append(
                "Module C.3: lease additions derived from movement identity "
                "(additions not disclosed directly)."
            )

        if liab_interest is not None:
            context.decision_log.append(
                f"Module C.3: interest on lease liabilities = {liab_interest} "
                f"(kept in financial expense line for NOPAT bridge)."
            )
        if rou_depreciation is not None:
            context.decision_log.append(
                f"Module C.3: ROU depreciation = {rou_depreciation} "
                f"(operating expense component of EBITA)."
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


def _first_decimal(cells: list[Any]) -> Decimal | None:
    for cell in cells:
        if isinstance(cell, Decimal):
            return cell
    return None
