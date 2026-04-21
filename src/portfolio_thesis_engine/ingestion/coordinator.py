"""IngestionCoordinator — picks a mode, runs it, registers the ticker."""

from __future__ import annotations

from pathlib import Path

from portfolio_thesis_engine.ingestion.base import (
    IngestionMode,
    IngestionResult,
)
from portfolio_thesis_engine.ingestion.bulk_markdown import BulkMarkdownMode
from portfolio_thesis_engine.ingestion.pre_extracted import PreExtractedMode
from portfolio_thesis_engine.storage.filesystem_repo import DocumentRepository
from portfolio_thesis_engine.storage.sqlite_repo import MetadataRepository


class IngestionCoordinator:
    """Facade that picks the right :class:`IngestionMode` by name and
    upserts the ticker row so downstream FKs succeed.

    Callers can override the mode table by passing ``modes=...``; the
    default table covers both Phase 1 modes.
    """

    def __init__(
        self,
        document_repo: DocumentRepository,
        metadata_repo: MetadataRepository,
        modes: dict[str, IngestionMode] | None = None,
    ) -> None:
        self.document_repo = document_repo
        self.metadata_repo = metadata_repo
        # Explicit None check so callers can inject an empty dict
        # (e.g., tests that want zero modes) without falling back to defaults.
        self.modes: dict[str, IngestionMode] = (
            {
                "bulk_markdown": BulkMarkdownMode(document_repo),
                "pre_extracted": PreExtractedMode(),
            }
            if modes is None
            else modes
        )

    def ingest(
        self,
        ticker: str,
        files: list[Path],
        mode: str = "bulk_markdown",
        profile: str = "P1",
    ) -> IngestionResult:
        """Run ``mode``'s ingestion for ``ticker`` and register the ticker.

        ``profile`` defaults to ``P1`` because every Phase 1 company is
        a P1 industrial; downstream profile assignment happens once the
        extractor has enough signal to classify.
        """
        if mode not in self.modes:
            raise ValueError(f"Unknown ingestion mode {mode!r}; available: {sorted(self.modes)}")

        result = self.modes[mode].ingest(ticker, files)
        # Register the ticker with minimal info — other columns fill in
        # later when the extractor learns the company name / exchange.
        self.metadata_repo.upsert_company(ticker=ticker, profile=profile)
        return result
