"""Phase 2 Sprint 3 — Damodaran reference data loader.

Loads the YAML snapshots in ``data/reference/damodaran/`` (country
risk premiums, industry unlevered betas, risk-free rates + inflation
by currency, synthetic-rating spread table, mature-market ERP) and
exposes them as typed accessors. The loader caches per instance so
one :class:`DamodaranReference` satisfies many WACC computations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

@dataclass
class _RatingBracket:
    rating: str
    min_coverage: Decimal
    spread: Decimal


# Reference YAML tables ship with the package (``src/.../reference/data``)
# rather than under ``data/`` which is gitignored for user-generated
# artefacts.
_DEFAULT_BASE_PATH = Path(__file__).resolve().parent / "data"


@dataclass
class DamodaranReference:
    """Static Damodaran reference data. Each field loads lazily on
    first access and caches the parsed YAML. Construct with a custom
    ``base_path`` in tests to inject fixture tables; production uses
    the packaged ``reference/data/`` directory."""

    base_path: Path = field(default_factory=lambda: _DEFAULT_BASE_PATH)
    _country_crp: dict[str, Decimal] | None = None
    _industry_betas: dict[str, Decimal] | None = None
    _rf_rates: dict[str, Decimal] | None = None
    _inflation_rates: dict[str, Decimal] | None = None
    _rating_brackets: list[_RatingBracket] | None = None
    _mature_market_erp: Decimal | None = None

    # ------------------------------------------------------------------
    # YAML I/O
    # ------------------------------------------------------------------
    def _load_yaml(self, name: str) -> dict[str, Any]:
        path = self.base_path / f"{name}.yaml"
        if not path.exists():
            raise FileNotFoundError(
                f"Damodaran reference table missing: {path}"
            )
        with path.open() as fh:
            return yaml.safe_load(fh) or {}

    # ------------------------------------------------------------------
    # Accessors
    # ------------------------------------------------------------------
    def country_crp(self, country: str) -> Decimal | None:
        """Return the country's equity risk premium (decimal fraction)
        above the mature-market ERP, or ``None`` when not tabulated."""
        if self._country_crp is None:
            payload = self._load_yaml("country_risk_premiums")
            self._country_crp = {
                k: Decimal(str(v)) for k, v in (payload.get("countries") or {}).items()
            }
        return self._country_crp.get(country)

    def industry_unlevered_beta(self, industry_key: str) -> Decimal | None:
        """Industry unlevered beta keyed by the same slug used in
        ``industry_betas.yaml`` (lowercase snake, e.g.
        ``healthcare_services``)."""
        if self._industry_betas is None:
            payload = self._load_yaml("industry_betas")
            self._industry_betas = {
                k: Decimal(str(v)) for k, v in (payload.get("industries") or {}).items()
            }
        return self._industry_betas.get(industry_key)

    def risk_free_rate(self, currency: str) -> Decimal | None:
        if self._rf_rates is None:
            payload = self._load_yaml("risk_free_rates_by_currency")
            self._rf_rates = {
                k: Decimal(str(v)) for k, v in (payload.get("risk_free_rates") or {}).items()
            }
        return self._rf_rates.get(currency)

    def inflation_rate(self, currency: str) -> Decimal | None:
        if self._inflation_rates is None:
            payload = self._load_yaml("risk_free_rates_by_currency")
            self._inflation_rates = {
                k: Decimal(str(v)) for k, v in (payload.get("inflation_rates") or {}).items()
            }
        return self._inflation_rates.get(currency)

    def mature_market_erp(self) -> Decimal:
        if self._mature_market_erp is None:
            payload = self._load_yaml("erp_by_market")
            raw = payload.get("mature_market_erp")
            if raw is None:
                raise ValueError("erp_by_market.yaml missing mature_market_erp")
            self._mature_market_erp = Decimal(str(raw))
        return self._mature_market_erp

    def synthetic_rating_for_coverage(
        self, coverage: Decimal
    ) -> tuple[str, Decimal]:
        """Return ``(rating, spread)`` for an interest-coverage ratio.
        Uses the table's ordered brackets (highest coverage first) —
        first bracket whose ``min_coverage`` is at most ``coverage``
        wins. Falls back to the lowest bracket when nothing matches."""
        if self._rating_brackets is None:
            payload = self._load_yaml("synthetic_ratings_table")
            self._rating_brackets = [
                _RatingBracket(
                    rating=str(b["rating"]),
                    min_coverage=Decimal(str(b["min_coverage"])),
                    spread=Decimal(str(b["spread"])),
                )
                for b in payload.get("brackets", [])
            ]
        for bracket in self._rating_brackets:
            if coverage >= bracket.min_coverage:
                return bracket.rating, bracket.spread
        last = self._rating_brackets[-1]
        return last.rating, last.spread


__all__ = ["DamodaranReference"]
