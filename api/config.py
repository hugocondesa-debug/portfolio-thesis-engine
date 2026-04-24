"""API configuration via environment variables.

Loads from ``api/.env`` if present; every value is overridable via
``PTE_API_*`` env vars. The container deployment passes credentials
through ``environment:`` in docker-compose.yml; local dev uses
``api/.env`` (gitignored).
"""

from __future__ import annotations

from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


class APISettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="PTE_API_",
        env_file=("api/.env", ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Auth (Basic) ---
    user: str = "hugo"
    password: str = "change-me"

    # --- Paths (defaults assume container layout) ---
    data_root: Path = Path("/data")

    # --- CORS ---
    # Tailscale: any 100.x.x.x is on the tailnet (regex enforced in main.py).
    # Localhost: dev frontend (Next.js default port 3000).
    allowed_origins: list[str] = [
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    ]
    allowed_tailscale_subnet: str = "100."

    # --- Pipeline subprocess ---
    pte_command: str = "uv run pte"
    pte_workdir: Path = Path("/workspace/portfolio-thesis-engine")
    pipeline_timeout_seconds: int = 1800  # 30-minute hard cap

    # --- Yaml versioning ---
    yaml_versions_keep: int = 10

    # --- Logging ---
    log_level: str = "INFO"


settings = APISettings()
