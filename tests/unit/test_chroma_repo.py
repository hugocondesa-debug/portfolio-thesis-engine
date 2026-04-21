"""Unit tests for storage/chroma_repo.py."""

from __future__ import annotations

from pathlib import Path

import pytest

from portfolio_thesis_engine.storage.chroma_repo import (
    RAGRepository,
    default_stub_embedding_fn,
)


@pytest.fixture
def repo(tmp_path: Path) -> RAGRepository:
    return RAGRepository(path=tmp_path)


class TestStubEmbedding:
    def test_is_deterministic(self) -> None:
        a = default_stub_embedding_fn(["hello"])
        b = default_stub_embedding_fn(["hello"])
        assert a == b

    def test_dimension_is_sixteen(self) -> None:
        vectors = default_stub_embedding_fn(["one", "two"])
        assert len(vectors) == 2
        assert all(len(v) == 16 for v in vectors)

    def test_different_texts_produce_different_vectors(self) -> None:
        a = default_stub_embedding_fn(["apple"])[0]
        b = default_stub_embedding_fn(["banana"])[0]
        assert a != b


class TestIndexing:
    def test_index_and_count(self, repo: RAGRepository) -> None:
        repo.index("filings", "doc1", "Revenue grew 15% YoY", {"ticker": "ACME", "year": 2024})
        assert repo.count("filings") == 1

    def test_index_upsert_updates_in_place(self, repo: RAGRepository) -> None:
        repo.index("filings", "doc1", "original text", {"ticker": "ACME"})
        repo.index("filings", "doc1", "updated text", {"ticker": "ACME"})
        assert repo.count("filings") == 1

    def test_batch_index_with_full_metadata(self, repo: RAGRepository) -> None:
        docs = [
            ("d1", "first", {"t": "A"}),
            ("d2", "second", {"t": "B"}),
            ("d3", "third", {"t": "C"}),
        ]
        repo.index_batch("notes", docs)
        assert repo.count("notes") == 3

    def test_batch_index_all_none_metadata(self, repo: RAGRepository) -> None:
        docs = [
            ("d1", "first", None),
            ("d2", "second", None),
        ]
        repo.index_batch("notes_nometa", docs)
        assert repo.count("notes_nometa") == 2

    def test_batch_index_mixed_metadata_drops_all_metadata(self, repo: RAGRepository) -> None:
        """Chroma forbids mixed None/dict metadata — the helper drops it all."""
        docs = [
            ("d1", "first", {"t": "A"}),
            ("d2", "second", None),
        ]
        repo.index_batch("notes_mixed", docs)
        assert repo.count("notes_mixed") == 2
        # Verify metadata was not persisted (the surviving metadata would
        # otherwise enable a where-filter hit)
        hits = repo.search("notes_mixed", "query", n_results=5, where={"t": "A"})
        assert hits == []

    def test_batch_empty_is_noop(self, repo: RAGRepository) -> None:
        repo.index_batch("empty_collection", [])
        # Collection shouldn't error when queried even if empty on the first
        # touch
        assert repo.count("empty_collection") == 0


class TestSearch:
    def test_search_returns_hits(self, repo: RAGRepository) -> None:
        repo.index("filings", "doc1", "Apple reported record revenue", None)
        repo.index("filings", "doc2", "Beta reported loss", None)
        results = repo.search("filings", "Apple revenue", n_results=2)
        assert len(results) <= 2
        ids = {r["id"] for r in results}
        assert "doc1" in ids

    def test_search_with_where_filters_by_metadata(self, repo: RAGRepository) -> None:
        repo.index("filings", "doc1", "anything", {"ticker": "ACME"})
        repo.index("filings", "doc2", "anything", {"ticker": "BETA"})
        results = repo.search("filings", "query", n_results=5, where={"ticker": "ACME"})
        assert [r["id"] for r in results] == ["doc1"]

    def test_search_returns_empty_on_empty_collection(self, repo: RAGRepository) -> None:
        results = repo.search("filings", "anything", n_results=5)
        assert results == []


class TestDelete:
    def test_delete_removes_doc(self, repo: RAGRepository) -> None:
        repo.index("filings", "doc1", "text", None)
        repo.delete("filings", "doc1")
        assert repo.count("filings") == 0

    def test_delete_missing_is_noop(self, repo: RAGRepository) -> None:
        repo.delete("filings", "never_existed")


class TestDependencyInjection:
    def test_custom_embedding_fn_is_used(self, tmp_path: Path) -> None:
        calls: list[list[str]] = []

        def tracking_fn(texts: list[str]) -> list[list[float]]:
            calls.append(texts)
            return [[0.1] * 8 for _ in texts]

        r = RAGRepository(path=tmp_path, embedding_fn=tracking_fn)
        r.index("docs", "d1", "hello", None)
        assert calls, "custom embedding_fn must be invoked during index"
