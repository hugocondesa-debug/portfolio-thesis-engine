"""ValuationComposer — build the final :class:`ValuationSnapshot`.

Combines:

- Three :class:`Scenario` objects from :class:`ScenarioComposer` (each
  already carries its per-share target + IRR breakdown).
- :class:`MarketSnapshot` from the market data provider (price, shares,
  currency).
- :class:`CanonicalCompanyState` for identity + vintage reference.
- An optional :class:`GuardrailsStatus` stub (Phase 1 placeholder).

Produces :class:`ValuationSnapshot` — immutable, versioned, ready to
persist via :class:`ValuationRepository`.

Phase 1 scope on :attr:`WeightedOutputs`:

- ``expected_value`` = Σ probability × per-share target (normalised to
  fractions so probabilities of ``[25, 50, 25]`` work correctly).
- ``fair_value_range_low / high`` = min / max per-share across
  scenarios.
- ``upside_pct`` vs current market price.
- ``asymmetry_ratio`` = upside_to_bull / downside_to_bear (signed),
  defaulting to ``0`` when either leg is degenerate.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from portfolio_thesis_engine.schemas.common import ConvictionLevel, GuardrailStatus
from portfolio_thesis_engine.schemas.company import CanonicalCompanyState
from portfolio_thesis_engine.schemas.valuation import (
    Conviction,
    GuardrailCategory,
    GuardrailsStatus,
    MarketSnapshot,
    Scenario,
    ValuationSnapshot,
    WeightedOutputs,
)

_FORECAST_SYSTEM_VERSION = "phase1-sprint9"


class ValuationComposer:
    """Compose the final valuation snapshot from scenarios + market."""

    def compose(
        self,
        canonical_state: CanonicalCompanyState,
        scenarios: list[Scenario],
        market: MarketSnapshot,
        *,
        guardrails: GuardrailsStatus | None = None,
        conviction: Conviction | None = None,
    ) -> ValuationSnapshot:
        if not scenarios:
            raise ValueError("ValuationComposer requires at least one scenario")

        weighted = self._weighted_outputs(scenarios, market)

        now = datetime.now(UTC)
        ts = now.strftime("%Y%m%dT%H%M%SZ")
        ticker = canonical_state.identity.ticker
        snapshot_id = f"{ticker.replace('.', '-')}_{ts}"

        return ValuationSnapshot(
            version=1,
            created_at=now,
            created_by=_FORECAST_SYSTEM_VERSION,
            snapshot_id=snapshot_id,
            ticker=ticker,
            company_name=canonical_state.identity.name,
            profile=canonical_state.identity.profile,
            valuation_date=now,
            based_on_extraction_id=canonical_state.extraction_id,
            based_on_extraction_date=canonical_state.extraction_date,
            market=market,
            scenarios=scenarios,
            weighted=weighted,
            conviction=conviction or _default_conviction(),
            guardrails=guardrails or _default_guardrails_stub(),
            forecast_system_version=_FORECAST_SYSTEM_VERSION,
            source_documents=list(canonical_state.source_documents),
        )

    # ------------------------------------------------------------------
    # Weighted outputs
    # ------------------------------------------------------------------
    def _weighted_outputs(
        self,
        scenarios: list[Scenario],
        market: MarketSnapshot,
    ) -> WeightedOutputs:
        per_shares: list[Decimal] = []
        prob_weighted_sum = Decimal("0")
        prob_weighted_irr = Decimal("0")
        prob_total = Decimal("0")

        for sc in scenarios:
            ps = sc.targets.get("dcf_fcff_per_share")
            if ps is None:
                continue
            prob_frac = sc.probability / Decimal("100")
            per_shares.append(ps)
            prob_weighted_sum += ps * prob_frac
            prob_total += prob_frac
            if sc.irr_3y is not None:
                prob_weighted_irr += sc.irr_3y * prob_frac

        if not per_shares:
            # Degenerate: no usable per-share targets; fall back to current
            # market price so downstream calculations don't crash.
            expected_value = market.price
            fv_low = market.price
            fv_high = market.price
            upside = Decimal("0")
            asymmetry = Decimal("0")
            weighted_irr: Decimal | None = None
        else:
            # Renormalise in case probabilities don't sum to 1 exactly
            # (schema allows ±0.5 % tolerance; renormalising keeps the
            # headline E[V] exactly the probability-weighted mean).
            if prob_total != 0:
                expected_value = prob_weighted_sum / prob_total
            else:
                expected_value = sum(per_shares) / Decimal(len(per_shares))
            fv_low = min(per_shares)
            fv_high = max(per_shares)
            upside = (
                (expected_value - market.price) / market.price * Decimal("100")
                if market.price != 0
                else Decimal("0")
            )
            asymmetry = self._asymmetry(fv_low, fv_high, market.price)
            weighted_irr = prob_weighted_irr / prob_total if prob_total != 0 else None

        return WeightedOutputs(
            expected_value=expected_value,
            expected_value_method_used="DCF_FCFF",
            fair_value_range_low=fv_low,
            fair_value_range_high=fv_high,
            upside_pct=upside,
            asymmetry_ratio=asymmetry,
            weighted_irr_3y=weighted_irr,
        )

    @staticmethod
    def _asymmetry(fv_low: Decimal, fv_high: Decimal, price: Decimal) -> Decimal:
        """Up / down asymmetry ratio.

        ``(fv_high − price) / max(price − fv_low, ε)``. When the bear
        case is *above* current (rare — all-bull valuation), the downside
        term flips sign; we clip with a tiny ε to keep the ratio finite.
        """
        upside = fv_high - price
        downside = price - fv_low
        if downside <= 0:
            # Entire range is upside — ratio is "infinite" in spirit;
            # report a large finite number so downstream UI can render.
            return Decimal("999") if upside > 0 else Decimal("0")
        return upside / downside


# ----------------------------------------------------------------------
# Defaults for Phase 1 placeholders
# ----------------------------------------------------------------------
def _default_conviction() -> Conviction:
    """All-MEDIUM default — analyst edits downstream."""
    return Conviction(
        forecast=ConvictionLevel.MEDIUM,
        valuation=ConvictionLevel.MEDIUM,
        asymmetry=ConvictionLevel.MEDIUM,
        timing_risk=ConvictionLevel.MEDIUM,
        liquidity_risk=ConvictionLevel.MEDIUM,
        governance_risk=ConvictionLevel.MEDIUM,
    )


def _default_guardrails_stub() -> GuardrailsStatus:
    """Phase 1 placeholder — Sprint 8 guardrails don't yet feed the
    :class:`ValuationSnapshot` guardrails block; they live on the
    canonical state. Populate with an empty overall PASS so the
    snapshot is a valid Pydantic object."""
    return GuardrailsStatus(
        categories=[
            GuardrailCategory(
                category="valuation",
                total=0,
                passed=0,
                warned=0,
                failed=0,
                skipped=0,
                notes=["Phase 1 stub — guardrails run on canonical state only."],
            )
        ],
        overall=GuardrailStatus.PASS,
    )
