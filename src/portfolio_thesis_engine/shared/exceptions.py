"""Custom exception hierarchy for Portfolio Thesis Engine.

Every internal exception inherits from :class:`PTEError` so callers can catch
engine errors without also swallowing unrelated ``Exception`` subclasses.
"""


class PTEError(Exception):
    """Base class for all Portfolio Thesis Engine errors."""


class ConfigError(PTEError):
    """Raised for invalid or missing configuration."""


class SchemaValidationError(PTEError):
    """Raised when a payload fails a Pydantic or business-rule validation
    beyond what Pydantic itself surfaces."""


class StorageError(PTEError):
    """Base class for storage/repository failures."""


class NotFoundError(StorageError):
    """Raised when a repository lookup misses."""


class VersionConflictError(StorageError):
    """Raised when an optimistic-locking write detects a concurrent update."""


class LLMError(PTEError):
    """Base class for LLM provider failures."""


class RateLimitError(LLMError):
    """Raised when a provider signals throttling (HTTP 429 or equivalent)."""


class CostLimitExceededError(LLMError):
    """Raised when a call would exceed the configured per-company cost cap."""


class ModelNotFoundError(LLMError):
    """Raised when the requested model ID is unknown to the provider."""


class MarketDataError(PTEError):
    """Base class for market-data provider failures."""


class GuardrailError(PTEError):
    """Raised when guardrail infrastructure itself fails (not a FAIL verdict,
    which is carried by :class:`GuardrailResult`)."""
