"""Module A — Operating Taxes (subset A.1–A.5).

Scope shipped here:

- **A.1** tax hierarchy: statutory → effective → operating. Operating
  rate is the anchor the rest of the pipeline uses for NOPAT.
- **A.2.0** materiality test: when the recurring reconciliation is
  immaterial (|Σ operating reconciling items| / |statutory_tax| < 5 %),
  skip the split and use the effective rate as operating.
- **A.2.1–A.2.5** operating vs non-operating classification of
  reconciling items. Relies on the ``category`` enum already set by
  :mod:`section_extractor`; falls back to keyword heuristics on the
  label for items tagged ``other``.
- **A.3** DTA/DTL: surfaced as a note in the decision log when the
  section is present. Phase 2 moves to structured adjustments once the
  IFRS reclass feeds them into the BS reclassification.
- **A.4** cash taxes: the difference between reported tax expense and
  cash taxes paid is surfaced in the log; not adjusted explicitly yet
  (waits on CF parser enrichment, Sprint 7).
- **A.5** BS treatment: tax payables/receivables are operating — the
  module emits a decision-log note to that effect.

OUT of Phase 1: A.6 TLCF valuation, A.7 advanced templates, A.8 deferred
mechanics, A.9 sector extensions.

The module is **deterministic** given the parsed section data. The
LLM-driven part happened upstream in section_extractor Pass 2, which
produced ``notes_taxes.parsed_data`` with a category-tagged reconciling-items
list; this module consumes that output. A second LLM call for
classification would add cost without adding accuracy.
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from portfolio_thesis_engine.extraction.base import ExtractionContext, ExtractionModule
from portfolio_thesis_engine.llm.anthropic_provider import AnthropicProvider
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.common import Source
from portfolio_thesis_engine.schemas.company import ModuleAdjustment

# Category → operating/non-operating mapping. These come from the enum
# in :mod:`section_extractor.tools` (``TAX_RECON_TOOL``'s reconciling-item
# ``category`` enum): we match on the canonical values so a typo in one
# place surfaces as a FAIL in the unit test.
_NON_OPERATING_CATEGORIES: frozenset[str] = frozenset(
    {
        "non_operating",
        "prior_year_adjustment",
    }
)
_OPERATING_CATEGORIES: frozenset[str] = frozenset(
    {
        "non_deductible",
        "tax_credit",
        "rate_diff_jurisdiction",
        "tax_loss_utilisation",
    }
)

# Keyword heuristics for ``category == "other"``. Conservative: when the
# label looks one-off, reclass as non-operating; otherwise keep in
# operating so the tax base stays representative of core operations.
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


def _to_decimal(value: Any) -> Decimal | None:
    """Coerce ``value`` to :class:`Decimal` or return ``None``.

    The section parser returns JSON numbers, which arrive as ``int`` or
    ``float``; pandas-style ``None`` and empty strings round-trip cleanly
    as well.
    """
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


class ModuleATaxes(ExtractionModule):
    """Operating taxes reclassification.

    Reads the ``notes_taxes`` parsed data produced by the section
    extractor; if absent or sparse, falls back to the WACC statutory
    rate and logs an estimate.
    """

    module_id = "A"

    def __init__(
        self,
        llm: AnthropicProvider,
        cost_tracker: CostTracker,
    ) -> None:
        # llm + cost_tracker carried for parity with Modules that do
        # call the LLM (Module C will); Module A itself is deterministic.
        self.llm = llm
        self.cost_tracker = cost_tracker

    # ------------------------------------------------------------------
    async def apply(self, context: ExtractionContext) -> ExtractionContext:
        tax_section = context.find_section("notes_taxes")
        parsed = tax_section.parsed_data if tax_section else None

        if parsed is None:
            self._fallback_to_statutory(context, reason="no notes_taxes section")
            return context

        effective_rate = _to_decimal(parsed.get("effective_rate_pct"))
        reported_tax = _to_decimal(parsed.get("reported_tax_expense"))
        statutory_tax = _to_decimal(parsed.get("statutory_tax"))
        profit_before_tax = _to_decimal(parsed.get("profit_before_tax"))
        reconciling = parsed.get("reconciling_items") or []

        if effective_rate is None or reported_tax is None:
            self._fallback_to_statutory(
                context,
                reason="notes_taxes missing effective_rate or reported_tax",
            )
            return context

        # Classify each reconciling item; running totals of the two
        # buckets let us compute the operating rate without needing a
        # clean ``statutory_tax`` field.
        operating_items: list[tuple[str, Decimal, str]] = []
        non_operating_items: list[tuple[str, Decimal, str]] = []
        for raw in reconciling:
            label = str(raw.get("label", "")).strip() or "(unlabelled)"
            amount = _to_decimal(raw.get("amount"))
            if amount is None:
                continue
            category = str(raw.get("category", "") or "").strip()
            bucket = self._classify(category, label)
            if bucket == "non_operating":
                non_operating_items.append((label, amount, category or "other"))
            else:
                operating_items.append((label, amount, category or "other"))

        non_operating_sum = sum((a for _, a, _ in non_operating_items), start=Decimal("0"))
        operating_sum = sum((a for _, a, _ in operating_items), start=Decimal("0"))

        # A.2.0 — materiality. When the sum of non-operating items is tiny
        # relative to the statutory tax, keep ``operating_tax_rate ==
        # effective_tax_rate`` (divide-by-zero safe: fall through when we
        # don't have statutory_tax).
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
            # A.2.1-A.2.5: operating tax = effective tax - non-operating
            # reconciling items. As a rate: divide by profit before tax.
            # When profit_before_tax isn't published, back it out from
            # reported_tax / effective_rate.
            pbt = profit_before_tax
            if pbt is None and effective_rate and effective_rate != 0:
                pbt = reported_tax / (effective_rate / Decimal("100"))
            if pbt is None or pbt == 0:
                # No PBT and no way to derive it — fall back to statutory.
                self._fallback_to_statutory(
                    context,
                    reason="could not derive profit_before_tax",
                )
                return context

            operating_tax_expense = reported_tax - non_operating_sum
            operating_tax_rate = (operating_tax_expense / pbt) * Decimal("100")
            context.decision_log.append(
                f"Module A.2: operating tax rate = {operating_tax_rate:.2f}% "
                f"(effective {effective_rate:.2f}%, "
                f"{len(non_operating_items)} non-operating reconciling item"
                f"{'' if len(non_operating_items) == 1 else 's'} removed, "
                f"sum {non_operating_sum})."
            )

        # A.2.2 — emit one ModuleAdjustment per non-operating item so the
        # audit trail survives aggregation.
        source = Source(document=tax_section.title) if tax_section else None
        for label, amount, category in non_operating_items:
            context.adjustments.append(
                ModuleAdjustment(
                    module="A.2",
                    description=f"Non-operating tax reconciling item: {label}",
                    amount=amount,
                    affected_periods=[context.primary_period],
                    rationale=(
                        f"Category '{category}' classified as non-operating; "
                        f"removed from operating tax base per A.2.2."
                    ),
                    source=source,
                )
            )

        # A.1 — always emit the operating-tax-rate decision as a separate
        # adjustment (amount = the rate itself, as a Decimal percent). Makes
        # downstream NOPAT construction a single lookup instead of a scan.
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

        # A.3 — DTA/DTL note (no explicit adjustment in Phase 1; logged
        # for the audit trail so the vintage/cascade module downstream
        # can pick it up in Phase 2).
        dta = _to_decimal(parsed.get("deferred_tax_asset"))
        dtl = _to_decimal(parsed.get("deferred_tax_liability"))
        if dta is not None or dtl is not None:
            context.decision_log.append(
                f"Module A.3: DTA={dta} DTL={dtl} observed — logged; "
                f"explicit BS reclass deferred to Phase 2."
            )

        # A.4 — cash taxes (if disclosed separately in the note).
        cash_tax = _to_decimal(parsed.get("cash_taxes_paid"))
        if cash_tax is not None and reported_tax is not None:
            delta = reported_tax - cash_tax
            context.decision_log.append(
                f"Module A.4: cash taxes paid {cash_tax} vs reported "
                f"{reported_tax} (Δ={delta}); kept on cash-flow view."
            )

        # A.5 — BS treatment note (tax payables/receivables = operating).
        context.decision_log.append(
            "Module A.5: tax payables/receivables classified as operating "
            "working capital (BS reclassification applied in Sprint 7)."
        )

        # Summary recap for estimators list if no PBT was published.
        if profit_before_tax is None:
            context.estimates_log.append(
                "Module A: profit_before_tax derived from reported_tax / "
                "effective_rate (not directly disclosed in notes_taxes)."
            )
        if operating_items:
            context.decision_log.append(
                f"Module A.2.1: {len(operating_items)} operating reconciling "
                f"item{'' if len(operating_items) == 1 else 's'} retained "
                f"(sum {operating_sum})."
            )

        return context

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _fallback_to_statutory(self, context: ExtractionContext, *, reason: str) -> None:
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

    def _classify(self, category: str, label: str) -> str:
        """Return ``"operating"`` or ``"non_operating"``.

        Uses the enum tag first; falls back to label-keyword heuristics
        when the category is ``other`` (or blank, which happens when the
        LLM failed to supply one).
        """
        if category in _NON_OPERATING_CATEGORIES:
            return "non_operating"
        if category in _OPERATING_CATEGORIES:
            return "operating"
        lowered = label.lower()
        if any(kw in lowered for kw in _NON_OPERATING_LABEL_KEYWORDS):
            return "non_operating"
        return "operating"
