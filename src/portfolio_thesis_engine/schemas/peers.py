"""Phase 2 Sprint 3 — peer set + peer-relative valuation schemas.

Independent from the Phase-1 ``peer.py`` schema (which models
individually-extracted peers for archetype work). Sprint 3 introduces a
lightweight peer declaration (ticker + metadata) plus fundamentals
snapshots fetched from external providers, aggregated into a
:class:`PeerComparison` the analytical layer renders.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from portfolio_thesis_engine.schemas.base import BaseSchema


_PeerSource = Literal["FMP_AUTO", "USER_OVERRIDE", "BOTH"]
_DiscoveryMethod = Literal["FMP_AUTO", "USER_MANUAL", "HYBRID"]
_ValuationSignal = Literal["UNDERVALUED", "FAIRLY_VALUED", "OVERVALUED"]
_Positioning = Literal["ABOVE_PEER", "IN_LINE", "BELOW_PEER"]
_ValuationPositioning = Literal["PREMIUM", "IN_LINE", "DISCOUNT"]


class PeerCompany(BaseSchema):
    """One peer declaration. Can be user-authored (written to the
    peers.yaml manually) or FMP-discovered."""

    ticker: str
    name: str
    country: str | None = None
    listing_currency: str | None = None
    market_cap_usd: Decimal | None = None
    industry: str | None = None
    source: _PeerSource = "FMP_AUTO"
    included: bool = True
    rationale: str | None = None


class PeerSet(BaseSchema):
    """Peer declaration for a target ticker, round-tripped via YAML."""

    target_ticker: str
    peers: list[PeerCompany] = Field(default_factory=list)
    discovery_method: _DiscoveryMethod = "HYBRID"
    fmp_sector: str | None = None
    fmp_industry: str | None = None
    min_peers_regression: int = 5
    max_peers_display: int = 20
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_fmp_sync: datetime | None = None


class PeerFundamentals(BaseSchema):
    """Single-period snapshot of a peer's key ratios + market data."""

    ticker: str
    period: str
    currency: str

    # Valuation multiples
    price_to_earnings: Decimal | None = None
    ev_to_ebitda: Decimal | None = None
    ev_to_sales: Decimal | None = None
    price_to_book: Decimal | None = None

    # Fundamentals
    revenue_growth_3y_cagr: Decimal | None = None
    operating_margin: Decimal | None = None
    roic: Decimal | None = None
    net_margin: Decimal | None = None
    financial_leverage: Decimal | None = None

    # Market data
    market_cap_local: Decimal | None = None
    market_cap_usd: Decimal | None = None

    fetched_at: datetime
    source: str = "MANUAL"  # "FMP" | "EODHD" | "MANUAL"


class PeerComparison(BaseSchema):
    """Target + peers snapshot with median / mean / percentile
    aggregates and target positioning per metric."""

    target_ticker: str
    target_fundamentals: PeerFundamentals
    peer_fundamentals: list[PeerFundamentals] = Field(default_factory=list)

    peer_median: dict[str, Decimal] = Field(default_factory=dict)
    peer_mean: dict[str, Decimal] = Field(default_factory=dict)
    peer_percentile_25: dict[str, Decimal] = Field(default_factory=dict)
    peer_percentile_75: dict[str, Decimal] = Field(default_factory=dict)

    target_percentile: dict[str, int] = Field(default_factory=dict)
    target_vs_median_pct: dict[str, Decimal] = Field(default_factory=dict)
    target_vs_median_bps: dict[str, Decimal] = Field(default_factory=dict)


class PeerValuationMultiples(BaseSchema):
    """Median-multiple valuation: implied value per multiple, target
    discount/premium vs peer median, plus ROIC/margin/growth context."""

    target_ticker: str

    peer_median_pe: Decimal | None = None
    peer_median_ev_ebitda: Decimal | None = None
    peer_median_ev_sales: Decimal | None = None

    target_current_pe: Decimal | None = None
    target_current_ev_ebitda: Decimal | None = None
    target_current_ev_sales: Decimal | None = None

    target_discount_pe_pct: Decimal | None = None
    target_discount_ev_ebitda_pct: Decimal | None = None
    target_discount_ev_sales_pct: Decimal | None = None

    target_roic_vs_peer_median_bps: Decimal | None = None
    target_margin_vs_peer_median_bps: Decimal | None = None
    target_growth_vs_peer_median_bps: Decimal | None = None

    roic_positioning: _Positioning | None = None
    valuation_positioning: _ValuationPositioning | None = None


class PeerValuationRegression(BaseSchema):
    """Simple linear regression across peer fundamentals → multiple.
    Emits ``None`` when fewer than :attr:`n_peers_minimum` peers carry
    complete data."""

    target_ticker: str
    dependent_variable: str = "ev_to_ebitda"
    explanatory_variables: list[str] = Field(default_factory=list)

    intercept: Decimal
    coefficients: dict[str, Decimal] = Field(default_factory=dict)
    r_squared: Decimal
    n_peers_used: int

    target_predicted_multiple: Decimal | None = None
    target_actual_multiple: Decimal | None = None
    residual_bps: int | None = None
    signal: _ValuationSignal | None = None


class PeerValuation(BaseSchema):
    """Top-level peer valuation bundle — multiples, optional
    regression, and summary bullets for CLI rendering."""

    target_ticker: str
    multiples: PeerValuationMultiples | None = None
    regression: PeerValuationRegression | None = None
    summary_bullets: list[str] = Field(default_factory=list)


__all__ = [
    "PeerCompany",
    "PeerSet",
    "PeerFundamentals",
    "PeerComparison",
    "PeerValuationMultiples",
    "PeerValuationRegression",
    "PeerValuation",
]
