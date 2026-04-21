"""Tests for shared.exceptions hierarchy."""

import pytest

from portfolio_thesis_engine.shared.exceptions import (
    ConfigError,
    CostLimitExceededError,
    GuardrailError,
    LLMError,
    MarketDataError,
    ModelNotFoundError,
    NotFoundError,
    PTEError,
    RateLimitError,
    SchemaValidationError,
    StorageError,
    VersionConflictError,
)


@pytest.mark.parametrize(
    "exc",
    [
        ConfigError,
        SchemaValidationError,
        StorageError,
        NotFoundError,
        VersionConflictError,
        LLMError,
        RateLimitError,
        CostLimitExceededError,
        ModelNotFoundError,
        MarketDataError,
        GuardrailError,
    ],
)
def test_all_exceptions_inherit_from_pte_error(exc: type[Exception]) -> None:
    assert issubclass(exc, PTEError)
    assert issubclass(exc, Exception)


def test_storage_subclasses_inherit_from_storage_error() -> None:
    assert issubclass(NotFoundError, StorageError)
    assert issubclass(VersionConflictError, StorageError)


def test_llm_subclasses_inherit_from_llm_error() -> None:
    assert issubclass(RateLimitError, LLMError)
    assert issubclass(CostLimitExceededError, LLMError)
    assert issubclass(ModelNotFoundError, LLMError)


def test_exception_can_be_raised_and_caught_by_base() -> None:
    with pytest.raises(PTEError) as excinfo:
        raise CostLimitExceededError("budget blown: $16 of $15")
    assert "budget blown" in str(excinfo.value)


def test_catching_storage_error_does_not_swallow_llm_error() -> None:
    with pytest.raises(LLMError):
        try:
            raise RateLimitError("429")
        except StorageError:
            pytest.fail("StorageError handler should not catch LLMError")
