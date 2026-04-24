"""Pydantic response schemas for API endpoints.

Lightweight — most artefact endpoints return plain ``dict[str, Any]``
straight from the underlying YAML / JSON, so they don't need a
dedicated response model. Schemas in this module are reserved for the
endpoints whose shape stabilises early and benefits from OpenAPI
typing (health, ticker summary/detail, yaml metadata, pipeline run
lifecycle).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class HealthResponse(BaseModel):
    status: str = "ok"
    version: str
    timestamp: datetime


class TickerSummary(BaseModel):
    """One row of ``GET /api/tickers``."""

    ticker: str
    name: str
    profile: str
    currency: str
    exchange: str
    isin: str | None = None

    has_extraction: bool = False
    has_valuation: bool = False
    has_forecast: bool = False
    has_ficha: bool = False

    latest_extraction_at: datetime | None = None
    latest_valuation_at: datetime | None = None
    latest_forecast_at: datetime | None = None


class TickerDetail(BaseModel):
    """``GET /api/tickers/{ticker}``."""

    ticker: str
    name: str
    profile: str
    currency: str
    exchange: str
    isin: str | None = None

    extraction_path: str | None = None
    valuation_path: str | None = None
    forecast_path: str | None = None
    ficha_path: str | None = None


class YamlListItem(BaseModel):
    name: str
    filename: str
    last_modified: datetime
    size_bytes: int
    versions_count: int


class YamlUploadResult(BaseModel):
    success: bool
    validation_errors: list[dict[str, Any]] | None = None
    backup_path: str | None = None
    new_filename: str | None = None


class PipelineRunRequest(BaseModel):
    extraction_path: str | None = None
    base_period: str | None = None
    skip_cross_check: bool = False


class PipelineRunResponse(BaseModel):
    run_id: str
    ticker: str
    command: str
    status: str = "queued"
    started_at: datetime


class PipelineRunStatus(BaseModel):
    run_id: str
    ticker: str
    command: str
    status: str  # queued | running | done | failed | timeout
    started_at: datetime
    completed_at: datetime | None = None
    duration_seconds: float | None = None
    exit_code: int | None = None
    output_tail: str | None = None
