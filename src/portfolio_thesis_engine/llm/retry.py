"""Retry with exponential backoff via :mod:`tenacity`.

Retryable exceptions include transient network errors (``ConnectionError``,
``TimeoutError``) and provider-specific rate-limit / transient errors from
the Anthropic and OpenAI SDKs when those modules are importable at runtime.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


def _collect_retryable_exceptions() -> tuple[type[BaseException], ...]:
    base: list[type[BaseException]] = [ConnectionError, TimeoutError]
    try:
        from anthropic import APIConnectionError, APITimeoutError, RateLimitError

        base.extend([APIConnectionError, APITimeoutError, RateLimitError])
    except ImportError:  # pragma: no cover - anthropic SDK should always be installed
        pass
    try:
        from openai import (
            APIConnectionError as OAIConnectionError,
        )
        from openai import (
            APITimeoutError as OAITimeoutError,
        )
        from openai import (
            RateLimitError as OAIRateLimitError,
        )

        base.extend([OAIConnectionError, OAITimeoutError, OAIRateLimitError])
    except ImportError:  # pragma: no cover - openai SDK should always be installed
        pass
    return tuple(base)


RETRYABLE_EXCEPTIONS: tuple[type[BaseException], ...] = _collect_retryable_exceptions()


def with_retry(
    max_attempts: int = 3,
    wait_min: int = 1,
    wait_max: int = 30,
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Decorator factory: retry on :data:`RETRYABLE_EXCEPTIONS` with
    exponential backoff bounded by ``[wait_min, wait_max]`` seconds.

    Applies to both sync and async callables; ``tenacity.retry`` handles both.
    """
    return retry(
        retry=retry_if_exception_type(RETRYABLE_EXCEPTIONS),
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=wait_min, max=wait_max),
        reraise=True,
    )
