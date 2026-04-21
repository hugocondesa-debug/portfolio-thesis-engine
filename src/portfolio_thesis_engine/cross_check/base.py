"""Cross-check dataclasses + status enum."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import StrEnum


class CrossCheckStatus(StrEnum):
    """Per-metric and overall cross-check outcomes.

    Precedence (worst → best): FAIL > SOURCES_DISAGREE > WARN > PASS.
    ``UNAVAILABLE`` is neutral — it doesn't raise the overall status
    because we can't cross-check a value we can't fetch.
    """

    PASS = "PASS"
    WARN = "WARN"
    FAIL = "FAIL"
    SOURCES_DISAGREE = "SOURCES_DISAGREE"
    UNAVAILABLE = "UNAVAILABLE"


@dataclass(frozen=True)
class CrossCheckMetric:
    """Single metric cross-check result.

    ``max_delta_pct`` is ``max(|ext − fmp|, |ext − yf|) / |ext|`` when
    both values are available; ``None`` when the extracted value or
    both external values are missing.
    """

    metric: str
    extracted_value: Decimal | None
    fmp_value: Decimal | None
    yfinance_value: Decimal | None
    max_delta_pct: Decimal | None
    status: CrossCheckStatus
    notes: str = ""


@dataclass
class CrossCheckReport:
    """Full cross-check result for one ticker."""

    ticker: str
    period: str
    metrics: list[CrossCheckMetric]
    overall_status: CrossCheckStatus
    blocking: bool
    generated_at: datetime
    log_path: str | None = None
    provider_errors: dict[str, str] = field(default_factory=dict)
