"""Modo A stub — Fase 2.

Pre-extracted ingestion (``raw/01_bs_raw.md``, ``raw/02_is_raw.md`` …) is
scheduled for Phase 2. The stub keeps the coordinator's dispatch table
symmetrical and gives callers a useful error message if they try to use
it early.
"""

from __future__ import annotations

from pathlib import Path

from portfolio_thesis_engine.ingestion.base import (
    IngestionMode,
    IngestionResult,
)


class PreExtractedMode(IngestionMode):
    """Placeholder for the Phase 2 raw/-files ingestion mode."""

    mode_name = "pre_extracted"

    def ingest(self, ticker: str, files: list[Path]) -> IngestionResult:
        raise NotImplementedError(
            "PreExtractedMode is Phase 2 — use BulkMarkdownMode for now "
            "(pass --mode bulk_markdown to `pte ingest`)."
        )

    def validate(self, files: list[Path]) -> list[str]:
        return ["FATAL: PreExtractedMode is Phase 2, use BulkMarkdownMode"]
