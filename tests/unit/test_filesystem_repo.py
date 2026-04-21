"""Unit tests for storage/filesystem_repo.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from portfolio_thesis_engine.storage.base import NotFoundError
from portfolio_thesis_engine.storage.filesystem_repo import DocumentRepository


@pytest.fixture
def repo(tmp_path: Path) -> DocumentRepository:
    return DocumentRepository(base_path=tmp_path)


class TestStoreRetrieve:
    def test_store_and_retrieve_bytes(self, repo: DocumentRepository) -> None:
        content = b"%PDF-1.4 fake pdf\n"
        path = repo.store("ACME", "filings", "2024-12-31_10K.pdf", content)
        assert path.exists()
        assert repo.retrieve("ACME", "filings", "2024-12-31_10K.pdf") == content

    def test_retrieve_missing_raises_notfound(self, repo: DocumentRepository) -> None:
        with pytest.raises(NotFoundError):
            repo.retrieve("ACME", "filings", "nope.pdf")

    def test_exists(self, repo: DocumentRepository) -> None:
        assert not repo.exists("ACME", "filings", "x.pdf")
        repo.store("ACME", "filings", "x.pdf", b"x")
        assert repo.exists("ACME", "filings", "x.pdf")

    def test_overwrite_replaces_content(self, repo: DocumentRepository) -> None:
        repo.store("ACME", "filings", "x.pdf", b"v1")
        repo.store("ACME", "filings", "x.pdf", b"v2")
        assert repo.retrieve("ACME", "filings", "x.pdf") == b"v2"


class TestListDelete:
    def test_list_documents_scoped_to_doc_type(self, repo: DocumentRepository) -> None:
        repo.store("ACME", "filings", "2024-12-31_10K.pdf", b"x")
        repo.store("ACME", "filings", "2024-06-30_10Q.pdf", b"x")
        repo.store("ACME", "transcripts", "2024-Q4.pdf", b"x")
        filings = repo.list_documents("ACME", doc_type="filings")
        assert len(filings) == 2
        assert all(p.parent.name == "filings" for p in filings)

    def test_list_all_for_ticker(self, repo: DocumentRepository) -> None:
        repo.store("ACME", "filings", "f.pdf", b"x")
        repo.store("ACME", "transcripts", "t.pdf", b"x")
        paths = repo.list_documents("ACME")
        assert len(paths) == 2

    def test_list_empty_ticker_returns_empty(self, repo: DocumentRepository) -> None:
        assert repo.list_documents("GHOST") == []

    def test_delete(self, repo: DocumentRepository) -> None:
        repo.store("ACME", "filings", "x.pdf", b"x")
        repo.delete("ACME", "filings", "x.pdf")
        assert not repo.exists("ACME", "filings", "x.pdf")

    def test_delete_missing_is_noop(self, repo: DocumentRepository) -> None:
        repo.delete("ACME", "filings", "never_existed.pdf")


class TestTickerNormalisation:
    """DocumentRepository normalises ticker on every public method so
    callers may pass either ``TEST.L`` or ``TEST-L``."""

    def test_store_with_dotted_ticker_lands_on_normalised_path(
        self, repo: DocumentRepository, tmp_path: Path
    ) -> None:
        path = repo.store("TEST.L", "filings", "doc.pdf", b"content")
        assert path == tmp_path / "TEST-L" / "filings" / "doc.pdf"

    def test_retrieve_symmetric_across_forms(self, repo: DocumentRepository) -> None:
        repo.store("TEST.L", "filings", "doc.pdf", b"payload")
        assert repo.retrieve("TEST.L", "filings", "doc.pdf") == b"payload"
        assert repo.retrieve("TEST-L", "filings", "doc.pdf") == b"payload"

    def test_exists_symmetric_across_forms(self, repo: DocumentRepository) -> None:
        repo.store("TEST.L", "filings", "doc.pdf", b"x")
        assert repo.exists("TEST.L", "filings", "doc.pdf") is True
        assert repo.exists("TEST-L", "filings", "doc.pdf") is True

    def test_delete_with_dotted_ticker(self, repo: DocumentRepository) -> None:
        repo.store("TEST.L", "filings", "doc.pdf", b"x")
        repo.delete("TEST.L", "filings", "doc.pdf")
        assert repo.exists("TEST-L", "filings", "doc.pdf") is False

    def test_list_documents_with_dotted_ticker(self, repo: DocumentRepository) -> None:
        repo.store("TEST.L", "filings", "a.pdf", b"x")
        repo.store("TEST.L", "filings", "b.pdf", b"x")
        assert len(repo.list_documents("TEST.L")) == 2
        assert len(repo.list_documents("TEST-L")) == 2
