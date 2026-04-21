"""Helpers for structured LLM outputs via tool use.

Anthropic's Messages API doesn't expose a first-class JSON-schema output
mode, so the canonical pattern is: declare a single tool whose
``input_schema`` matches the desired output, set ``tool_choice`` to force
the model to invoke it, and read the structured args back from the
tool-use block. These helpers standardise that wiring.
"""

from __future__ import annotations

from typing import Any

from portfolio_thesis_engine.llm.base import LLMRequest, LLMResponse


def build_tool(
    name: str,
    description: str,
    input_schema: dict[str, Any],
) -> dict[str, Any]:
    """Assemble an Anthropic tool definition from a JSON schema."""
    return {
        "name": name,
        "description": description,
        "input_schema": input_schema,
    }


def force_tool_choice(name: str) -> dict[str, Any]:
    """Return the ``tool_choice`` payload that forces a specific tool."""
    return {"type": "tool", "name": name}


def structured_request(
    prompt: str,
    tool_name: str,
    description: str,
    input_schema: dict[str, Any],
    *,
    system: str | None = None,
    model: str | None = None,
    max_tokens: int = 4096,
) -> LLMRequest:
    """Build an :class:`LLMRequest` that forces a single tool use.

    The response's ``structured_output`` will contain the dict the model
    passed to the tool, conforming to ``input_schema``.
    """
    tool = build_tool(tool_name, description, input_schema)
    return LLMRequest(
        prompt=prompt,
        system=system,
        model=model,
        max_tokens=max_tokens,
        tools=[tool],
        tool_choice=force_tool_choice(tool_name),
    )


def extract_structured(response: LLMResponse) -> dict[str, Any] | None:
    """Return the tool-use payload from a response, or ``None`` if absent."""
    return response.structured_output
