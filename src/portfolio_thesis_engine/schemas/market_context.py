"""Market context — cluster-level data shared across companies."""

from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import Field

from portfolio_thesis_engine.schemas.base import AuditableMixin, BaseSchema


class MarketParticipant(BaseSchema):
    """A participant in a market cluster."""

    ticker: str
    name: str
    market_share_pct: Decimal | None = None
    position: str | None = None


class MarketDimension(BaseSchema):
    """A dimension of the market (geography, segment, etc.)."""

    name: str
    description: str | None = None
    total_market_value: Decimal | None = None
    unit: str | None = None
    year: int | None = None
    cagr: Decimal | None = None
    source: str | None = None
    participants: list[MarketParticipant] = Field(default_factory=list)


class MarketCatalyst(BaseSchema):
    """A catalyst / trigger affecting the market."""

    date_approx: str
    event: str
    impact_direction: str
    affected_companies: list[str] = Field(default_factory=list)
    probability: Decimal | None = None
    description: str | None = None


class MarketContext(BaseSchema, AuditableMixin):
    """Cluster-level market context.

    MVP is minimal: identity + reference + extension point. Rich content added
    incrementally over time via :attr:`extensions`.
    """

    cluster_id: str
    name: str
    description: str

    companies: list[str] = Field(default_factory=list)

    dimensions: list[MarketDimension] = Field(default_factory=list)
    catalysts: list[MarketCatalyst] = Field(default_factory=list)
    regulatory_notes: list[str] = Field(default_factory=list)
    dynamics_notes: list[str] = Field(default_factory=list)

    extensions: dict[str, Any] = Field(default_factory=dict)

    last_updated: datetime
    sources: list[str] = Field(default_factory=list)
