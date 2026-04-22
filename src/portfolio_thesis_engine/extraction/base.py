"""Shared primitives for the extraction engine.

:class:`ExtractionContext` — the mutable state threaded through modules.
Modules append to ``adjustments``, ``decision_log`` and ``estimates_log``
rather than returning new objects; this mirrors the spec's E.4–E.7
sketches and keeps the call-site simple.

Phase 1.5 / Sprint 3: the context holds a typed
:class:`RawExtraction` — the human-produced YAML loaded by the
pipeline — and modules read it directly (no more adapter shim).

:class:`ExtractionModule` — abstract base; every module implements a
single ``apply(context)`` coroutine.

:class:`ExtractionResult` — the batched product of a run: adjustments
collected, logs, and (when built by
:meth:`ExtractionCoordinator.extract_canonical`) the fully-typed
:class:`CanonicalCompanyState`.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from portfolio_thesis_engine.schemas.common import FiscalPeriod
from portfolio_thesis_engine.schemas.company import CanonicalCompanyState, ModuleAdjustment
from portfolio_thesis_engine.schemas.raw_extraction import RawExtraction
from portfolio_thesis_engine.schemas.wacc import WACCInputs

# ----------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------
_FY_RE = re.compile(r"FY(?P<year>\d{4})")
_QY_RE = re.compile(r"Q(?P<q>[1-4])\s*(?P<year>\d{4})")


def parse_fiscal_period(label: str) -> FiscalPeriod:
    """Parse a label like ``FY2024`` or ``Q3 2024`` into a
    :class:`FiscalPeriod`.

    Falls back to ``year=1990`` with the raw label when the pattern is
    unrecognised — callers treat that as an unknown period but a valid
    object so downstream ``ModuleAdjustment.affected_periods`` construction
    never raises.
    """
    m = _QY_RE.search(label)
    if m:
        return FiscalPeriod(
            year=int(m.group("year")),
            quarter=int(m.group("q")),
            label=label,
        )
    m = _FY_RE.search(label)
    if m:
        return FiscalPeriod(year=int(m.group("year")), label=label)
    return FiscalPeriod(year=1990, label=label or "unknown")


# ----------------------------------------------------------------------
# Context
# ----------------------------------------------------------------------
@dataclass
class ExtractionContext:
    """Mutable state shared across extraction modules.

    ``adjustments``, ``decision_log`` and ``estimates_log`` accumulate in
    the order modules run. Modules read ``raw_extraction`` (treated as
    read-only) and append to the logs.
    """

    ticker: str
    fiscal_period_label: str
    primary_period: FiscalPeriod
    raw_extraction: RawExtraction
    wacc_inputs: WACCInputs
    adjustments: list[ModuleAdjustment] = field(default_factory=list)
    decision_log: list[str] = field(default_factory=list)
    estimates_log: list[str] = field(default_factory=list)


# ----------------------------------------------------------------------
# Module ABC
# ----------------------------------------------------------------------
class ExtractionModule(ABC):
    """Base class for reclassification modules (A, B, C, ...)."""

    module_id: str = ""

    @abstractmethod
    async def apply(self, context: ExtractionContext) -> ExtractionContext:
        """Mutate ``context`` in place and return it."""


# ----------------------------------------------------------------------
# Result
# ----------------------------------------------------------------------
@dataclass
class ExtractionResult:
    """Output of :meth:`ExtractionCoordinator.extract`.

    ``canonical_state`` is populated only by
    :meth:`ExtractionCoordinator.extract_canonical` (which requires a
    :class:`CompanyIdentity`); the low-level ``extract`` path leaves it
    ``None``.
    """

    ticker: str
    fiscal_period_label: str
    primary_period: FiscalPeriod
    adjustments: list[ModuleAdjustment]
    decision_log: list[str]
    estimates_log: list[str]
    modules_run: list[str]
    canonical_state: CanonicalCompanyState | None = None
