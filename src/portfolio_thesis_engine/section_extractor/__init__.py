"""Section extractor — turns raw markdown reports into structured sections.

Three passes:

1. Pass 1 (TOC identification) — one LLM call locates section boundaries.
2. Pass 2 (per-section parsing) — one LLM call per section, parallelised,
   returning structured data via tool use.
3. Pass 3 (validation) — Python-side checksums and consistency checks.

Phase 1 ships P1 Industrial archetype; other archetypes are Phase 2.
"""

from portfolio_thesis_engine.section_extractor.base import (
    ExtractionResult,
    IdentifiedSection,
    SectionExtractor,
    StructuredSection,
)
from portfolio_thesis_engine.section_extractor.p1_extractor import P1IndustrialExtractor

__all__ = [
    "ExtractionResult",
    "IdentifiedSection",
    "P1IndustrialExtractor",
    "SectionExtractor",
    "StructuredSection",
]
