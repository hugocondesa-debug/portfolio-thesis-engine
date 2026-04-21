"""Peer — comparable company for benchmarking."""

from datetime import datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import Field

from portfolio_thesis_engine.schemas.base import BaseSchema
from portfolio_thesis_engine.schemas.common import Currency, Profile


class PeerExtractionLevel(StrEnum):
    """How much extraction was performed on this peer."""

    LEVEL_A = "A"
    LEVEL_B = "B"
    LEVEL_C = "C"


class PeerStatus(StrEnum):
    ACTIVE = "active"
    PROMOTED = "promoted"
    DROPPED = "dropped"


class Peer(BaseSchema):
    """A peer comparable to a target company."""

    ticker: str
    name: str
    profile: Profile
    currency: Currency
    exchange: str

    peer_of_ticker: str

    extraction_level: PeerExtractionLevel
    last_update: datetime
    status: PeerStatus = PeerStatus.ACTIVE

    market_data: dict[str, Decimal] = Field(default_factory=dict)
    reported_metrics: dict[str, Decimal] = Field(default_factory=dict)

    adjusted_metrics: dict[str, Decimal] | None = None

    archetype_specific: dict[str, Decimal] = Field(default_factory=dict)

    promotion_date: datetime | None = None
    promoted_to: str | None = None
