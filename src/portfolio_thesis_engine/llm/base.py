"""Abstract LLM provider interfaces.

:class:`LLMProvider` — completion-style providers (Anthropic Claude).
:class:`EmbeddingsProvider` — embedding-only providers (OpenAI).

Request/response types are plain dataclasses (not Pydantic) so they stay
lightweight at call sites and don't trigger validation overhead per request.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass
class LLMRequest:
    """A single LLM completion request."""

    prompt: str
    system: str | None = None
    model: str | None = None
    max_tokens: int = 4096
    temperature: float = 0.0
    tools: list[dict[str, Any]] | None = None
    tool_choice: dict[str, Any] | None = None
    response_schema: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    """Response from an LLM completion call."""

    content: str
    structured_output: dict[str, Any] | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: Decimal = Decimal("0")
    model_used: str = ""
    latency_ms: int = 0
    stop_reason: str | None = None
    raw_response: Any = None


class LLMProvider(ABC):
    """Abstract completion provider."""

    @abstractmethod
    async def complete(self, request: LLMRequest) -> LLMResponse:
        """Async completion."""

    @abstractmethod
    def complete_sync(self, request: LLMRequest) -> LLMResponse:
        """Synchronous completion. Typically wraps :meth:`complete` via asyncio."""


class EmbeddingsProvider(ABC):
    """Abstract embeddings provider."""

    @abstractmethod
    async def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        """Embed a batch of texts."""
