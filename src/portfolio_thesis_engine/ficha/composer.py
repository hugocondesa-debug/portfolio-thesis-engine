"""FichaComposer — builds a :class:`Ficha` from the canonical state +
valuation snapshot.

The :class:`Ficha` schema lives in :mod:`schemas.ficha` and is the
aggregate view shown by :command:`pte show` and the Streamlit UI.
Phase 1 populates:

- identity, current_extraction_id, current_valuation_snapshot_id
- conviction (from the valuation snapshot)
- market_contexts (from CompanyIdentity)
- snapshot_age_days, is_stale (derived from valuation_snapshot.valuation_date)

Left at schema defaults (wired in later phases):

- thesis — human-edited ThesisStatement (Phase 2)
- position — from :class:`PositionRepository` (Phase 2)
- monitorables — from tracked KPIs (Phase 2)
- tags, next_earnings_expected — Phase 2+

The composer is deliberately stateless; callers inject the
``company_repo`` only when they want the ficha persisted in the same
call (the pipeline does this).
"""

from __future__ import annotations

from datetime import UTC, datetime

from portfolio_thesis_engine.schemas.company import CanonicalCompanyState
from portfolio_thesis_engine.schemas.ficha import Ficha
from portfolio_thesis_engine.schemas.valuation import ValuationSnapshot
from portfolio_thesis_engine.storage.yaml_repo import CompanyRepository

_DEFAULT_STALE_THRESHOLD_DAYS = 90


class FichaComposer:
    """Compose the aggregate :class:`Ficha` view."""

    def __init__(self, stale_threshold_days: int = _DEFAULT_STALE_THRESHOLD_DAYS) -> None:
        if stale_threshold_days < 1:
            raise ValueError("stale_threshold_days must be >= 1")
        self.stale_threshold_days = stale_threshold_days

    # ------------------------------------------------------------------
    def compose(
        self,
        canonical_state: CanonicalCompanyState,
        valuation_snapshot: ValuationSnapshot | None = None,
        *,
        as_of: datetime | None = None,
    ) -> Ficha:
        """Return a :class:`Ficha` combining ``canonical_state`` and
        (optionally) ``valuation_snapshot``.

        ``as_of`` (default ``now(UTC)``) is the reference point for
        staleness computation; exposed so tests can pin a deterministic
        "now".
        """
        now = as_of or datetime.now(UTC)

        snapshot_age_days: int | None = None
        is_stale = False
        conviction = None
        valuation_snapshot_id: str | None = None

        if valuation_snapshot is not None:
            # valuation_date may be naive or tz-aware; normalise both
            # sides to UTC so the subtraction never raises.
            vd = valuation_snapshot.valuation_date
            if vd.tzinfo is None:
                vd = vd.replace(tzinfo=UTC)
            snapshot_age_days = max((now - vd).days, 0)
            is_stale = snapshot_age_days > self.stale_threshold_days
            conviction = valuation_snapshot.conviction
            valuation_snapshot_id = valuation_snapshot.snapshot_id

        return Ficha(
            version=1,
            created_at=now,
            created_by="phase1-sprint10",
            ticker=canonical_state.identity.ticker,
            identity=canonical_state.identity,
            thesis=None,
            current_extraction_id=canonical_state.extraction_id,
            current_valuation_snapshot_id=valuation_snapshot_id,
            position=None,
            conviction=conviction,
            monitorables=[],
            tags=[],
            market_contexts=list(canonical_state.identity.market_contexts),
            snapshot_age_days=snapshot_age_days,
            is_stale=is_stale,
            next_earnings_expected=None,
        )

    # ------------------------------------------------------------------
    def compose_and_save(
        self,
        canonical_state: CanonicalCompanyState,
        valuation_snapshot: ValuationSnapshot | None,
        company_repo: CompanyRepository,
        *,
        as_of: datetime | None = None,
    ) -> Ficha:
        """Convenience: compose + persist via :class:`CompanyRepository`.

        Ficha is not versioned on disk (it's a single YAML under
        ``companies/{ticker}/ficha.yaml``), so this is a straight save.
        """
        ficha = self.compose(canonical_state, valuation_snapshot, as_of=as_of)
        company_repo.save(ficha)
        return ficha
