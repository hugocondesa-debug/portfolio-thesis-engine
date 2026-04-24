"""Generic scenario buckets — Sprint 4A-alpha.8 schema v1.1 addition.

Allows :class:`leading_indicators` (and any future analyst YAML) to
reference scenarios **generically** (``scenario_relevance: [BULL]``)
instead of by specific name (``[bull_operational, bull_re_rating]``).
Prevents manual sync when new scenarios are added or renamed.
"""

from __future__ import annotations

from enum import StrEnum


class ScenarioBucket(StrEnum):
    """Four canonical scenario categories.

    ``BULL``:  upside (operational, re-rating, M&A acceleration).
    ``BEAR``:  downside (structural compression, cyclical delays).
    ``BASE``:  central estimate (management guidance or analyst mid-case).
    ``TAIL``:  low-probability events (takeover floor, fire-sale, black swan).

    StrEnum — values serialise directly as plain strings in YAML.
    """

    BASE = "BASE"
    BULL = "BULL"
    BEAR = "BEAR"
    TAIL = "TAIL"


def infer_bucket_from_name(name: str) -> ScenarioBucket:
    """Infer the canonical bucket from a scenario's ``name`` field.

    Rules (order matters):

    - ``base*``                                   → BASE
    - ``bull*``                                   → BULL
    - ``bear*``                                   → BEAR
    - ``takeover_*`` / ``tail_*`` / ``fire_sale`` → TAIL
    - ``m_and_a_accelerated``                     → BULL  (M&A deployment bullish)
    - anything else                               → BULL  (safe optimistic default)

    The default-BULL fallback is intentional: analyst intent for custom
    scenarios is usually upside-seeking; the :mod:`validation` helpers
    emit soft warnings so the analyst can audit rather than silently
    miscategorise. Case-insensitive.
    """
    lowered = name.lower()
    if lowered.startswith("base"):
        return ScenarioBucket.BASE
    if lowered.startswith("bull"):
        return ScenarioBucket.BULL
    if lowered.startswith("bear"):
        return ScenarioBucket.BEAR
    if (
        lowered.startswith("takeover_")
        or lowered.startswith("tail_")
        or lowered == "fire_sale"
    ):
        return ScenarioBucket.TAIL
    if lowered == "m_and_a_accelerated":
        return ScenarioBucket.BULL
    return ScenarioBucket.BULL


__all__ = ["ScenarioBucket", "infer_bucket_from_name"]
