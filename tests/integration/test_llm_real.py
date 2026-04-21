"""Real-API smoke tests for LLM providers.

Gated by ``PTE_SMOKE_HIT_REAL_APIS=true``. When the env var is unset or
falsy, every test in this file is skipped — CI and default local runs
cost nothing. When enabled, the suite issues exactly two small calls
(one Anthropic completion, one OpenAI embedding) costing roughly $0.001
in aggregate; run manually after rotating API keys or upgrading SDKs.

::

    PTE_SMOKE_HIT_REAL_APIS=true uv run pytest tests/integration/test_llm_real.py -v
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from portfolio_thesis_engine.llm.anthropic_provider import AnthropicProvider
from portfolio_thesis_engine.llm.base import LLMRequest
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.llm.openai_provider import OpenAIEmbeddingsProvider
from portfolio_thesis_engine.llm.router import TaskType, model_for_task
from portfolio_thesis_engine.shared.config import settings

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not settings.smoke_hit_real_apis,
        reason="PTE_SMOKE_HIT_REAL_APIS must be true to hit real LLM APIs",
    ),
]


@pytest.mark.asyncio
async def test_anthropic_minimal_completion(tmp_path) -> None:
    """Issue the smallest possible Anthropic call and verify cost accounting."""
    provider = AnthropicProvider()
    tracker = CostTracker(log_path=tmp_path / "real_smoke.jsonl")

    request = LLMRequest(
        prompt="Reply with the two characters 'ok' and nothing else.",
        model=model_for_task(TaskType.CLASSIFICATION),
        max_tokens=16,
    )
    response = await provider.complete(request)

    assert response.content, "response must carry text"
    assert response.input_tokens > 0
    assert response.output_tokens > 0
    assert response.cost_usd > Decimal("0")
    assert response.model_used.startswith("claude-haiku")

    tracker.record(
        operation="smoke_test_anthropic",
        model=response.model_used,
        input_tokens=response.input_tokens,
        output_tokens=response.output_tokens,
        cost_usd=response.cost_usd,
    )
    assert tracker.session_total() == response.cost_usd


@pytest.mark.asyncio
async def test_openai_embeddings_minimal() -> None:
    """Issue the smallest possible embeddings request."""
    provider = OpenAIEmbeddingsProvider()
    vectors = await provider.embed(["portfolio thesis engine smoke test"])

    assert len(vectors) == 1
    assert len(vectors[0]) > 0, "embedding vector must be non-empty"
    # text-embedding-3-small is 1536-dim by default
    assert len(vectors[0]) >= 512
