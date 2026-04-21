"""Module B — Provisions & non-operating items (minimal, B.0–B.2).

Scope shipped here:

- **B.0** applicability: when the IS parse is empty or missing a
  non-operating bucket, the module returns a no-op (logged).
- **B.1** operating vs EBITA framework: walks the IS ``line_items`` and
  flags items whose category is ``non_operating`` *or* whose label
  matches the obvious non-operating patterns. Everything else stays in
  operating income.
- **B.2** non-operating items — minimal catalogue:

  * goodwill impairment
  * restructuring charges (identified as one-off by label)
  * gains / losses on disposal of PP&E or subsidiaries

OUT of Phase 1: B.3–B.10 (detailed treatment of multiple provision
categories, separating routine from special, etc). Those arrive with
the full reclassification engine in Phase 2.

Module B is **deterministic**: the classification leans on the IS
``category`` enum already assigned by the section extractor, with label
keyword matching as a backup when ``category == "other"``. No LLM call
is required.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from portfolio_thesis_engine.extraction.base import ExtractionContext, ExtractionModule
from portfolio_thesis_engine.llm.anthropic_provider import AnthropicProvider
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.common import Source
from portfolio_thesis_engine.schemas.company import ModuleAdjustment

# Label keywords → canonical non-operating type. The order matters: we
# want the most specific match to win (``goodwill impairment`` is more
# specific than ``impairment``).
_NON_OPERATING_LABEL_PATTERNS: tuple[tuple[str, str], ...] = (
    ("goodwill impairment", "goodwill_impairment"),
    ("goodwill write-down", "goodwill_impairment"),
    ("goodwill write down", "goodwill_impairment"),
    ("restructuring charge", "restructuring"),
    ("restructuring cost", "restructuring"),
    ("restructuring expense", "restructuring"),
    ("restructuring", "restructuring"),
    ("impairment of", "asset_impairment"),
    ("asset impairment", "asset_impairment"),
    ("gain on disposal", "disposal_gain_loss"),
    ("loss on disposal", "disposal_gain_loss"),
    ("gain on sale", "disposal_gain_loss"),
    ("loss on sale", "disposal_gain_loss"),
    ("gain on divestiture", "disposal_gain_loss"),
    ("loss on divestiture", "disposal_gain_loss"),
    ("litigation settlement", "litigation"),
    ("legal settlement", "litigation"),
)


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _classify_is_line(label: str, category: str) -> str | None:
    """Return the canonical non-operating type or ``None`` if the line is
    operating.

    Order of precedence:
    1. IS ``category == "non_operating"`` → already flagged; use label to
       pick a specific sub-type, default to ``"non_operating_other"``.
    2. Label keyword match → explicit type.
    3. Everything else → ``None`` (operating).
    """
    lowered = label.lower()
    if category == "non_operating":
        for keyword, subtype in _NON_OPERATING_LABEL_PATTERNS:
            if keyword in lowered:
                return subtype
        return "non_operating_other"

    for keyword, subtype in _NON_OPERATING_LABEL_PATTERNS:
        if keyword in lowered:
            return subtype
    return None


class ModuleBProvisions(ExtractionModule):
    """Provisions / non-operating items minimal reclassification."""

    module_id = "B"

    def __init__(
        self,
        llm: AnthropicProvider,
        cost_tracker: CostTracker,
    ) -> None:
        # Parity with other modules — Module B doesn't hit the LLM.
        self.llm = llm
        self.cost_tracker = cost_tracker

    # ------------------------------------------------------------------
    async def apply(self, context: ExtractionContext) -> ExtractionContext:
        is_section = context.find_section("income_statement")
        parsed: dict[str, Any] | None = is_section.parsed_data if is_section else None
        line_items = (parsed or {}).get("line_items") or []

        # B.0 — applicability
        if not line_items:
            context.decision_log.append(
                "Module B.0: no income_statement line items available; "
                "skipping non-operating reclassification."
            )
            return context

        source = Source(document=is_section.title) if is_section else None
        matches: list[tuple[str, Decimal, str, str]] = []  # (label, amount, subtype, category)

        for raw in line_items:
            label = str(raw.get("label", "") or "").strip()
            if not label:
                continue
            category = str(raw.get("category", "") or "").strip()
            amount = _to_decimal(raw.get("value_current"))
            if amount is None:
                continue
            subtype = _classify_is_line(label, category)
            if subtype is None:
                continue
            matches.append((label, amount, subtype, category or "other"))

        if not matches:
            context.decision_log.append(
                "Module B.1: no obvious non-operating items in income "
                "statement; operating profit left unchanged."
            )
            return context

        # B.2 — emit adjustments. Sign convention: amount is what the IS
        # reports (typically negative for expenses/losses, positive for
        # gains). The reclassification *removes* the item from operating
        # income; downstream NOPAT construction subtracts adjustments
        # with module == "B.*" from the operating-income pool.
        for label, amount, subtype, category in matches:
            context.adjustments.append(
                ModuleAdjustment(
                    module=f"B.2.{subtype}",
                    description=f"Non-operating item: {label}",
                    amount=amount,
                    affected_periods=[context.primary_period],
                    rationale=(
                        f"Classified as {subtype!r} (IS category '{category}'); "
                        f"moved below operating profit per B.2 framework."
                    ),
                    source=source,
                )
            )

        total = sum((m[1] for m in matches), start=Decimal("0"))
        context.decision_log.append(
            f"Module B.1: {len(matches)} non-operating item"
            f"{'' if len(matches) == 1 else 's'} reclassified "
            f"(sum {total})."
        )
        return context
