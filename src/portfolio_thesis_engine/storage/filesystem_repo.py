"""Filesystem-backed document repository for raw blobs (PDFs, transcripts, …).

Layout convention::

    {base_path}/{ticker}/{doc_type}/{filename}

Where ``filename`` typically follows ``YYYY-MM-DD_descriptor.{ext}``. The
repository is type-agnostic about the blob content — callers pass and
receive ``bytes``.
"""

from __future__ import annotations

from pathlib import Path

from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.storage.base import NotFoundError, StorageError


class DocumentRepository:
    """Store and retrieve arbitrary document blobs keyed by
    ``(ticker, doc_type, filename)``."""

    def __init__(self, base_path: Path | None = None) -> None:
        self.base_path = base_path or (settings.data_dir / "documents")
        self.base_path.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    def _path_for(self, ticker: str, doc_type: str, filename: str) -> Path:
        return self.base_path / ticker / doc_type / filename

    # ------------------------------------------------------------------
    def store(self, ticker: str, doc_type: str, filename: str, content: bytes) -> Path:
        """Write ``content`` and return the resulting absolute path.

        Overwrites if the file already exists — callers are expected to
        version at the filename level (e.g., by including a date).
        """
        path = self._path_for(ticker, doc_type, filename)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        except Exception as e:
            raise StorageError(f"Failed to write {path}: {e}") from e
        return path

    def retrieve(self, ticker: str, doc_type: str, filename: str) -> bytes:
        """Return the raw bytes. Raises :class:`NotFoundError` if absent."""
        path = self._path_for(ticker, doc_type, filename)
        if not path.exists():
            raise NotFoundError(f"Document not found: {path}")
        try:
            return path.read_bytes()
        except Exception as e:
            raise StorageError(f"Failed to read {path}: {e}") from e

    def exists(self, ticker: str, doc_type: str, filename: str) -> bool:
        return self._path_for(ticker, doc_type, filename).exists()

    def delete(self, ticker: str, doc_type: str, filename: str) -> None:
        """No-op if the document does not exist."""
        self._path_for(ticker, doc_type, filename).unlink(missing_ok=True)

    def list_documents(self, ticker: str, doc_type: str | None = None) -> list[Path]:
        """List documents for ``ticker``, optionally scoped to ``doc_type``.

        Returned paths are absolute and sorted. If the directory doesn't
        exist, returns an empty list.
        """
        root = self.base_path / ticker
        if doc_type is not None:
            root = root / doc_type
        if not root.exists():
            return []
        return sorted(p for p in root.rglob("*") if p.is_file())
