"""Shared primitives for the extraction engine.

:class:`ExtractionContext` — the mutable state threaded through modules.
Modules append to ``adjustments``, ``decision_log`` and ``estimates_log``
rather than returning new objects; this mirrors the spec's E.4–E.7
sketches and keeps the call-site simple.

:class:`ExtractionModule` — abstract base; every module implements a
single ``apply(context)`` coroutine.

:class:`ExtractionResult` — the batched product of a run: the adjustments
collected and the logs. Sprint 7 extends this with the full
:class:`CanonicalCompanyState`; Sprint 6 keeps it narrow.
"""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from portfolio_thesis_engine.extraction.raw_extraction_adapter import StructuredSection
from portfolio_thesis_engine.schemas.common import FiscalPeriod
from portfolio_thesis_engine.schemas.company import CanonicalCompanyState, ModuleAdjustment
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
    # Unknown — use a sentinel year at the valid floor.
    return FiscalPeriod(year=1990, label=label or "unknown")


# ----------------------------------------------------------------------
# Context
# ----------------------------------------------------------------------
@dataclass
class ExtractionContext:
    """Mutable state shared across extraction modules.

    ``adjustments``, ``decision_log`` and ``estimates_log`` accumulate in
    the order modules run. Modules read ``sections`` (read-only in
    practice) and append to the logs.
    """

    ticker: str
    fiscal_period_label: str
    primary_period: FiscalPeriod
    sections: list[StructuredSection]
    wacc_inputs: WACCInputs
    adjustments: list[ModuleAdjustment] = field(default_factory=list)
    decision_log: list[str] = field(default_factory=list)
    estimates_log: list[str] = field(default_factory=list)

    def find_section(self, section_type: str) -> StructuredSection | None:
        """First section of ``section_type`` or ``None``."""
        for section in self.sections:
            if section.section_type == section_type:
                return section
        return None


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

    Sprint 7 adds :attr:`canonical_state`: the fully-typed, immutable
    :class:`CanonicalCompanyState` built from the reclassified sections,
    the module adjustments, and the derived analysis. It stays optional
    so the coordinator's low-level ``extract`` (no identity supplied) can
    still return a result without it — callers building a canonical
    state use :meth:`ExtractionCoordinator.extract_canonical` instead.
    """

    ticker: str
    fiscal_period_label: str
    primary_period: FiscalPeriod
    adjustments: list[ModuleAdjustment]
    decision_log: list[str]
    estimates_log: list[str]
    modules_run: list[str]
    canonical_state: CanonicalCompanyState | None = None
