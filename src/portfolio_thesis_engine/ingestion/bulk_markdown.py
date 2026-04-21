"""Modo B — bulk markdown ingestion.

Accepts one or more large markdown files produced manually from a PDF or
similar source. Each file gets a ``doc_type`` inferred from its filename,
a content hash, and an ISO ``report_date`` guess when the filename
encodes a year.
"""

from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from pathlib import Path

from portfolio_thesis_engine.ingestion.base import (
    IngestedDocument,
    IngestionError,
    IngestionMode,
    IngestionResult,
)
from portfolio_thesis_engine.storage.base import normalise_ticker
from portfolio_thesis_engine.storage.filesystem_repo import DocumentRepository

_MAX_FILE_BYTES = 50_000_000  # 50 MB sanity cap
_FINANCIAL_KEYWORDS = ("revenue", "income", "equity", "cash", "assets")
_WACC_FILE_STEM = "wacc_inputs"
_YEAR_RE = re.compile(r"(20\d{2})")
_QUARTER_RE = re.compile(r"(?i)q[1-4]|h[12]|interim")


def _infer_doc_type(path: Path) -> str:
    """Infer ``doc_type`` from the filename alone (cheap, deterministic)."""
    stem = path.stem.lower()
    if stem == _WACC_FILE_STEM:
        return "wacc_inputs"
    if "annual" in stem or stem.startswith("ar_") or "_ar_" in stem:
        return "annual_report"
    if _QUARTER_RE.search(stem):
        return "interim_report"
    return "other"


def _infer_report_date(path: Path, doc_type: str) -> str | None:
    """Best-effort ISO date from the filename. Returns ``None`` when
    nothing obvious matches — callers can fill it in later if needed."""
    if doc_type == "wacc_inputs":
        return None
    match = _YEAR_RE.search(path.stem)
    if not match:
        return None
    year = match.group(1)
    # Conservative: annual reports close on Dec 31; interim defaults to June 30
    if doc_type == "interim_report":
        return f"{year}-06-30"
    return f"{year}-12-31"


def _sha256(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class BulkMarkdownMode(IngestionMode):
    """Store one or more large markdown files as blob documents.

    Validation covers presence, non-emptiness, a 50 MB sanity cap,
    UTF-8 decodability, and a cheap keyword sniff to warn when a file
    doesn't look financial.
    """

    mode_name = "bulk_markdown"

    def __init__(self, document_repo: DocumentRepository) -> None:
        self.document_repo = document_repo

    # ------------------------------------------------------------------
    def validate(self, files: list[Path]) -> list[str]:
        errors: list[str] = []
        if not files:
            errors.append("FATAL: no files supplied")
            return errors
        for f in files:
            if not f.exists():
                errors.append(f"FATAL: {f} does not exist")
                continue
            if not f.is_file():
                errors.append(f"FATAL: {f} is not a regular file")
                continue
            size = f.stat().st_size
            if size == 0:
                errors.append(f"FATAL: {f} is empty")
                continue
            if size > _MAX_FILE_BYTES:
                errors.append(f"WARN: {f} is very large ({size / 1e6:.1f} MB)")
            try:
                content = f.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                errors.append(f"FATAL: {f} is not valid UTF-8")
                continue
            # Cheap financial sanity check — skip WACC files (they don't
            # contain IS/BS/CF prose).
            if _infer_doc_type(f) != "wacc_inputs":
                lower = content.lower()
                if not any(w in lower for w in _FINANCIAL_KEYWORDS):
                    errors.append(
                        f"WARN: {f} does not contain common financial keywords "
                        f"({', '.join(_FINANCIAL_KEYWORDS)}); double-check it's a "
                        f"financial report"
                    )
        return errors

    # ------------------------------------------------------------------
    def ingest(self, ticker: str, files: list[Path]) -> IngestionResult:
        errors = self.validate(files)
        fatal = [e for e in errors if e.startswith("FATAL")]
        if fatal:
            raise IngestionError("; ".join(fatal))

        normalised = normalise_ticker(ticker)
        documents: list[IngestedDocument] = []
        for f in files:
            raw = f.read_bytes()
            content_hash = _sha256(raw)
            doc_type = _infer_doc_type(f)
            report_date = _infer_report_date(f, doc_type)

            # Store the blob in DocumentRepository under
            # {ticker}/{doc_type}/{date?}_{filename}
            stored_name = self._stored_name(f, report_date)
            stored_path = self.document_repo.store(
                ticker=normalised,
                doc_type=doc_type,
                filename=stored_name,
                content=raw,
            )
            documents.append(
                IngestedDocument(
                    doc_id=f"{normalised}/{doc_type}/{stored_name}",
                    ticker=normalised,
                    doc_type=doc_type,
                    source_path=stored_path,
                    report_date=report_date,
                    content_hash=content_hash,
                    ingested_at=datetime.now(UTC),
                    mode=self.mode_name,
                    metadata={"size_bytes": len(raw)},
                )
            )

        return IngestionResult(
            ticker=normalised,
            documents=documents,
            errors=[e for e in errors if not e.startswith("FATAL")],
            mode=self.mode_name,
        )

    # ------------------------------------------------------------------
    @staticmethod
    def _stored_name(src: Path, report_date: str | None) -> str:
        """Filename used inside DocumentRepository.

        Prefix with the ISO date when we have one so files sort
        chronologically; otherwise keep the original stem + suffix.
        """
        if report_date is None:
            return src.name
        # Avoid double-prefix if the caller already embedded the date
        if report_date in src.stem:
            return src.name
        return f"{report_date}_{src.name}"
