"""Abstract extractor + shared dataclasses for the three-pass pipeline."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from portfolio_thesis_engine.ingestion.base import IngestedDocument
from portfolio_thesis_engine.schemas.common import GuardrailStatus


# ----------------------------------------------------------------------
# Intermediate (Pass 1) — boundaries only, no content yet
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class IdentifiedSection:
    """A section located inside a document but not yet parsed.

    Pass 1 produces one of these per section; Pass 2 turns each into a
    :class:`StructuredSection`.
    """

    section_type: str
    title: str
    start_char: int
    end_char: int  # exclusive
    fiscal_period: str | None = None
    confidence: float = 1.0


# ----------------------------------------------------------------------
# Final (Pass 2) — content + structured parsed data
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class StructuredSection:
    """A recognized and extracted section of a financial report.

    ``content`` is the raw markdown slice; ``parsed_data`` is the output
    of the per-section tool-use call (``None`` when the section is of a
    type we don't parse yet, or when Pass 2 hasn't run).
    """

    section_type: str
    title: str
    content: str
    parsed_data: dict[str, Any] | None = None
    page_range: tuple[int, int] | None = None
    fiscal_period: str | None = None
    confidence: float = 1.0
    extraction_method: str = "llm_section_detection"


# ----------------------------------------------------------------------
# Validator (Pass 3) output — one dataclass per check
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class ValidationIssue:
    """A single validator finding.

    ``severity`` maps directly to :class:`GuardrailStatus` when the
    coordinator rolls issues up into an overall status. ``section_type``
    is ``None`` for cross-section checks (e.g. "fiscal periods don't
    agree").
    """

    severity: str  # "FATAL" | "WARN" | "INFO"
    message: str
    section_type: str | None = None
    details: dict[str, Any] | None = None


# ----------------------------------------------------------------------
# ExtractionResult — the complete product of all passes
# ----------------------------------------------------------------------
@dataclass
class ExtractionResult:
    """Output of :meth:`SectionExtractor.extract`."""

    doc_id: str
    ticker: str
    fiscal_period: str
    sections: list[StructuredSection]
    unresolved: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    issues: list[ValidationIssue] = field(default_factory=list)
    overall_status: GuardrailStatus = GuardrailStatus.PASS


# ----------------------------------------------------------------------
# Extractor ABC
# ----------------------------------------------------------------------
class SectionExtractor(ABC):
    """Per-archetype base."""

    profile_name: str = ""

    @abstractmethod
    async def extract(self, document: IngestedDocument) -> ExtractionResult:
        """Run Pass 1 → Pass 2 → Pass 3 and return the final result."""
