"""IRR decomposition — simple two-component split for Phase 1.

Given a target price (per-share from the equity bridge) and a current
market price, decompose the annualised return into:

- **Fundamental growth** — BV / equity growth implied at the
  scenario's ``revenue_cagr`` (acting as a proxy for earnings growth).
- **Multiple re-rating** — the residual that makes the decomposition
  add up to the total IRR.

Phase 1 sets the **dividend yield** at zero. Phase 2 will compute it
from :class:`CanonicalCompanyState.analysis.capital_allocation` once
the extractor captures multi-period dividend history.

The decomposition is deliberately algebraic (``fundamental + rerating
= total``) rather than empirical: with three components and one
equation, we can either derive two empirically and solve the third, or
derive one empirically and solve both others. For Phase 1 we derive
``fundamental`` from the scenario CAGR and solve for ``rerating`` —
that keeps the output legible and dependencies minimal.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from portfolio_thesis_engine.schemas.company import CanonicalCompanyState
from portfolio_thesis_engine.schemas.valuation import Scenario
from portfolio_thesis_engine.valuation.base import IRRResult, ValuationEngine

_ONE = Decimal("1")
_HUNDRED = Decimal("100")


class IRRDecomposer(ValuationEngine):
    """Annualised target-price IRR with fundamental / re-rating split."""

    def decompose(
        self,
        target_price: Decimal,
        current_price: Decimal,
        scenario: Scenario,
        canonical_state: CanonicalCompanyState,
        horizon_years: int = 3,
    ) -> IRRResult:
        if current_price <= 0:
            raise ValueError("current_price must be > 0")
        if horizon_years < 1:
            raise ValueError("horizon_years must be >= 1")

        # Non-positive target means the equity is projected worthless —
        # report a total wipeout (−100 % IRR) and let the decomposition
        # absorb everything into rerating. The alternative (raising)
        # would crash the scenario composer on deep bear cases.
        if target_price <= 0:
            total_irr = Decimal("-1")
        else:
            ratio = target_price / current_price
            total_irr = self._root(ratio, horizon_years) - _ONE

        # Fundamental growth: use the scenario's revenue CAGR as the
        # proxy (expressed as a decimal fraction). When absent, 0.
        cagr_pct = scenario.drivers.revenue_cagr
        fundamental = (cagr_pct / _HUNDRED) if cagr_pct is not None else Decimal("0")

        # Phase 1: no dividend yield. Phase 2 wires this from CF.
        dividend_yield = Decimal("0")

        # Solve for re-rating: total = fundamental + dividend_yield + rerating
        rerating = total_irr - fundamental - dividend_yield

        return IRRResult(
            total_p_a=total_irr,
            fundamental_p_a=fundamental,
            rerating_p_a=rerating,
            dividend_yield_p_a=dividend_yield,
            horizon_years=horizon_years,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _root(value: Decimal, n: int) -> Decimal:
        """Return ``value ** (1/n)`` with Decimal precision.

        Decimal doesn't support non-integer powers directly; we round-
        trip through float. Precision loss is negligible for IRR use.
        """
        return Decimal(str(float(value) ** (1.0 / float(n))))

    def describe(self) -> dict[str, Any]:
        return {"engine": "IRRDecomposer"}
