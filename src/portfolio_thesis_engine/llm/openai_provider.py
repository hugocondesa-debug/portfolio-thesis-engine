"""OpenAI provider — **embeddings only**.

Completions must go through Anthropic. This module exposes only the
embeddings endpoint so :class:`portfolio_thesis_engine.storage.chroma_repo.RAGRepository`
can plug a real embedding function in (Sprint 5 took an injectable stub
as placeholder).
"""

from __future__ import annotations

from typing import Any

from openai import AsyncOpenAI, OpenAI

from portfolio_thesis_engine.llm.base import EmbeddingsProvider
from portfolio_thesis_engine.shared.config import settings


class OpenAIEmbeddingsProvider(EmbeddingsProvider):
    """OpenAI embeddings provider (no completions)."""

    def __init__(
        self,
        api_key: str | None = None,
        sync_client: Any = None,
        async_client: Any = None,
    ) -> None:
        self.api_key = api_key or settings.secret("openai_api_key")
        self.sync_client = sync_client or OpenAI(api_key=self.api_key)
        self.async_client = async_client or AsyncOpenAI(api_key=self.api_key)

    async def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        if not texts:
            return []
        effective_model = model or settings.llm_model_embeddings
        response = await self.async_client.embeddings.create(
            input=texts,
            model=effective_model,
        )
        return [item.embedding for item in response.data]

    def embed_sync(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """Synchronous counterpart — useful at startup-time wiring."""
        if not texts:
            return []
        effective_model = model or settings.llm_model_embeddings
        response = self.sync_client.embeddings.create(input=texts, model=effective_model)
        return [item.embedding for item in response.data]
