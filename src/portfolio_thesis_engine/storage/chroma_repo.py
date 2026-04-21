"""ChromaDB-backed RAG repository.

Collections are partitioned by document type (``filings``, ``transcripts``,
``news``). The embedding function is injected at construction time so the
repository stays decoupled from the OpenAI provider (landing in Sprint 6)
and tests can run without network access.

When no embedding function is supplied, a deterministic SHA-256-based stub
produces 16-dimensional vectors. The stub is good enough for the repository's
own roundtrip tests (it preserves the invariant that identical text yields
identical vectors) but is **not** semantically meaningful — production code
must inject a real embedding function.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings  # noqa: TC002

from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.storage.base import StorageError

EmbeddingFn = Callable[[list[str]], list[list[float]]]


def default_stub_embedding_fn(texts: list[str]) -> list[list[float]]:
    """Deterministic 16-dim SHA-256-based embedding. For tests only."""
    out: list[list[float]] = []
    for text in texts:
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        vec = [int.from_bytes(digest[i : i + 2], "big") / 65535.0 for i in range(0, 32, 2)]
        out.append(vec)
    return out


class _InjectedEmbeddingFn(EmbeddingFunction[Documents]):
    """Adapter that exposes an :class:`EmbeddingFn` through Chroma's
    :class:`EmbeddingFunction` protocol."""

    def __init__(self, fn: EmbeddingFn) -> None:
        self._fn = fn

    def __call__(self, input: Documents) -> Embeddings:  # noqa: A002 (chroma's name)
        return self._fn(list(input))  # type: ignore[return-value]


class RAGRepository:
    """Vector store for document chunks, partitioned by collection name.

    Call :meth:`index` to add a document, :meth:`search` to run semantic
    retrieval, and :meth:`delete` to remove a document by id.
    """

    def __init__(
        self,
        path: Path | None = None,
        embedding_fn: EmbeddingFn | None = None,
    ) -> None:
        self.path = path or (settings.data_dir / "rag")
        self.path.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(self.path))
        self._embedding_fn = embedding_fn or default_stub_embedding_fn
        self._chroma_embedding_fn = _InjectedEmbeddingFn(self._embedding_fn)

    # ------------------------------------------------------------------
    def _collection(self, name: str) -> chromadb.Collection:
        # chromadb's EmbeddingFunction generic parameter is a union the stubs
        # model imprecisely; our adapter handles the list[str] path fine.
        return self.client.get_or_create_collection(
            name=name,
            embedding_function=self._chroma_embedding_fn,  # type: ignore[arg-type]
        )

    # ------------------------------------------------------------------
    def index(
        self,
        collection: str,
        doc_id: str,
        text: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Add or overwrite a document chunk in ``collection``."""
        try:
            self._collection(collection).upsert(
                ids=[doc_id],
                documents=[text],
                metadatas=[metadata] if metadata else None,
            )
        except Exception as e:
            raise StorageError(f"Failed to index doc {doc_id!r} in {collection!r}: {e}") from e

    def index_batch(
        self,
        collection: str,
        docs: list[tuple[str, str, dict[str, Any] | None]],
    ) -> None:
        """Batch-upsert ``(id, text, metadata)`` tuples.

        Chroma requires either a non-empty metadata dict for every document
        or no metadatas array at all — mixed input is invalid. This helper
        passes metadatas only when *every* doc supplies one; otherwise it
        drops metadata for the whole batch.
        """
        if not docs:
            return
        ids = [d[0] for d in docs]
        texts = [d[1] for d in docs]
        metadatas: list[dict[str, Any]] | None = None
        if all(d[2] for d in docs):
            metadatas = [d[2] for d in docs]  # type: ignore[misc]
        try:
            self._collection(collection).upsert(
                ids=ids,
                documents=texts,
                metadatas=metadatas,  # type: ignore[arg-type]
            )
        except Exception as e:
            raise StorageError(
                f"Failed to batch-index {len(docs)} docs in {collection!r}: {e}"
            ) from e

    def search(
        self,
        collection: str,
        query: str,
        n_results: int = 5,
        where: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        """Return up to ``n_results`` matches, optionally filtered by metadata.

        Each result dict has keys ``id``, ``document``, ``metadata``, ``distance``.
        """
        try:
            raw = self._collection(collection).query(
                query_texts=[query], n_results=n_results, where=where
            )
        except Exception as e:
            raise StorageError(f"Search failed on {collection!r} for query {query!r}: {e}") from e

        ids = (raw.get("ids") or [[]])[0]
        documents = (raw.get("documents") or [[]])[0]
        metadatas_raw = (raw.get("metadatas") or [[]])[0]
        distances_raw = (raw.get("distances") or [[]])[0]
        metadatas: list[Any] = list(metadatas_raw) if metadatas_raw else [None] * len(ids)
        distances: list[Any] = list(distances_raw) if distances_raw else [None] * len(ids)
        return [
            {
                "id": i,
                "document": d,
                "metadata": m,
                "distance": dist,
            }
            for i, d, m, dist in zip(ids, documents, metadatas, distances, strict=False)
        ]

    def delete(self, collection: str, doc_id: str) -> None:
        """Remove a document from ``collection``. No-op if absent."""
        try:
            self._collection(collection).delete(ids=[doc_id])
        except Exception as e:
            raise StorageError(f"Failed to delete doc {doc_id!r} from {collection!r}: {e}") from e

    def count(self, collection: str) -> int:
        return self._collection(collection).count()
