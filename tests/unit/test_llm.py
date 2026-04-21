"""Unit tests for the LLM orchestrator.

All provider interactions are mocked — **no real API calls**. The real-API
smoke suite lives at ``tests/integration/test_llm_real.py`` and is gated
by ``PTE_SMOKE_HIT_REAL_APIS=true``.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from portfolio_thesis_engine.llm.anthropic_provider import (
    _DEFAULT_PRICING,
    AnthropicProvider,
    load_pricing,
)
from portfolio_thesis_engine.llm.base import LLMRequest, LLMResponse
from portfolio_thesis_engine.llm.cost_tracker import (
    CostTracker,
    get_cost_tracker,
    reset_cost_tracker,
)
from portfolio_thesis_engine.llm.openai_provider import OpenAIEmbeddingsProvider
from portfolio_thesis_engine.llm.retry import RETRYABLE_EXCEPTIONS, with_retry
from portfolio_thesis_engine.llm.router import TaskType, model_for_task
from portfolio_thesis_engine.llm.structured import (
    build_tool,
    extract_structured,
    force_tool_choice,
    structured_request,
)

# ======================================================================
# router
# ======================================================================


class TestRouter:
    def test_task_type_values(self) -> None:
        assert TaskType.CLASSIFICATION.value == "classification"
        assert TaskType.JUDGMENT.value == "judgment"

    def test_model_for_task_mapping(self) -> None:
        assert model_for_task(TaskType.CLASSIFICATION) == "claude-haiku-4-5-20251001"
        assert model_for_task(TaskType.ANALYSIS) == "claude-sonnet-4-6"
        assert model_for_task(TaskType.EXTRACTION) == "claude-sonnet-4-6"
        assert model_for_task(TaskType.JUDGMENT) == "claude-opus-4-7"
        assert model_for_task(TaskType.NARRATIVE) == "claude-sonnet-4-6"


# ======================================================================
# pricing
# ======================================================================


class TestPricing:
    def test_defaults_loaded_when_no_override(self) -> None:
        pricing = load_pricing(None)
        for model, spec in _DEFAULT_PRICING.items():
            assert pricing[model]["input"] == spec["input"]
            assert pricing[model]["output"] == spec["output"]

    def test_override_adds_new_model(self) -> None:
        override = json.dumps({"custom-model": {"input": "0.50", "output": "2.00"}})
        pricing = load_pricing(override)
        assert pricing["custom-model"]["input"] == Decimal("0.50")
        assert pricing["custom-model"]["output"] == Decimal("2.00")
        # defaults still present
        assert "claude-opus-4-7" in pricing

    def test_override_replaces_existing_model(self) -> None:
        override = json.dumps({"claude-opus-4-7": {"input": "99.99", "output": "199.99"}})
        pricing = load_pricing(override)
        assert pricing["claude-opus-4-7"]["input"] == Decimal("99.99")
        assert pricing["claude-opus-4-7"]["output"] == Decimal("199.99")

    def test_malformed_override_falls_back_to_defaults(self) -> None:
        pricing = load_pricing("{invalid_json")
        assert pricing == _DEFAULT_PRICING

    def test_partial_override_entry_ignored(self) -> None:
        # Missing 'output' key — entire entry skipped
        pricing = load_pricing(json.dumps({"m": {"input": "1.0"}}))
        assert "m" not in pricing


# ======================================================================
# AnthropicProvider — mocked
# ======================================================================


def _fake_usage(inp: int, out: int) -> SimpleNamespace:
    return SimpleNamespace(input_tokens=inp, output_tokens=out)


def _fake_text_response(text: str, inp: int = 10, out: int = 20) -> SimpleNamespace:
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)],
        usage=_fake_usage(inp, out),
        stop_reason="end_turn",
    )


def _fake_tool_use_response(tool_input: dict, inp: int = 15, out: int = 40) -> SimpleNamespace:
    return SimpleNamespace(
        content=[
            SimpleNamespace(type="tool_use", input=tool_input),
        ],
        usage=_fake_usage(inp, out),
        stop_reason="tool_use",
    )


def _build_provider(
    async_return: SimpleNamespace, sync_return: SimpleNamespace | None = None
) -> AnthropicProvider:
    async_client = MagicMock()
    async_client.messages = MagicMock()
    async_client.messages.create = AsyncMock(return_value=async_return)
    sync_client = MagicMock()
    sync_client.messages = MagicMock()
    sync_client.messages.create = MagicMock(return_value=sync_return or async_return)
    return AnthropicProvider(
        api_key="test-key",
        sync_client=sync_client,
        async_client=async_client,
    )


class TestAnthropicProvider:
    def test_compute_cost_known_model(self) -> None:
        p = _build_provider(_fake_text_response("hi"))
        # 1M input tokens at $3.00 → exactly $3.00 for sonnet
        assert p.compute_cost("claude-sonnet-4-6", 1_000_000, 0) == Decimal("3.00")
        # Output side
        assert p.compute_cost("claude-sonnet-4-6", 0, 500_000) == Decimal("7.50")

    def test_compute_cost_unknown_model_returns_zero(self) -> None:
        p = _build_provider(_fake_text_response("hi"))
        assert p.compute_cost("not-a-real-model", 1000, 1000) == Decimal("0")

    @pytest.mark.asyncio
    async def test_complete_returns_parsed_response(self) -> None:
        p = _build_provider(_fake_text_response("hello world", inp=100, out=200))
        req = LLMRequest(prompt="say hi", model="claude-sonnet-4-6")
        resp = await p.complete(req)
        assert resp.content == "hello world"
        assert resp.input_tokens == 100
        assert resp.output_tokens == 200
        assert resp.model_used == "claude-sonnet-4-6"
        # 100 input * $3/M + 200 output * $15/M = $0.0003 + $0.003 = $0.0033
        assert resp.cost_usd == Decimal("0.00330000")
        assert resp.stop_reason == "end_turn"

    @pytest.mark.asyncio
    async def test_complete_forwards_system_and_tools(self) -> None:
        p = _build_provider(_fake_text_response("x"))
        req = LLMRequest(
            prompt="run",
            system="you are a bot",
            tools=[{"name": "t", "description": "d", "input_schema": {}}],
            tool_choice={"type": "tool", "name": "t"},
            max_tokens=512,
            temperature=0.3,
        )
        await p.complete(req)
        call_kwargs = p.async_client.messages.create.await_args.kwargs
        assert call_kwargs["system"] == "you are a bot"
        assert call_kwargs["tools"][0]["name"] == "t"
        assert call_kwargs["tool_choice"]["name"] == "t"
        assert call_kwargs["max_tokens"] == 512
        assert call_kwargs["temperature"] == 0.3

    @pytest.mark.asyncio
    async def test_complete_parses_tool_use_block(self) -> None:
        p = _build_provider(_fake_tool_use_response({"answer": 42, "unit": "mg"}))
        req = LLMRequest(prompt="?", model="claude-sonnet-4-6")
        resp = await p.complete(req)
        assert resp.structured_output == {"answer": 42, "unit": "mg"}
        assert resp.content == ""  # tool_use blocks don't contribute text

    def test_complete_sync_runs_outside_loop(self) -> None:
        p = _build_provider(_fake_text_response("sync hello", inp=5, out=5))
        req = LLMRequest(prompt="hi", model="claude-sonnet-4-6")
        resp = p.complete_sync(req)
        assert resp.content == "sync hello"

    def test_complete_sync_inside_running_loop_uses_sync_client(self) -> None:
        sync_resp = _fake_text_response("from sync client", inp=5, out=5)
        async_resp = _fake_text_response("from async client")
        p = _build_provider(async_return=async_resp, sync_return=sync_resp)

        async def driver() -> str:
            # Running inside an asyncio event loop → must fall through to sync
            return p.complete_sync(LLMRequest(prompt="x", model="claude-sonnet-4-6")).content

        result = asyncio.run(driver())
        assert result == "from sync client"


# ======================================================================
# OpenAIEmbeddingsProvider — mocked
# ======================================================================


def _build_embed_provider(vectors: list[list[float]]) -> OpenAIEmbeddingsProvider:
    async_client = MagicMock()
    async_client.embeddings = MagicMock()
    fake_response = SimpleNamespace(data=[SimpleNamespace(embedding=v) for v in vectors])
    async_client.embeddings.create = AsyncMock(return_value=fake_response)
    sync_client = MagicMock()
    sync_client.embeddings = MagicMock()
    sync_client.embeddings.create = MagicMock(return_value=fake_response)
    return OpenAIEmbeddingsProvider(
        api_key="test-key", sync_client=sync_client, async_client=async_client
    )


class TestOpenAIEmbeddingsProvider:
    @pytest.mark.asyncio
    async def test_embed_returns_vectors(self) -> None:
        vecs = [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
        p = _build_embed_provider(vecs)
        result = await p.embed(["foo", "bar"])
        assert result == vecs

    @pytest.mark.asyncio
    async def test_embed_empty_is_noop(self) -> None:
        p = _build_embed_provider([])
        assert await p.embed([]) == []

    def test_embed_sync(self) -> None:
        vecs = [[1.0, 2.0]]
        p = _build_embed_provider(vecs)
        assert p.embed_sync(["only"]) == vecs

    @pytest.mark.asyncio
    async def test_embed_forwards_model(self) -> None:
        p = _build_embed_provider([[0.0]])
        await p.embed(["text"], model="text-embedding-3-large")
        kwargs = p.async_client.embeddings.create.await_args.kwargs
        assert kwargs["model"] == "text-embedding-3-large"


# ======================================================================
# CostTracker
# ======================================================================


class TestCostTracker:
    def test_record_appends_to_session_and_jsonl(self, tmp_path: Path) -> None:
        t = CostTracker(log_path=tmp_path / "costs.jsonl")
        entry = t.record(
            operation="extract_taxes",
            model="claude-sonnet-4-6",
            input_tokens=1000,
            output_tokens=500,
            cost_usd=Decimal("0.0105"),
            ticker="ACME",
        )
        assert entry.ticker == "ACME"
        assert t.session_total() == Decimal("0.0105")
        assert len(t.session_entries()) == 1
        # Persisted to JSONL
        lines = (tmp_path / "costs.jsonl").read_text().splitlines()
        assert len(lines) == 1
        payload = json.loads(lines[0])
        assert payload["ticker"] == "ACME"
        assert payload["cost_usd"] == "0.0105"

    def test_session_total_sums_multiple(self, tmp_path: Path) -> None:
        t = CostTracker(log_path=tmp_path / "costs.jsonl")
        t.record("op", "m", 0, 0, Decimal("1.00"))
        t.record("op", "m", 0, 0, Decimal("2.50"))
        t.record("op", "m", 0, 0, Decimal("0.25"))
        assert t.session_total() == Decimal("3.75")

    def test_ticker_total_reads_from_log(self, tmp_path: Path) -> None:
        t = CostTracker(log_path=tmp_path / "costs.jsonl")
        t.record("op", "m", 0, 0, Decimal("1.00"), ticker="ACME")
        t.record("op", "m", 0, 0, Decimal("2.00"), ticker="ACME")
        t.record("op", "m", 0, 0, Decimal("5.00"), ticker="OTHER")
        assert t.ticker_total("ACME") == Decimal("3.00")
        assert t.ticker_total("OTHER") == Decimal("5.00")
        assert t.ticker_total("MISSING") == Decimal("0")

    def test_ticker_total_with_no_log_returns_zero(self, tmp_path: Path) -> None:
        # Never record — log file never gets created
        t = CostTracker(log_path=tmp_path / "never.jsonl")
        assert t.ticker_total("ACME") == Decimal("0")

    def test_singleton_lifecycle(self, tmp_path: Path, monkeypatch) -> None:
        reset_cost_tracker()
        # Point the singleton at a tmp dir so it doesn't pollute real data
        monkeypatch.setattr(
            "portfolio_thesis_engine.shared.config.settings.data_dir",
            tmp_path,
        )
        a = get_cost_tracker()
        b = get_cost_tracker()
        assert a is b
        reset_cost_tracker()
        c = get_cost_tracker()
        assert c is not a


# ======================================================================
# retry
# ======================================================================


class TestRetry:
    def test_retryable_exceptions_include_baseline(self) -> None:
        assert ConnectionError in RETRYABLE_EXCEPTIONS
        assert TimeoutError in RETRYABLE_EXCEPTIONS

    def test_retries_on_connection_error_then_succeeds(self) -> None:
        attempts = {"count": 0}

        @with_retry(max_attempts=3, wait_min=0, wait_max=0)
        def flaky() -> str:
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise ConnectionError("transient")
            return "ok"

        assert flaky() == "ok"
        assert attempts["count"] == 3

    def test_does_not_retry_on_unlisted_exception(self) -> None:
        attempts = {"count": 0}

        @with_retry(max_attempts=3, wait_min=0, wait_max=0)
        def boom() -> None:
            attempts["count"] += 1
            raise ValueError("non-retryable")

        with pytest.raises(ValueError):
            boom()
        assert attempts["count"] == 1

    def test_exhausts_attempts_then_reraises(self) -> None:
        @with_retry(max_attempts=2, wait_min=0, wait_max=0)
        def always_fail() -> None:
            raise ConnectionError("still bad")

        with pytest.raises(ConnectionError):
            always_fail()

    @pytest.mark.asyncio
    async def test_async_function_is_supported(self) -> None:
        attempts = {"count": 0}

        @with_retry(max_attempts=2, wait_min=0, wait_max=0)
        async def flaky() -> str:
            attempts["count"] += 1
            if attempts["count"] < 2:
                raise ConnectionError("transient")
            return "ok"

        assert await flaky() == "ok"
        assert attempts["count"] == 2


# ======================================================================
# structured outputs helpers
# ======================================================================


class TestStructuredHelpers:
    def test_build_tool_shape(self) -> None:
        tool = build_tool(
            "classify",
            "classify the adjustment",
            {"type": "object", "properties": {"bucket": {"type": "string"}}},
        )
        assert tool["name"] == "classify"
        assert tool["description"] == "classify the adjustment"
        assert tool["input_schema"]["type"] == "object"

    def test_force_tool_choice(self) -> None:
        assert force_tool_choice("x") == {"type": "tool", "name": "x"}

    def test_structured_request_wires_tool(self) -> None:
        req = structured_request(
            prompt="p",
            tool_name="result",
            description="return result",
            input_schema={"type": "object"},
            system="you are strict",
            max_tokens=1024,
        )
        assert req.tools is not None
        assert len(req.tools) == 1
        assert req.tools[0]["name"] == "result"
        assert req.tool_choice == {"type": "tool", "name": "result"}
        assert req.system == "you are strict"
        assert req.max_tokens == 1024

    def test_extract_structured(self) -> None:
        resp = LLMResponse(content="", structured_output={"k": "v"})
        assert extract_structured(resp) == {"k": "v"}
        empty = LLMResponse(content="text")
        assert extract_structured(empty) is None
