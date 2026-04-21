"""Application configuration loaded from environment and .env file."""

from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings.

    Sources (highest precedence first): process environment, .env file, defaults.
    Secrets use :class:`SecretStr` to prevent accidental logging; retrieve the
    plain string via :meth:`secret`.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        env_prefix="PTE_",
        case_sensitive=False,
        extra="ignore",
    )

    anthropic_api_key: SecretStr = Field(..., alias="ANTHROPIC_API_KEY")
    openai_api_key: SecretStr = Field(..., alias="OPENAI_API_KEY")
    fmp_api_key: SecretStr = Field(..., alias="FMP_API_KEY")

    data_dir: Path = Field(default=Path.home() / "workspace" / "portfolio-thesis-engine" / "data")
    backup_dir: Path = Field(
        default=Path.home() / "workspace" / "portfolio-thesis-engine" / "backup"
    )

    llm_model_judgment: str = "claude-opus-4-7"
    llm_model_analysis: str = "claude-sonnet-4-6"
    llm_model_classification: str = "claude-haiku-4-5-20251001"
    llm_model_embeddings: str = "text-embedding-3-small"

    llm_max_cost_per_company_usd: float = 15.0
    llm_max_tokens_per_request: int = 200_000

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["json", "console"] = "console"

    enable_cost_tracking: bool = True
    enable_guardrails: bool = True
    enable_telemetry: bool = False

    smoke_hit_real_apis: bool = False

    def secret(self, name: str) -> str:
        """Return the plain value of a secret field by attribute name."""
        val = getattr(self, name)
        return val.get_secret_value() if isinstance(val, SecretStr) else val


settings = Settings()  # type: ignore[call-arg]  # values come from env / .env
