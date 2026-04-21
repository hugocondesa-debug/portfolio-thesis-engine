"""Tests for shared.config."""

from pathlib import Path

import pytest
from pydantic import SecretStr, ValidationError

from portfolio_thesis_engine.shared.config import Settings


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Strip PTE_* and provider API keys so each test sees a clean slate."""
    for var in (
        "ANTHROPIC_API_KEY",
        "OPENAI_API_KEY",
        "FMP_API_KEY",
        "PTE_DATA_DIR",
        "PTE_BACKUP_DIR",
        "PTE_LOG_LEVEL",
        "PTE_LOG_FORMAT",
        "PTE_LLM_MAX_COST_PER_COMPANY_USD",
        "PTE_LLM_MAX_TOKENS_PER_REQUEST",
        "PTE_LLM_MODEL_JUDGMENT",
        "PTE_LLM_MODEL_ANALYSIS",
        "PTE_LLM_MODEL_CLASSIFICATION",
        "PTE_LLM_MODEL_EMBEDDINGS",
        "PTE_ENABLE_COST_TRACKING",
        "PTE_ENABLE_GUARDRAILS",
        "PTE_ENABLE_TELEMETRY",
        "PTE_SMOKE_HIT_REAL_APIS",
    ):
        monkeypatch.delenv(var, raising=False)


def _set_required_keys(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    monkeypatch.setenv("FMP_API_KEY", "fmp-test")


def test_loads_required_api_keys(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_keys(monkeypatch)
    s = Settings(_env_file=None)
    assert isinstance(s.anthropic_api_key, SecretStr)
    assert s.secret("anthropic_api_key") == "sk-ant-test"
    assert s.secret("openai_api_key") == "sk-openai-test"
    assert s.secret("fmp_api_key") == "fmp-test"


def test_missing_required_key_raises(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-openai-test")
    # FMP_API_KEY intentionally missing
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_defaults(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_keys(monkeypatch)
    s = Settings(_env_file=None)
    assert s.log_level == "INFO"
    assert s.log_format == "console"
    assert s.llm_model_analysis == "claude-sonnet-4-6"
    assert s.llm_model_judgment == "claude-opus-4-7"
    assert s.llm_max_cost_per_company_usd == 15.0
    assert s.enable_cost_tracking is True
    assert s.enable_telemetry is False
    assert s.smoke_hit_real_apis is False


def test_pte_prefix_overrides(
    clean_env: None, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _set_required_keys(monkeypatch)
    monkeypatch.setenv("PTE_LOG_LEVEL", "DEBUG")
    monkeypatch.setenv("PTE_LOG_FORMAT", "json")
    monkeypatch.setenv("PTE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("PTE_ENABLE_TELEMETRY", "true")
    s = Settings(_env_file=None)
    assert s.log_level == "DEBUG"
    assert s.log_format == "json"
    assert s.data_dir == tmp_path / "data"
    assert s.enable_telemetry is True


def test_invalid_log_level_rejected(clean_env: None, monkeypatch: pytest.MonkeyPatch) -> None:
    _set_required_keys(monkeypatch)
    monkeypatch.setenv("PTE_LOG_LEVEL", "TRACE")
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_secret_helper_returns_plain_string(
    clean_env: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    _set_required_keys(monkeypatch)
    s = Settings(_env_file=None)
    plain = s.secret("anthropic_api_key")
    assert isinstance(plain, str)
    assert plain == "sk-ant-test"
    # And secrets must not leak through repr / str
    assert "sk-ant-test" not in repr(s)
