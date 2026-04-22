"""Phase 1.5.11 — restatement detection stub.

When a fresh audited extraction lands for a period previously
processed under an unaudited source, the pipeline should flag material
deltas (|%Δ| > 2 %) on headline metrics (revenue, net income, total
assets, equity). The full implementation lives in Phase 2 Sprint 2;
this module ships the data types and a sentinel raising
:class:`NotImplementedError` so callers can wire themselves without
blocking on the real logic.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from portfolio_thesis_engine.schemas.base import BaseSchema


class RestatementDelta(BaseSchema):
    """One metric-level delta between an audited and unaudited source."""

    metric: str
    previous_unaudited: Decimal | None = None
    current_audited: Decimal | None = None
    absolute_delta: Decimal | None = None
    percent_delta: Decimal | None = None
    material: bool = False


class RestatementReport(BaseSchema):
    """Phase 2 Sprint 2 — full implementation. Phase 1.5.11 only
    defines the shape."""

    previous_extraction_id: str
    current_extraction_id: str
    period_label: str
    deltas: list[RestatementDelta] = []
    overall_material: bool = False
    notes: str = ""


def detect_restatement_stub(
    current_extraction: Any,
    previous_unaudited_extraction: Any,
) -> RestatementReport | None:
    """Phase 1.5.11 stub — raises :class:`NotImplementedError`.

    Phase 2 Sprint 2 will compare headline metrics (revenue, NI, total
    assets, equity) between a fresh audited extraction and an earlier
    unaudited one for the same fiscal period, flag deltas over 2 %,
    and return a populated :class:`RestatementReport`. Today we stub
    so pipeline / CLI callers can wire themselves today and pick up
    the real implementation transparently.
    """
    _ = (current_extraction, previous_unaudited_extraction)
    raise NotImplementedError(
        "Restatement detection: Phase 2 Sprint 2 (audited vs unaudited delta)."
    )


__all__ = [
    "RestatementDelta",
    "RestatementReport",
    "detect_restatement_stub",
]
