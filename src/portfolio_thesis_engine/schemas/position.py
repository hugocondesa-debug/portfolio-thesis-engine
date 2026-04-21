"""Position — a portfolio holding of a company."""

from decimal import Decimal
from enum import StrEnum

from pydantic import Field

from portfolio_thesis_engine.schemas.base import AuditableMixin, BaseSchema
from portfolio_thesis_engine.schemas.common import Currency, Money, Percentage


class PositionStatus(StrEnum):
    ACTIVE = "active"
    EXITED = "exited"
    WATCHLIST = "watchlist"
    RESEARCH = "research"


class PositionTransaction(BaseSchema):
    """Single transaction in a position's history."""

    date: str
    type: str
    quantity: Decimal
    price: Money
    currency: Currency
    rationale: str
    fees: Money | None = None


class PositionCurrentState(BaseSchema):
    """Auto-computed current state of a position."""

    quantity: Decimal
    avg_cost: Money
    last_price: Money
    last_price_date: str
    market_value: Money
    unrealized_pnl: Money
    unrealized_pnl_pct: Percentage
    weight_pct: Percentage


class PositionLinkage(BaseSchema):
    """Links to related entities."""

    valuation_snapshot_current: str | None = None
    ficha_path: str | None = None
    company_state_id: str | None = None


class Position(BaseSchema, AuditableMixin):
    """Portfolio position in a company."""

    ticker: str
    company_name: str
    status: PositionStatus
    currency: Currency

    transactions: list[PositionTransaction] = Field(default_factory=list)

    current: PositionCurrentState | None = None

    exit_date: str | None = None
    exit_price: Money | None = None
    realized_pnl: Money | None = None
    realized_pnl_pct: Percentage | None = None

    linkage: PositionLinkage = Field(default_factory=PositionLinkage)

    tags: list[str] = Field(default_factory=list)
    notes: str | None = None
