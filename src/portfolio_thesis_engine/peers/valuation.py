"""Phase 2 Sprint 3 — peer-relative valuation.

Two complementary views:

- **Multiples**: target vs peer-median P/E, EV/EBITDA, EV/Sales;
  implied values using peer medians; ROIC / margin / growth
  positioning.
- **Regression**: simple OLS of a multiple on peer fundamentals
  (ROIC, growth, margin). Requires at least ``min_peers`` observations;
  skipped otherwise.

All math runs on :mod:`decimal` inputs; regression converts to float
via numpy since OLS on a Decimal matrix isn't practical.
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np

from portfolio_thesis_engine.schemas.peers import (
    PeerComparison,
    PeerValuation,
    PeerValuationMultiples,
    PeerValuationRegression,
)


_BPS = Decimal("10000")


def _positioning(delta_bps: Decimal | None, threshold_bps: int = 100) -> str | None:
    if delta_bps is None:
        return None
    if delta_bps > threshold_bps:
        return "ABOVE_PEER"
    if delta_bps < -threshold_bps:
        return "BELOW_PEER"
    return "IN_LINE"


def _valuation_positioning(
    discount_pct: Decimal | None, threshold_pct: Decimal = Decimal("5")
) -> str | None:
    if discount_pct is None:
        return None
    if discount_pct > threshold_pct:
        return "PREMIUM"
    if discount_pct < -threshold_pct:
        return "DISCOUNT"
    return "IN_LINE"


def _discount_pct(target: Decimal | None, median: Decimal | None) -> Decimal | None:
    if target is None or median is None or median == 0:
        return None
    return (target - median) / median * Decimal("100")


class PeerValuationBuilder:
    def __init__(self, min_peers: int = 5) -> None:
        self.min_peers = min_peers

    # ------------------------------------------------------------------
    def build(self, comparison: PeerComparison) -> PeerValuation:
        multiples = self._build_multiples(comparison)
        regression = self._build_regression(comparison)
        bullets = _summary_bullets(comparison, multiples, regression)
        return PeerValuation(
            target_ticker=comparison.target_ticker,
            multiples=multiples,
            regression=regression,
            summary_bullets=bullets,
        )

    # ------------------------------------------------------------------
    def _build_multiples(
        self, comparison: PeerComparison
    ) -> PeerValuationMultiples | None:
        medians = comparison.peer_median
        target = comparison.target_fundamentals
        if not medians:
            return None
        pe_discount = _discount_pct(
            target.price_to_earnings, medians.get("price_to_earnings")
        )
        ev_ebitda_discount = _discount_pct(
            target.ev_to_ebitda, medians.get("ev_to_ebitda")
        )
        ev_sales_discount = _discount_pct(
            target.ev_to_sales, medians.get("ev_to_sales")
        )
        roic_bps = comparison.target_vs_median_bps.get("roic")
        margin_bps = comparison.target_vs_median_bps.get("operating_margin")
        growth_bps = comparison.target_vs_median_bps.get(
            "revenue_growth_3y_cagr"
        )
        return PeerValuationMultiples(
            target_ticker=comparison.target_ticker,
            peer_median_pe=medians.get("price_to_earnings"),
            peer_median_ev_ebitda=medians.get("ev_to_ebitda"),
            peer_median_ev_sales=medians.get("ev_to_sales"),
            target_current_pe=target.price_to_earnings,
            target_current_ev_ebitda=target.ev_to_ebitda,
            target_current_ev_sales=target.ev_to_sales,
            target_discount_pe_pct=pe_discount,
            target_discount_ev_ebitda_pct=ev_ebitda_discount,
            target_discount_ev_sales_pct=ev_sales_discount,
            target_roic_vs_peer_median_bps=roic_bps,
            target_margin_vs_peer_median_bps=margin_bps,
            target_growth_vs_peer_median_bps=growth_bps,
            roic_positioning=_positioning(roic_bps),  # type: ignore[arg-type]
            valuation_positioning=_valuation_positioning(
                ev_ebitda_discount
            ),  # type: ignore[arg-type]
        )

    # ------------------------------------------------------------------
    def _build_regression(
        self, comparison: PeerComparison
    ) -> PeerValuationRegression | None:
        peers = comparison.peer_fundamentals
        target = comparison.target_fundamentals
        explanatory = ("roic", "revenue_growth_3y_cagr", "operating_margin")
        dependent = "ev_to_ebitda"

        rows = []
        for p in peers:
            dep_val = getattr(p, dependent)
            xs = [getattr(p, f) for f in explanatory]
            if dep_val is None or any(v is None for v in xs):
                continue
            rows.append([float(dep_val)] + [float(v) for v in xs])
        if len(rows) < self.min_peers:
            return None

        arr = np.asarray(rows, dtype=float)
        y = arr[:, 0]
        x = arr[:, 1:]
        x_with_intercept = np.column_stack([np.ones(len(x)), x])
        coefs, residuals, rank, _ = np.linalg.lstsq(
            x_with_intercept, y, rcond=None
        )
        y_pred = x_with_intercept @ coefs
        ss_res = float(np.sum((y - y_pred) ** 2))
        ss_tot = float(np.sum((y - np.mean(y)) ** 2))
        r_squared = 1.0 - ss_res / ss_tot if ss_tot > 0 else 0.0

        # Target prediction
        target_xs = [getattr(target, f) for f in explanatory]
        if any(v is None for v in target_xs) or target.ev_to_ebitda is None:
            predicted = None
            residual_bps = None
            signal = None
            target_predicted_decimal = None
        else:
            target_vector = np.array(
                [1.0] + [float(v) for v in target_xs if v is not None]
            )
            predicted = float(target_vector @ coefs)
            actual = float(target.ev_to_ebitda)
            target_predicted_decimal = Decimal(str(round(predicted, 4)))
            residual_bps = int(round((actual - predicted) * 10000))
            if residual_bps < -200:
                signal = "UNDERVALUED"
            elif residual_bps > 200:
                signal = "OVERVALUED"
            else:
                signal = "FAIRLY_VALUED"

        return PeerValuationRegression(
            target_ticker=comparison.target_ticker,
            dependent_variable=dependent,
            explanatory_variables=list(explanatory),
            intercept=Decimal(str(round(float(coefs[0]), 6))),
            coefficients={
                var: Decimal(str(round(float(c), 6)))
                for var, c in zip(explanatory, coefs[1:])
            },
            r_squared=Decimal(str(round(r_squared, 4))),
            n_peers_used=len(rows),
            target_predicted_multiple=target_predicted_decimal,
            target_actual_multiple=target.ev_to_ebitda,
            residual_bps=residual_bps,
            signal=signal,  # type: ignore[arg-type]
        )


def _summary_bullets(
    comparison: PeerComparison,
    multiples: PeerValuationMultiples | None,
    regression: PeerValuationRegression | None,
) -> list[str]:
    bullets: list[str] = []
    if multiples is not None and multiples.valuation_positioning is not None:
        disc = multiples.target_discount_ev_ebitda_pct
        if disc is not None:
            bullets.append(
                f"EV/EBITDA discount vs peers: {disc:+.1f}% "
                f"→ {multiples.valuation_positioning}"
            )
    if multiples is not None and multiples.roic_positioning is not None:
        roic_bps = multiples.target_roic_vs_peer_median_bps
        if roic_bps is not None:
            bullets.append(
                f"ROIC vs peer median: {roic_bps:+.0f} bps "
                f"→ {multiples.roic_positioning}"
            )
    if regression is not None and regression.signal is not None:
        bullets.append(
            f"Regression residual: {regression.residual_bps:+d} bps "
            f"(R²={regression.r_squared:.2f}, n={regression.n_peers_used}) "
            f"→ {regression.signal}"
        )
    _ = comparison
    return bullets


def build_peer_valuation(
    comparison: PeerComparison, *, min_peers: int = 5
) -> PeerValuation:
    return PeerValuationBuilder(min_peers=min_peers).build(comparison)


__all__ = [
    "PeerValuationBuilder",
    "build_peer_valuation",
]
