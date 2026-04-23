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

from typing import Any

from portfolio_thesis_engine.schemas.company import (
    CanonicalCompanyState,
    NarrativeContext,
)
from portfolio_thesis_engine.schemas.ficha import Ficha, NarrativeSummary
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

        narrative_summary = _condense_narrative(canonical_state.narrative_context)

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
            narrative_summary=narrative_summary,
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


# ----------------------------------------------------------------------
# Phase 1.5.14 — narrative condensation helpers (module-level so unit
# tests can import them directly).
# ----------------------------------------------------------------------
_MAX_KEY_THEMES = 7
_MAX_RISKS = 7
_MAX_GUIDANCE = 5
_MAX_CAPITAL_ALLOC = 5
_MAX_FORWARD = 5


def _condense_narrative(
    context: NarrativeContext | None,
) -> NarrativeSummary | None:
    """Turn a rich :class:`NarrativeContext` into short bullet strings
    with attribution baked in. Returns ``None`` when ``context`` is
    ``None`` so the Ficha field stays optional."""
    if context is None:
        return None
    return NarrativeSummary(
        source_period=context.source_extraction_period,
        source_document_type=context.source_document_type,
        source_extraction_timestamp=context.extraction_timestamp,
        key_themes=_condense_narrative_items(
            context.key_themes, _MAX_KEY_THEMES
        ),
        primary_risks=_condense_risk_items(
            context.risks_mentioned, _MAX_RISKS
        ),
        management_guidance=_condense_guidance_items(
            context.guidance_changes, _MAX_GUIDANCE
        ),
        capital_allocation=_condense_capital_items(
            context.capital_allocation_signals, _MAX_CAPITAL_ALLOC
        ),
        forward_looking_statements=_condense_narrative_items(
            context.forward_looking_statements, _MAX_FORWARD
        ),
    )


def _with_attribution(body: str, source: Any, page: Any = None) -> str:
    """Append ``[source: ..., p. N]`` when either is present."""
    bits: list[str] = []
    if source:
        bits.append(str(source))
    if page is not None and page != "":
        bits.append(f"p. {page}")
    if not bits:
        return body
    return f"{body} [source: {', '.join(bits)}]"


def _condense_narrative_items(items: list[Any], cap: int) -> list[str]:
    out: list[str] = []
    for item in items[:cap]:
        text = getattr(item, "text", None) or ""
        tag = getattr(item, "tag", None)
        body = f"[{tag}] {text}" if tag else text
        out.append(
            _with_attribution(
                body,
                getattr(item, "source", None),
                getattr(item, "page", None),
            )
        )
    return out


def _condense_risk_items(items: list[Any], cap: int) -> list[str]:
    out: list[str] = []
    for item in items[:cap]:
        risk = getattr(item, "risk", None) or ""
        detail = getattr(item, "detail", None)
        body = f"{risk} — {detail}" if detail else risk
        out.append(
            _with_attribution(
                body,
                getattr(item, "source", None),
                getattr(item, "page", None),
            )
        )
    return out


def _condense_guidance_items(items: list[Any], cap: int) -> list[str]:
    out: list[str] = []
    for item in items[:cap]:
        metric = getattr(item, "metric", None) or "unspecified"
        statement = getattr(item, "statement", None)
        value = getattr(item, "value", None)
        direction = getattr(item, "direction", None)
        period = getattr(item, "period", None)
        parts = [metric]
        if direction:
            parts.append(f"({direction})")
        if value:
            parts.append(f"value {value}")
        if statement:
            parts.append(f"— {statement}")
        if period:
            parts.append(f"[period: {period}]")
        out.append(
            _with_attribution(" ".join(parts), getattr(item, "source", None))
        )
    return out


def _condense_capital_items(items: list[Any], cap: int) -> list[str]:
    out: list[str] = []
    for item in items[:cap]:
        area = getattr(item, "area", None) or "General"
        detail = getattr(item, "detail", None)
        amount = getattr(item, "amount", None)
        period = getattr(item, "period", None)
        parts = [f"[{area}]"]
        if amount:
            parts.append(str(amount))
        if detail:
            parts.append(f"— {detail}")
        if period:
            parts.append(f"({period})")
        out.append(
            _with_attribution(" ".join(parts), getattr(item, "source", None))
        )
    return out
