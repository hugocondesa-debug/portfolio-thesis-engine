"""Anthropic Claude provider.

Pricing defaults are hard-coded; an operator may override them without a
redeploy by setting ``PTE_LLM_PRICING_JSON`` in the environment to a JSON
object mapping ``{model_id: {"input": decimal_str, "output": decimal_str}}``.
Values are per 1,000,000 tokens in USD.
"""

from __future__ import annotations

import asyncio
import json
import time
from decimal import Decimal
from typing import Any

from anthropic import Anthropic, AsyncAnthropic

from portfolio_thesis_engine.llm.base import LLMProvider, LLMRequest, LLMResponse
from portfolio_thesis_engine.shared.config import settings

_DEFAULT_PRICING: dict[str, dict[str, Decimal]] = {
    "claude-opus-4-7": {
        "input": Decimal("15.00"),
        "output": Decimal("75.00"),
    },
    "claude-sonnet-4-6": {
        "input": Decimal("3.00"),
        "output": Decimal("15.00"),
    },
    "claude-haiku-4-5-20251001": {
        "input": Decimal("0.80"),
        "output": Decimal("4.00"),
    },
}


def load_pricing(override_json: str | None = None) -> dict[str, dict[str, Decimal]]:
    """Merge hard-coded defaults with any JSON override.

    Passing ``override_json`` explicitly is primarily for tests; production
    code relies on ``settings.llm_pricing_json`` (sourced from
    ``PTE_LLM_PRICING_JSON``). Invalid overrides fall back to defaults.
    """
    pricing = {model: dict(prices) for model, prices in _DEFAULT_PRICING.items()}
    raw = override_json if override_json is not None else settings.llm_pricing_json
    if not raw:
        return pricing
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return pricing
    for model, spec in parsed.items():
        if not isinstance(spec, dict):
            continue
        if "input" not in spec or "output" not in spec:
            continue
        pricing[model] = {
            "input": Decimal(str(spec["input"])),
            "output": Decimal(str(spec["output"])),
        }
    return pricing


class AnthropicProvider(LLMProvider):
    """Provider wrapping the Anthropic Python SDK."""

    def __init__(
        self,
        api_key: str | None = None,
        pricing: dict[str, dict[str, Decimal]] | None = None,
        sync_client: Any = None,
        async_client: Any = None,
    ) -> None:
        self.api_key = api_key or settings.secret("anthropic_api_key")
        self.pricing = pricing if pricing is not None else load_pricing()
        self.sync_client = sync_client or Anthropic(api_key=self.api_key)
        self.async_client = async_client or AsyncAnthropic(api_key=self.api_key)

    def compute_cost(self, model: str, input_tokens: int, output_tokens: int) -> Decimal:
        """Return total cost in USD for a call. ``Decimal("0")`` for unknown
        models — callers should log-and-continue rather than raise."""
        spec = self.pricing.get(model)
        if not spec:
            return Decimal("0")
        million = Decimal("1000000")
        return (
            spec["input"] * Decimal(input_tokens) / million
            + spec["output"] * Decimal(output_tokens) / million
        )

    # ------------------------------------------------------------------
    def _build_kwargs(self, request: LLMRequest, model: str) -> dict[str, Any]:
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": request.max_tokens,
            "temperature": request.temperature,
            "messages": [{"role": "user", "content": request.prompt}],
        }
        if request.system:
            kwargs["system"] = request.system
        if request.tools:
            kwargs["tools"] = request.tools
        if request.tool_choice:
            kwargs["tool_choice"] = request.tool_choice
        return kwargs

    def _parse_response(self, response: Any, model: str, latency_ms: int) -> LLMResponse:
        content = ""
        structured: dict[str, Any] | None = None
        blocks = getattr(response, "content", None) or []
        for block in blocks:
            btype = getattr(block, "type", None)
            if btype == "text":
                content += getattr(block, "text", "") or ""
            elif btype == "tool_use":
                structured = getattr(block, "input", None)
        usage = getattr(response, "usage", None)
        input_tokens = getattr(usage, "input_tokens", 0) if usage else 0
        output_tokens = getattr(usage, "output_tokens", 0) if usage else 0
        return LLMResponse(
            content=content,
            structured_output=structured,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cost_usd=self.compute_cost(model, input_tokens, output_tokens),
            model_used=model,
            latency_ms=latency_ms,
            stop_reason=getattr(response, "stop_reason", None),
            raw_response=response,
        )

    # ------------------------------------------------------------------
    async def complete(self, request: LLMRequest) -> LLMResponse:
        model = request.model or settings.llm_model_analysis
        kwargs = self._build_kwargs(request, model)
        start = time.monotonic()
        response = await self.async_client.messages.create(**kwargs)
        latency_ms = int((time.monotonic() - start) * 1000)
        return self._parse_response(response, model, latency_ms)

    def complete_sync(self, request: LLMRequest) -> LLMResponse:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(self.complete(request))
        # Already inside an event loop — use the sync client directly.
        model = request.model or settings.llm_model_analysis
        kwargs = self._build_kwargs(request, model)
        start = time.monotonic()
        response = self.sync_client.messages.create(**kwargs)
        latency_ms = int((time.monotonic() - start) * 1000)
        return self._parse_response(response, model, latency_ms)
