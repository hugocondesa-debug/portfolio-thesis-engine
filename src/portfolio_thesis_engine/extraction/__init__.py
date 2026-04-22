"""Extraction engine — applies the reclassification methodology to a
:class:`RawExtraction` loaded by the pipeline.

Phase 1 ships Module A (taxes, subset A.1–A.5), Module B (provisions
minimal, B.0–B.2) and Module C (leases, subset C.0–C.3). The
coordinator orders modules, propagates a shared
:class:`ExtractionContext` between them, and enforces the per-company
cost cap between stages.

Public surface is intentionally minimal so downstream callers depend
on a stable façade, not on individual module internals.
"""

from portfolio_thesis_engine.extraction.analysis import AnalysisDeriver
from portfolio_thesis_engine.extraction.base import (
    ExtractionContext,
    ExtractionModule,
    ExtractionResult,
)
from portfolio_thesis_engine.extraction.coordinator import ExtractionCoordinator
from portfolio_thesis_engine.extraction.module_a_taxes import ModuleATaxes
from portfolio_thesis_engine.extraction.module_b_provisions import ModuleBProvisions
from portfolio_thesis_engine.extraction.module_c_leases import ModuleCLeases

__all__ = [
    "AnalysisDeriver",
    "ExtractionContext",
    "ExtractionModule",
    "ExtractionResult",
    "ExtractionCoordinator",
    "ModuleATaxes",
    "ModuleBProvisions",
    "ModuleCLeases",
]
