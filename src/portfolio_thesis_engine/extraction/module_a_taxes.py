"""Module A — Operating Taxes (subset A.1–A.5).

Phase 1.5 / Sprint 3 rewrite: consumes :class:`RawExtraction` directly.
The human extractor tags each :class:`TaxReconciliationItem` with a
:data:`TaxItemClassification` literal (``operational`` /
``non_operational`` / ``one_time`` / ``unknown``); Module A routes on
that vocabulary without any intermediate mapping.

Scope shipped here:

- **A.1** tax hierarchy: statutory → effective → operating. Operating
  rate is the anchor the rest of the pipeline uses for NOPAT.
- **A.2.0** materiality: when the sum of non-operating items is small
  vs. the statutory tax (``< 5 %``), skip the split and use the
  effective rate as operating.
- **A.2.1–A.2.5** operating vs non-operating classification. Non-op
  buckets: ``non_operational`` + ``one_time``. ``unknown`` falls back
  to a label-keyword heuristic.
- **A.3** DTA/DTL: out of scope for Phase 1.5 raw schema (no fields in
  :class:`TaxNote`); log when a BS note surfaces them in later phases.
- **A.4** cash taxes: log the delta vs reported expense when cash
  taxes are disclosed on the CF.
- **A.5** BS treatment: tax payables/receivables = operating (note).

OUT of Phase 1: A.6–A.9 (TLCF valuation, advanced templates, deferred
mechanics, sector extensions).

The module is **deterministic** — no LLM calls.
"""

from __future__ import annotations

from decimal import Decimal

from portfolio_thesis_engine.extraction.base import ExtractionContext, ExtractionModule
from portfolio_thesis_engine.llm.anthropic_provider import AnthropicProvider
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.common import Source
from portfolio_thesis_engine.schemas.company import ModuleAdjustment
from portfolio_thesis_engine.schemas.raw_extraction import TaxReconciliationItem

# Classifications that are always non-operating.
_NON_OPERATING_CLASSIFICATIONS: frozenset[str] = frozenset(
    {"non_operational", "one_time"}
)

# Label heuristics for ``classification == "unknown"``. Conservative —
# one-off-sounding items move to non-op; anything else stays operating.
_NON_OPERATING_LABEL_KEYWORDS: tuple[str, ...] = (
    "goodwill",
    "impairment",
    "disposal",
    "restructuring",
    "one-off",
    "prior year",
    "acquisition",
    "settlement",
    "litigation",
)

_MATERIALITY_THRESHOLD = Decimal("0.05")  # 5 % of statutory tax


class ModuleATaxes(ExtractionModule):
    """Operating taxes reclassification from a :class:`RawExtraction`."""

    module_id = "A"

    def __init__(
        self,
        llm: AnthropicProvider,
        cost_tracker: CostTracker,
    ) -> None:
        # llm + cost_tracker carried for parity with modules that may
        # call the LLM; Module A itself is deterministic.
        self.llm = llm
        self.cost_tracker = cost_tracker

    # ------------------------------------------------------------------
    async def apply(self, context: ExtractionContext) -> ExtractionContext:
        raw = context.raw_extraction
        tax_note = raw.notes.taxes
        is_data = raw.primary_is

        if tax_note is None:
            self._fallback_to_statutory(context, reason="no taxes note")
            return context

        effective_rate = tax_note.effective_tax_rate_percent
        statutory_rate = tax_note.statutory_rate_percent

        # Derive reported tax + PBT + statutory_tax from the IS.
        reported_tax = abs(is_data.income_tax) if is_data and is_data.income_tax is not None else None
        pbt = is_data.income_before_tax if is_data else None
        statutory_tax: Decimal | None = None
        if pbt is not None and statutory_rate is not None:
            statutory_tax = pbt * statutory_rate / Decimal("100")

        if effective_rate is None or reported_tax is None:
            self._fallback_to_statutory(
                context,
                reason="taxes note missing effective_rate or IS missing income_tax",
            )
            return context

        # Classify each reconciling item; running totals give the
        # operating rate without needing a clean statutory_tax.
        operating_items: list[tuple[str, Decimal, str]] = []
        non_operating_items: list[tuple[str, Decimal, str]] = []
        for item in tax_note.reconciling_items:
            bucket = self._classify(item)
            if bucket == "non_operating":
                non_operating_items.append(
                    (item.description, item.amount, item.classification)
                )
            else:
                operating_items.append(
                    (item.description, item.amount, item.classification)
                )

        non_operating_sum = sum(
            (a for _, a, _ in non_operating_items), start=Decimal("0")
        )
        operating_sum = sum(
            (a for _, a, _ in operating_items), start=Decimal("0")
        )

        # A.2.0 — materiality. Tiny non-op items vs statutory_tax ⇒ use
        # the effective rate as operating rather than split.
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
            # A.2.1-A.2.5: operating tax = reported_tax − non-operating
            # reconciling items. As a rate: divide by PBT. Back it out
            # from reported_tax / effective_rate when PBT not published.
            effective_pbt = pbt
            if effective_pbt is None and effective_rate != 0:
                effective_pbt = reported_tax / (effective_rate / Decimal("100"))
            if effective_pbt is None or effective_pbt == 0:
                self._fallback_to_statutory(
                    context,
                    reason="could not derive profit_before_tax",
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

        # A.2.2 — one ModuleAdjustment per non-operating item so the
        # audit trail survives aggregation.
        source = Source(document="notes.taxes")
        for description, amount, classification in non_operating_items:
            context.adjustments.append(
                ModuleAdjustment(
                    module="A.2",
                    description=f"Non-operating tax reconciling item: {description}",
                    amount=amount,
                    affected_periods=[context.primary_period],
                    rationale=(
                        f"Classification '{classification}' → non-operating; "
                        f"removed from operating tax base per A.2.2."
                    ),
                    source=source,
                )
            )

        # A.1 — operating-tax-rate adjustment (amount = rate as Decimal pct).
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

        # A.4 — cash taxes, if the CF surfaces a cash-taxes line via
        # extensions. The raw schema doesn't carry it as a typed field,
        # so we look in the CF extensions dict.
        cf = raw.primary_cf
        cash_tax = None
        if cf is not None:
            for key in ("cash_taxes_paid", "income_taxes_paid"):
                if key in cf.extensions:
                    cash_tax = cf.extensions[key]
                    break
        if cash_tax is not None:
            delta = reported_tax - abs(cash_tax)
            context.decision_log.append(
                f"Module A.4: cash taxes paid {abs(cash_tax)} vs reported "
                f"{reported_tax} (Δ={delta}); kept on cash-flow view."
            )

        # A.5 — BS treatment note.
        context.decision_log.append(
            "Module A.5: tax payables/receivables classified as operating "
            "working capital (applied in BS reclassification)."
        )

        if pbt is None:
            context.estimates_log.append(
                "Module A: profit_before_tax derived from reported_tax / "
                "effective_rate (not directly disclosed in IS)."
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
        """Use the WACC statutory rate as the operating tax rate."""
        statutory = context.wacc_inputs.cost_of_capital.tax_rate_for_wacc
        context.estimates_log.append(
            f"Module A: falling back to statutory tax rate {statutory}% "
            f"from WACCInputs ({reason})."
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

    def _classify(self, item: TaxReconciliationItem) -> str:
        """Return ``"operating"`` or ``"non_operating"`` for one item."""
        classification = item.classification
        if classification in _NON_OPERATING_CLASSIFICATIONS:
            return "non_operating"
        if classification == "operational":
            return "operating"
        # unknown → label-keyword fallback
        lowered = item.description.lower()
        if any(kw in lowered for kw in _NON_OPERATING_LABEL_KEYWORDS):
            return "non_operating"
        return "operating"
