"""Ingestion — first entry point to the engine.

Phase 1 exposes :class:`BulkMarkdownMode` (primary) and a stub for
:class:`PreExtractedMode` (Phase 2). :class:`IngestionCoordinator`
despatches by mode and registers the ticker in the metadata store.
:func:`ingestion.wacc_parser.parse_wacc_inputs` turns a YAML-frontmatter
markdown into a validated :class:`WACCInputs`.
"""

from portfolio_thesis_engine.ingestion.base import (
    IngestedDocument,
    IngestionError,
    IngestionMode,
    IngestionResult,
)
from portfolio_thesis_engine.ingestion.bulk_markdown import BulkMarkdownMode
from portfolio_thesis_engine.ingestion.coordinator import IngestionCoordinator
from portfolio_thesis_engine.ingestion.pre_extracted import PreExtractedMode
from portfolio_thesis_engine.ingestion.wacc_parser import parse_wacc_inputs

__all__ = [
    "BulkMarkdownMode",
    "IngestedDocument",
    "IngestionCoordinator",
    "IngestionError",
    "IngestionMode",
    "IngestionResult",
    "PreExtractedMode",
    "parse_wacc_inputs",
]
