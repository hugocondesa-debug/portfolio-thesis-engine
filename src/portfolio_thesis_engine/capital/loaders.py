"""Phase 2 Sprint 3 — helpers that bridge canonical-state metadata +
analyst-curated YAML into :class:`WACCGeneratorInputs`.

Sprint 3 expects two analyst-authored files:

- ``data/yamls/companies/<ticker>/revenue_geography.yaml`` — revenue
  breakdown by country, feeds the CRP weighting.
- ``data/yamls/companies/<ticker>/industry.yaml`` — optional override
  for the Damodaran industry slug; otherwise a default mapping is used
  from the canonical identity's profile.

A future sprint will wire :class:`SegmentsBlock.by_geography` through
the canonical state so the geography file falls back to a default when
the raw extraction already carries the data.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import yaml

from portfolio_thesis_engine.capital.wacc_generator import (
    GeographyWeight,
    WACCGeneratorInputs,
)
from portfolio_thesis_engine.schemas.company import CanonicalCompanyState
from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.storage.base import normalise_ticker


def _ticker_dir(ticker: str) -> Path:
    return settings.data_dir / "yamls" / "companies" / normalise_ticker(ticker)


# Map analyst-friendly labels to Damodaran table keys. "Others" /
# "Other" / "ROW" are passed through as-is — the WACC generator treats
# unknown countries as CRP = 0 (mature-market proxy).
_COUNTRY_ALIASES = {
    "Hong_Kong": "HK",
    "Hong Kong": "HK",
    "HongKong": "HK",
    "Mainland_China": "PRC",
    "Mainland China": "PRC",
    "China": "PRC",  # already aliased in the YAML; keep here for safety
}


def _normalise_country(name: str) -> str:
    return _COUNTRY_ALIASES.get(name, name)


def load_revenue_geography(ticker: str) -> list[GeographyWeight]:
    """Read the curated geography file. Returns an empty list when
    absent (caller falls back to listing-country CRP).

    Two YAML schemas are accepted:

    1. **List form** — ``geography: [{country: X, weight: Y}, ...]``.
    2. **Dict form** — ``revenue_by_geography: {Country: weight, ...}``
       (matches the analyst-friendly conventions used in EuroEyes'
       input file).

    Country names are mapped through :data:`_COUNTRY_ALIASES` so
    analyst-friendly spellings (``Hong_Kong``, ``China``) resolve to
    the Damodaran table keys (``HK``, ``PRC``).
    """
    path = _ticker_dir(ticker) / "revenue_geography.yaml"
    if not path.exists():
        return []
    with path.open() as fh:
        payload = yaml.safe_load(fh) or {}
    out: list[GeographyWeight] = []
    # List form (Sprint 3 Part G original).
    for entry in payload.get("geography") or []:
        out.append(
            GeographyWeight(
                country=_normalise_country(str(entry["country"])),
                weight=Decimal(str(entry["weight"])),
            )
        )
    # Dict form (analyst convention).
    for country, weight in (payload.get("revenue_by_geography") or {}).items():
        out.append(
            GeographyWeight(
                country=_normalise_country(str(country)),
                weight=Decimal(str(weight)),
            )
        )
    return out


def load_industry_key(ticker: str, state: CanonicalCompanyState | None) -> str:
    """Resolve the Damodaran industry slug for ``ticker``. Preference
    order:

    1. ``data/yamls/companies/<ticker>/industry.yaml`` override.
    2. Profile-based default (e.g. P1 → ``industrial_machinery``,
       but here we just default to ``healthcare_services`` for the
       EuroEyes pilot; Sprint 4 can expand the profile mapping).
    """
    override = _ticker_dir(ticker) / "industry.yaml"
    if override.exists():
        with override.open() as fh:
            payload = yaml.safe_load(fh) or {}
        slug = payload.get("damodaran_industry_key")
        if slug:
            return str(slug)
    # Default — caller can override via the YAML when a different slug
    # fits better.
    return "healthcare_services"


def build_generator_inputs_from_state(
    ticker: str,
    state: CanonicalCompanyState | None,
    *,
    equity_market_value: Decimal | None = None,
    manual_wacc: Decimal | None = None,
    marginal_tax_rate: Decimal = Decimal("0.25"),
) -> WACCGeneratorInputs:
    """Compose :class:`WACCGeneratorInputs` from the canonical state +
    analyst YAML. When ``state`` is ``None`` callers must pass
    listing_currency + country_domicile upstream."""
    if state is None:
        raise ValueError("Canonical state required to infer listing_currency/country")
    listing_currency = state.identity.reporting_currency.value
    country_domicile = state.identity.country_domicile

    bridge = (
        state.analysis.nopat_bridge_by_period[0]
        if state.analysis.nopat_bridge_by_period
        else None
    )
    ic = (
        state.analysis.invested_capital_by_period[0]
        if state.analysis.invested_capital_by_period
        else None
    )

    ebit = bridge.operating_income if bridge is not None else None
    interest_expense = (
        -bridge.financial_expense if bridge is not None else None
    )
    debt_book = ic.bank_debt if ic is not None else Decimal("0")
    equity_claims = ic.equity_claims if ic is not None else Decimal("0")
    debt_to_equity = (
        debt_book / equity_claims
        if equity_claims and equity_claims != 0
        else Decimal("0")
    )

    return WACCGeneratorInputs(
        target_ticker=ticker,
        listing_currency=listing_currency,
        country_domicile=country_domicile,
        industry_key=load_industry_key(ticker, state),
        debt_to_equity=debt_to_equity,
        marginal_tax_rate=marginal_tax_rate,
        revenue_geography=load_revenue_geography(ticker),
        ebit=ebit,
        interest_expense=interest_expense,
        equity_market_value=equity_market_value,
        debt_book_value=debt_book,
        manual_wacc=manual_wacc,
    )


__all__ = [
    "build_generator_inputs_from_state",
    "load_industry_key",
    "load_revenue_geography",
]
