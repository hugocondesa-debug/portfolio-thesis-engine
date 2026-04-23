"""Phase 2 Sprint 3 — :class:`PeerMetricsFetcher`.

Takes a :class:`PeerSet` and materialises a :class:`PeerComparison`
with target + peer fundamentals and aggregate statistics. The external
provider is injected as :class:`PeerFundamentalsProvider` so tests can
use deterministic stub data (production uses FMP).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

from portfolio_thesis_engine.schemas.peers import (
    PeerComparison,
    PeerFundamentals,
    PeerSet,
)


class PeerFundamentalsProvider(Protocol):
    """Pluggable provider for market-multiple + ratio data."""

    def fetch_fundamentals(self, ticker: str) -> PeerFundamentals | None:
        """Return fundamentals snapshot or ``None`` when unavailable."""


class _NoopFundamentalsProvider:
    def fetch_fundamentals(self, ticker: str) -> PeerFundamentals | None:
        _ = ticker
        return None


_RATIO_FIELDS = (
    "price_to_earnings",
    "ev_to_ebitda",
    "ev_to_sales",
    "price_to_book",
    "revenue_growth_3y_cagr",
    "operating_margin",
    "roic",
    "net_margin",
    "financial_leverage",
)


class PeerMetricsFetcher:
    def __init__(
        self,
        provider: PeerFundamentalsProvider | None = None,
        *,
        target_fundamentals_provider: PeerFundamentalsProvider | None = None,
    ) -> None:
        self.provider: PeerFundamentalsProvider = (
            provider or _NoopFundamentalsProvider()
        )
        # Allow a different provider for the target (useful when target
        # fundamentals come from the canonical state rather than FMP).
        self.target_provider: PeerFundamentalsProvider = (
            target_fundamentals_provider or self.provider
        )

    def fetch(self, peer_set: PeerSet) -> PeerComparison | None:
        target = self.target_provider.fetch_fundamentals(
            peer_set.target_ticker
        )
        if target is None:
            return None
        peer_funds = [
            f
            for p in peer_set.peers
            if p.included
            for f in [self.provider.fetch_fundamentals(p.ticker)]
            if f is not None
        ]
        return _assemble_comparison(target, peer_funds)

    def fetch_from_target(
        self, peer_set: PeerSet, target_override: PeerFundamentals
    ) -> PeerComparison:
        """Alternate entry when the analytical layer already has
        target fundamentals derived from the canonical state."""
        peer_funds = [
            f
            for p in peer_set.peers
            if p.included
            for f in [self.provider.fetch_fundamentals(p.ticker)]
            if f is not None
        ]
        return _assemble_comparison(target_override, peer_funds)


def _assemble_comparison(
    target: PeerFundamentals, peer_funds: list[PeerFundamentals]
) -> PeerComparison:
    medians: dict[str, Decimal] = {}
    means: dict[str, Decimal] = {}
    p25: dict[str, Decimal] = {}
    p75: dict[str, Decimal] = {}
    target_percentile: dict[str, int] = {}
    target_vs_median_pct: dict[str, Decimal] = {}
    target_vs_median_bps: dict[str, Decimal] = {}

    for field in _RATIO_FIELDS:
        values = sorted(
            v
            for v in (getattr(p, field) for p in peer_funds)
            if v is not None
        )
        if not values:
            continue
        medians[field] = _median(values)
        means[field] = sum(values, Decimal("0")) / len(values)
        p25[field] = _quantile(values, Decimal("0.25"))
        p75[field] = _quantile(values, Decimal("0.75"))
        target_val = getattr(target, field)
        if target_val is not None and medians[field] != 0:
            delta = (target_val - medians[field]) / abs(medians[field])
            target_vs_median_pct[field] = delta * Decimal("100")
            target_vs_median_bps[field] = delta * Decimal("10000")
            target_percentile[field] = _percentile_rank(values, target_val)

    return PeerComparison(
        target_ticker=target.ticker,
        target_fundamentals=target,
        peer_fundamentals=peer_funds,
        peer_median=medians,
        peer_mean=means,
        peer_percentile_25=p25,
        peer_percentile_75=p75,
        target_percentile=target_percentile,
        target_vs_median_pct=target_vs_median_pct,
        target_vs_median_bps=target_vs_median_bps,
    )


def _median(values: list[Decimal]) -> Decimal:
    n = len(values)
    if n % 2 == 1:
        return values[n // 2]
    return (values[n // 2 - 1] + values[n // 2]) / Decimal("2")


def _quantile(values: list[Decimal], q: Decimal) -> Decimal:
    if not values:
        return Decimal("0")
    n = len(values)
    idx = (Decimal(str(n - 1)) * q)
    lower = int(idx)
    fraction = idx - Decimal(lower)
    if lower + 1 >= n:
        return values[lower]
    return values[lower] + fraction * (values[lower + 1] - values[lower])


def _percentile_rank(sorted_values: list[Decimal], target: Decimal) -> int:
    """Return the integer percentile (0-100) of ``target`` within
    ``sorted_values``."""
    if not sorted_values:
        return 0
    below = sum(1 for v in sorted_values if v < target)
    return int(round(below / len(sorted_values) * 100))


# Convenience export for tests that want a quick target fundamentals
# provider that returns a fixed snapshot.
def make_static_provider(
    snapshots: dict[str, PeerFundamentals],
) -> PeerFundamentalsProvider:
    class _Static:
        def fetch_fundamentals(self, ticker: str) -> PeerFundamentals | None:
            return snapshots.get(ticker)

    return _Static()


__all__ = [
    "PeerFundamentalsProvider",
    "PeerMetricsFetcher",
    "make_static_provider",
]
