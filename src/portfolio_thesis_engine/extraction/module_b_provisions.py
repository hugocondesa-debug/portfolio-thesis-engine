"""Module B — Provisions & non-operating items (minimal, B.0–B.2).

Phase 1.5 / Sprint 3 rewrite: consumes :class:`RawExtraction` directly.
Instead of scanning an IS ``line_items`` list for non-op labels, we now
read the typed carriers the human extractor fills in:

- :attr:`NotesContainer.provisions` — a list of
  :class:`ProvisionItem`, each tagged with a
  :data:`ProvisionClassification` literal.
- :attr:`NotesContainer.goodwill.impairment` — single Decimal surfaces
  a ``B.2.goodwill_impairment`` adjustment.
- :attr:`NotesContainer.discontinued_ops` — logged when present and
  flows through the IS ``net_income_from_discontinued`` field.
- IS non-op fields: ``non_operating_income``, ``share_of_associates``,
  ``net_income_from_discontinued``. Each surfaces as a separate
  ``B.2.*`` adjustment.

Scope shipped here:

- **B.0** applicability — when neither the IS nor the notes expose any
  non-op lines, the module returns a no-op (logged).
- **B.1** operating vs EBITA framework — operating income stays as
  reported on the IS. Everything flagged below lands below the line.
- **B.2** non-operating items catalogue:

  * goodwill impairment
  * provisions classified as ``restructuring`` / ``impairment`` /
    ``non_operating`` on the notes
  * IS non-op fields

OUT of Phase 1: B.3–B.10. The module is **deterministic** — no LLM.
"""

from __future__ import annotations

from decimal import Decimal

from portfolio_thesis_engine.extraction.base import ExtractionContext, ExtractionModule
from portfolio_thesis_engine.llm.anthropic_provider import AnthropicProvider
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.common import Source
from portfolio_thesis_engine.schemas.company import ModuleAdjustment

# Provision classifications that move below operating income.
_NON_OPERATING_PROVISION_CLASSIFICATIONS: frozenset[str] = frozenset(
    {"non_operating", "restructuring", "impairment"}
)

# Map provision classification → B.2 subtype for the adjustment module id.
_PROVISION_SUBTYPE: dict[str, str] = {
    "restructuring": "restructuring",
    "impairment": "asset_impairment",
    "non_operating": "non_operating_other",
}


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
        is_data = raw.primary_is
        notes = raw.notes

        adjustments_added = 0

        # --- Goodwill impairment (notes.goodwill.impairment) ----------
        if notes.goodwill is not None and notes.goodwill.impairment is not None:
            amount = notes.goodwill.impairment
            if amount != 0:
                context.adjustments.append(
                    ModuleAdjustment(
                        module="B.2.goodwill_impairment",
                        description="Goodwill impairment (from notes.goodwill)",
                        amount=amount,
                        affected_periods=[context.primary_period],
                        rationale=(
                            "Goodwill impairment is one-off by nature; "
                            "moved below operating profit per B.2."
                        ),
                        source=Source(document="notes.goodwill"),
                    )
                )
                adjustments_added += 1

        # --- Provisions flagged as non-operating ---------------------
        for provision in notes.provisions:
            if provision.classification not in _NON_OPERATING_PROVISION_CLASSIFICATIONS:
                continue
            subtype = _PROVISION_SUBTYPE[provision.classification]
            context.adjustments.append(
                ModuleAdjustment(
                    module=f"B.2.{subtype}",
                    description=f"Non-operating provision: {provision.description}",
                    amount=provision.amount,
                    affected_periods=[context.primary_period],
                    rationale=(
                        f"Classification '{provision.classification}' → "
                        f"moved below operating profit per B.2."
                    ),
                    source=Source(document="notes.provisions"),
                )
            )
            adjustments_added += 1

        # --- IS non-operating fields ---------------------------------
        if is_data is not None:
            is_source = Source(document="income_statement")
            if (
                is_data.non_operating_income is not None
                and is_data.non_operating_income != 0
            ):
                context.adjustments.append(
                    ModuleAdjustment(
                        module="B.2.non_operating_other",
                        description="Non-operating income (IS)",
                        amount=is_data.non_operating_income,
                        affected_periods=[context.primary_period],
                        rationale=(
                            "Reported below operating profit on the IS; "
                            "kept out of the operating-tax base per B.2."
                        ),
                        source=is_source,
                    )
                )
                adjustments_added += 1
            if (
                is_data.share_of_associates is not None
                and is_data.share_of_associates != 0
            ):
                context.adjustments.append(
                    ModuleAdjustment(
                        module="B.2.associates",
                        description="Share of associates (IS)",
                        amount=is_data.share_of_associates,
                        affected_periods=[context.primary_period],
                        rationale=(
                            "Equity-method income is capital-structure-agnostic; "
                            "treated as non-operating for NOPAT per B.2."
                        ),
                        source=is_source,
                    )
                )
                adjustments_added += 1
            if (
                is_data.net_income_from_discontinued is not None
                and is_data.net_income_from_discontinued != 0
            ):
                context.adjustments.append(
                    ModuleAdjustment(
                        module="B.2.discontinued",
                        description="Net income from discontinued operations (IS)",
                        amount=is_data.net_income_from_discontinued,
                        affected_periods=[context.primary_period],
                        rationale=(
                            "Discontinued ops are out of the continuing-"
                            "operating base per B.2."
                        ),
                        source=is_source,
                    )
                )
                adjustments_added += 1

        # --- Discontinued-ops note (log only; the IS field drives the adj) ---
        if notes.discontinued_ops is not None:
            ni = notes.discontinued_ops.net_income
            if ni is not None:
                context.decision_log.append(
                    f"Module B: discontinued-ops note present "
                    f"(net_income={ni}); covered by IS adjustment when "
                    f"net_income_from_discontinued populated."
                )

        # --- B.0 applicability ---------------------------------------
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
