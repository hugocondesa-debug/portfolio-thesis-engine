"""Module C — Leases (IFRS 16, subset C.0–C.3).

Scope shipped here:

- **C.0** applicability: when `notes_leases` is absent or its parsed
  payload is empty, log and return without adjustments. Matches the
  spec's "assuming no material leases" path.
- **C.1** IFRS 16 base: surface the ROU asset total and the lease
  liability movement structure on the decision log so the audit
  trail captures what the section extractor recovered.
- **C.2** capitalization basics: lease liabilities (opening/closing)
  flow into the BS reclassification in Sprint 7+; Module C records
  the totals for that downstream use.
- **C.3** lease additions for the FCFF economic view. ``additions``
  comes straight from the lease-liability movement when disclosed;
  otherwise we back it out as
  ``closing − opening + principal_payments`` (a
  standard IFRS 16 identity). The result is one
  :class:`ModuleAdjustment` with ``module="C.3"``, whose amount the
  Sprint 7 FCFF construction adds to reinvestment.

OUT of Phase 1: C.4+ (operating vs finance lease distinctions,
sale-leaseback patches, sector extensions).

The module is **deterministic**. The LLM work happened upstream in
section_extractor Pass 2 via ``LEASES_TOOL``; Module C consumes the
parsed_data dict.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from portfolio_thesis_engine.extraction.base import ExtractionContext, ExtractionModule
from portfolio_thesis_engine.llm.anthropic_provider import AnthropicProvider
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.common import Source
from portfolio_thesis_engine.schemas.company import ModuleAdjustment


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


class ModuleCLeases(ExtractionModule):
    """IFRS 16 lease reclassification — base + FCFF additions."""

    module_id = "C"

    def __init__(
        self,
        llm: AnthropicProvider,
        cost_tracker: CostTracker,
    ) -> None:
        # Parity with sibling modules — Module C doesn't hit the LLM
        # in Sprint 7 either: the notes_leases section was parsed by
        # section_extractor Pass 2 via LEASES_TOOL.
        self.llm = llm
        self.cost_tracker = cost_tracker

    # ------------------------------------------------------------------
    async def apply(self, context: ExtractionContext) -> ExtractionContext:
        leases_section = context.find_section("notes_leases")
        parsed: dict[str, Any] | None = (
            leases_section.parsed_data if leases_section else None
        )

        # C.0 — applicability
        if not parsed:
            context.decision_log.append(
                "Module C.0: no notes_leases section parsed; assuming no "
                "material IFRS 16 lease activity."
            )
            return context

        movement = parsed.get("lease_liability_movement") or {}
        rou_categories = parsed.get("rou_assets_by_category") or []

        rou_total = sum(
            (x for x in (_to_decimal(r.get("value_current")) for r in rou_categories) if x),
            start=Decimal("0"),
        )
        opening = _to_decimal(movement.get("opening_balance"))
        closing = _to_decimal(movement.get("closing_balance"))
        additions_disclosed = _to_decimal(movement.get("additions"))
        principal_payments = _to_decimal(movement.get("principal_payments"))
        depreciation_rou = _to_decimal(movement.get("depreciation_of_rou"))
        interest_expense = _to_decimal(movement.get("interest_expense"))

        # C.1 — base audit-trail note
        context.decision_log.append(
            f"Module C.1: IFRS 16 base — ROU total {rou_total} across "
            f"{len(rou_categories)} categor"
            f"{'y' if len(rou_categories) == 1 else 'ies'}, "
            f"lease liability opening {opening} / closing {closing}."
        )

        # C.2 — capitalization basics: log the lease liability balance
        # that flows into BS reclass downstream.
        if closing is not None:
            context.decision_log.append(
                f"Module C.2: lease liability capitalized on BS = {closing} "
                f"(downstream reclassification in Sprint 7)."
            )

        # C.3 — lease additions. Prefer the disclosed field; otherwise
        # back out from the movement identity
        # closing = opening + additions − principal_payments − depreciation_of_rou
        # Solving for additions: closing − opening + principal_payments + depreciation_of_rou.
        # (Reporters vary: some include depreciation in the liability
        # movement, others only touch the liability with additions +
        # interest − payments. We default to the more common shape and
        # surface an estimate note if we had to derive it.)
        additions = additions_disclosed
        derived = False
        if additions is None and opening is not None and closing is not None:
            additions = closing - opening
            if principal_payments is not None:
                additions += principal_payments
            if depreciation_rou is not None:
                # Only used when the movement table mixes P&L items in.
                # Most disclosures put depreciation on the ROU side, not
                # the liability side — but we don't want to guess.
                pass
            derived = True

        if additions is None:
            context.estimates_log.append(
                "Module C.3: lease additions could not be derived "
                "(opening/closing balance missing). Skipping adjustment."
            )
            return context

        source = Source(document=leases_section.title) if leases_section else None
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

        # Book-keeping extras kept out of the adjustments list — these
        # land on downstream NOPAT / ratio computations in Sprint 7.
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
