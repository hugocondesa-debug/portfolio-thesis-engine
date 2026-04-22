"""Module C — Leases (IFRS 16, subset C.0–C.3).

Phase 1.5 / Sprint 3 rewrite: consumes :class:`RawExtraction` directly
via :class:`LeaseNote`. No more ``lease_liability_movement`` dict
traversal — every input is a typed ``Decimal | None`` on the note.

Scope shipped here:

- **C.0** applicability — when :attr:`NotesContainer.leases` is absent,
  log and return without adjustments.
- **C.1** IFRS 16 base — surface ROU closing + lease liability
  opening/closing so the audit trail captures what was recovered.
- **C.2** capitalization basics — log the lease-liability balance that
  flows into the BS reclassification.
- **C.3** lease additions for the FCFF economic view.
  Prefer the disclosed ``rou_assets_additions`` field; otherwise back
  it out from the movement identity
  ``closing − opening + principal_payments``. Emits one
  ``ModuleAdjustment`` with ``module="C.3"``.

OUT of Phase 1: C.4+ (operating vs finance, sale-leaseback, sector
extensions).
"""

from __future__ import annotations

from portfolio_thesis_engine.extraction.base import ExtractionContext, ExtractionModule
from portfolio_thesis_engine.llm.anthropic_provider import AnthropicProvider
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.common import Source
from portfolio_thesis_engine.schemas.company import ModuleAdjustment


class ModuleCLeases(ExtractionModule):
    """IFRS 16 lease reclassification — base + FCFF additions."""

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
        leases = context.raw_extraction.notes.leases

        if leases is None:
            context.decision_log.append(
                "Module C.0: no leases note; assuming no material IFRS 16 "
                "lease activity."
            )
            return context

        rou_closing = leases.rou_assets_closing
        liab_opening = leases.lease_liabilities_opening
        liab_closing = leases.lease_liabilities_closing
        additions_disclosed = leases.rou_assets_additions
        principal_payments = leases.lease_principal_payments
        depreciation_rou = leases.rou_assets_depreciation
        interest_expense = leases.lease_interest_expense

        # C.1 — base audit-trail note
        context.decision_log.append(
            f"Module C.1: IFRS 16 base — ROU closing {rou_closing}, "
            f"lease liability opening {liab_opening} / closing {liab_closing}."
        )

        # C.2 — capitalization basics
        if liab_closing is not None:
            context.decision_log.append(
                f"Module C.2: lease liability capitalized on BS = {liab_closing} "
                f"(downstream BS reclassification)."
            )

        # C.3 — lease additions. Prefer the disclosed field; otherwise
        # back out: additions = closing − opening + principal_payments.
        additions = additions_disclosed
        derived = False
        if additions is None and liab_opening is not None and liab_closing is not None:
            additions = liab_closing - liab_opening
            if principal_payments is not None:
                additions += principal_payments
            derived = True

        if additions is None:
            context.estimates_log.append(
                "Module C.3: lease additions could not be derived "
                "(opening/closing balance missing). Skipping adjustment."
            )
            return context

        source = Source(document="notes.leases")
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
                "Module C.3: lease additions derived from movement "
                "identity (additions not disclosed directly)."
            )

        if interest_expense is not None:
            context.decision_log.append(
                f"Module C.3: interest on lease liabilities = {interest_expense} "
                f"(kept in financial expense line for NOPAT bridge)."
            )
        if depreciation_rou is not None:
            context.decision_log.append(
                f"Module C.3: ROU depreciation = {depreciation_rou} "
                f"(operating expense component of EBITA)."
            )

        return context
