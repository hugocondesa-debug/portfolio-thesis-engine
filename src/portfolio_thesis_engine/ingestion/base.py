"""Abstract ingestion mode + shared dataclasses."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from portfolio_thesis_engine.shared.exceptions import PTEError


class IngestionError(PTEError):
    """Raised on fatal ingestion validation failures."""


@dataclass(frozen=True)
class IngestedDocument:
    """A single document registered in the storage layer.

    ``source_path`` points at the blob location inside
    :class:`DocumentRepository` after ingestion — not at the caller's
    original file. Use ``content_hash`` for idempotence checks
    (identical hash implies identical payload).
    """

    doc_id: str  # e.g. "1846-HK/annual_report/2024-12-31_annual_report.md"
    ticker: str  # normalised
    doc_type: str  # "annual_report" | "interim_report" | "wacc_inputs" | "other"
    source_path: Path
    report_date: str | None  # ISO date if derivable, else None
    content_hash: str  # SHA-256 hex
    ingested_at: datetime
    mode: str  # "bulk_markdown" | "pre_extracted"
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestionResult:
    """Outcome of a single ingest call.

    ``documents`` are those successfully registered. ``errors`` holds
    non-fatal warnings — fatal failures raise :class:`IngestionError`
    before the call returns.
    """

    ticker: str
    documents: list[IngestedDocument]
    errors: list[str] = field(default_factory=list)
    mode: str = ""


class IngestionMode(ABC):
    """Abstract base — every mode validates input, then registers files."""

    mode_name: str = ""

    @abstractmethod
    def ingest(self, ticker: str, files: list[Path]) -> IngestionResult:
        """Validate, store, and register files; return the composite result."""

    @abstractmethod
    def validate(self, files: list[Path]) -> list[str]:
        """Return validation error strings. Strings prefixed ``FATAL:`` are
        treated as blockers by the coordinator; others are warnings."""
