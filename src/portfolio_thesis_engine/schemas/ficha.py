"""Ficha — aggregate view of a company across all modules.

Composed on-demand from :class:`CanonicalCompanyState`, :class:`ValuationSnapshot`,
:class:`Position`, and peer data. This schema defines the canonical shape; the
ficha is not persisted as a single file.
"""

from datetime import datetime

from pydantic import Field

from portfolio_thesis_engine.schemas.base import BaseSchema, VersionedMixin
from portfolio_thesis_engine.schemas.company import CompanyIdentity
from portfolio_thesis_engine.schemas.position import Position
from portfolio_thesis_engine.schemas.valuation import Conviction


class NarrativeSummary(BaseSchema):
    """Phase 1.5.14 — condensed narrative snapshot on the Ficha.

    Built by the :class:`FichaComposer` from
    :attr:`CanonicalCompanyState.narrative_context`. Each bucket holds
    short bullet strings with optional ``[source: ...]`` attribution
    baked in. Designed for human scanning + upload to Claude.ai Project
    for scenario-adjustment workflows where rich business context
    materially changes how an analyst picks Bear / Base / Bull drivers.
    """

    source_period: str
    source_document_type: str
    source_extraction_timestamp: datetime

    key_themes: list[str] = Field(default_factory=list)
    primary_risks: list[str] = Field(default_factory=list)
    management_guidance: list[str] = Field(default_factory=list)
    capital_allocation: list[str] = Field(default_factory=list)
    forward_looking_statements: list[str] = Field(default_factory=list)


class ThesisStatement(BaseSchema):
    """Investment thesis in one paragraph."""

    version: int = Field(default=1)
    text: str
    written_at: datetime
    last_reviewed: datetime | None = None


class Monitorable(BaseSchema):
    """A metric being tracked over time."""

    metric: str
    on_track_condition: str
    warning_condition: str
    last_observed: str | None = None
    last_observed_date: str | None = None
    status: str
    source: str | None = None


class Ficha(BaseSchema, VersionedMixin):
    """Aggregate view of a company.

    The composed output displayed by the portfolio system.
    """

    ticker: str
    identity: CompanyIdentity

    thesis: ThesisStatement | None = None

    current_extraction_id: str | None = None
    current_valuation_snapshot_id: str | None = None
    position: Position | None = None

    conviction: Conviction | None = None
    monitorables: list[Monitorable] = Field(default_factory=list)

    tags: list[str] = Field(default_factory=list)
    market_contexts: list[str] = Field(default_factory=list)

    snapshot_age_days: int | None = None
    is_stale: bool = False
    next_earnings_expected: str | None = None

    # Phase 1.5.14 — qualitative payload condensed from the source
    # extraction. Optional: legacy fichas without narrative leave it
    # ``None``, as do runs whose source extraction carried no narrative.
    narrative_summary: NarrativeSummary | None = None
