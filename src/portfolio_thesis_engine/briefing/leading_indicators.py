"""Phase 2 Sprint 4A-alpha.5 Part B — leading indicators framework.

Schemas + loader + sector-default catalogue suggestions. FRED live
fetch is stubbed (returns ``None`` when no API key is configured) —
analysts author values in the per-ticker YAML file for now.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from portfolio_thesis_engine.schemas.base import BaseSchema
from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.storage.base import normalise_ticker


_CategoryType = Literal[
    "CURRENCY",
    "MACRO",
    "LABOR_COSTS",
    "COMMODITY",
    "RATES",
    "DEMAND",
    "SUPPLY",
    "REGULATORY",
    "OTHER",
]
_DataSourceType = Literal[
    "FRED", "MANUAL", "FMP", "EODHD", "INDUSTRY_REPORT"
]
_SensitivityType = Literal[
    "LINEAR_WITHIN_RANGE", "LINEAR", "QUALITATIVE", "NONLINEAR"
]
_Trend = Literal[
    "STABLE",
    "EXPANDING",
    "DETERIORATING_SLIGHTLY",
    "DETERIORATING_SHARPLY",
    "IMPROVING",
]
_Volatility = Literal["LOW", "MODERATE", "HIGH"]
_Direction = Literal["NEUTRAL", "WARNING", "HEADWIND", "TAILWIND"]
_Confidence = Literal["HIGH", "MEDIUM", "LOW"]


class IndicatorDataSource(BaseSchema):
    type: _DataSourceType
    series_id: str | None = None
    fallback: Literal["MANUAL", "NONE"] = "MANUAL"


class IndicatorSensitivity(BaseSchema):
    type: _SensitivityType = "QUALITATIVE"
    range: tuple[Decimal, Decimal] | None = None
    elasticity: str | None = None
    absolute_impact_per_percent: str | None = None
    interpretation: str | None = None


class IndicatorEnvironment(BaseSchema):
    trend: _Trend = "STABLE"
    recent_volatility: _Volatility = "MODERATE"
    direction: _Direction = "NEUTRAL"
    data_date: date | None = None


class LeadingIndicator(BaseSchema):
    name: str
    category: _CategoryType
    relevance: list[str] = Field(default_factory=list)
    data_source: IndicatorDataSource
    current_value: Decimal | None = None
    historical_correlation: dict[str, Decimal] | None = None
    correlation_lag_months: int | None = None
    sensitivity: IndicatorSensitivity = Field(default_factory=IndicatorSensitivity)
    current_environment: IndicatorEnvironment | None = None
    scenario_relevance: list[str] = Field(default_factory=list)
    source_evidence: list[int] = Field(default_factory=list)
    confidence: _Confidence = "MEDIUM"


class LeadingIndicatorsSet(BaseSchema):
    target_ticker: str
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sector_taxonomy: str = ""
    indicators: list[LeadingIndicator] = Field(default_factory=list)
    source_documents_referenced: list[str] = Field(default_factory=list)
    sector_default_suggestions: list[str] = Field(default_factory=list)


# ----------------------------------------------------------------------
# Loader + catalogue
# ----------------------------------------------------------------------
_CATALOGUE_PATH = (
    Path(__file__).resolve().parent.parent
    / "reference"
    / "data"
    / "leading_indicators_catalogue.yaml"
)


class LeadingIndicatorsLoader:
    """Load per-ticker ``leading_indicators.yaml`` + sector catalogue
    for default suggestions."""

    def __init__(self, catalogue_path: Path | None = None) -> None:
        self._catalogue_path = catalogue_path or _CATALOGUE_PATH
        self._catalogue_cache: dict[str, list[dict[str, object]]] | None = None

    # ------------------------------------------------------------------
    def load_company(self, ticker: str) -> LeadingIndicatorsSet | None:
        path = (
            settings.data_dir
            / "yamls"
            / "companies"
            / normalise_ticker(ticker)
            / "leading_indicators.yaml"
        )
        if not path.exists():
            return None
        with path.open() as fh:
            payload = yaml.safe_load(fh) or {}
        return LeadingIndicatorsSet.model_validate(payload)

    def _load_catalogue(self) -> dict[str, list[dict[str, object]]]:
        if self._catalogue_cache is not None:
            return self._catalogue_cache
        if not self._catalogue_path.exists():
            self._catalogue_cache = {}
            return self._catalogue_cache
        with self._catalogue_path.open() as fh:
            payload = yaml.safe_load(fh) or {}
        # Strip the ``vintage`` key — not a sector entry.
        self._catalogue_cache = {
            k: v for k, v in payload.items() if k != "vintage"
        }
        return self._catalogue_cache

    def load_sector_defaults(self, sector: str) -> list[str]:
        """Return indicator names tagged as the sector's suggested set."""
        catalogue = self._load_catalogue()
        entries = catalogue.get(sector) or []
        return [entry["name"] for entry in entries if "name" in entry]

    def suggest_missing(
        self, company_set: LeadingIndicatorsSet | None, sector: str
    ) -> list[str]:
        """Indicator names from the sector catalogue that aren't yet
        in the company's leading_indicators.yaml."""
        defaults = set(self.load_sector_defaults(sector))
        if company_set is None:
            return sorted(defaults)
        existing = {i.name for i in company_set.indicators}
        return sorted(defaults - existing)


# ----------------------------------------------------------------------
# FRED stub
# ----------------------------------------------------------------------
def fetch_fred_latest(series_id: str) -> Decimal | None:
    """Stub FRED fetcher. Returns ``None`` when no API key is present
    (analyst fills via MANUAL in the YAML). Full wire-up lands when
    the monitoring sprint needs live macro data."""
    import os

    api_key = os.environ.get("FRED_API_KEY")
    if not api_key:
        return None
    # Placeholder — do NOT hit the network in tests. Real
    # implementation would urllib.request with proper timeout handling.
    _ = series_id
    return None


__all__ = [
    "IndicatorDataSource",
    "IndicatorEnvironment",
    "IndicatorSensitivity",
    "LeadingIndicator",
    "LeadingIndicatorsLoader",
    "LeadingIndicatorsSet",
    "fetch_fred_latest",
]
