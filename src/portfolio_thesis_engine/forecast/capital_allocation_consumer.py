"""Phase 2 Sprint 4A-beta — capital_allocation.yaml consumer.

Parses ``data/yamls/companies/<ticker>/capital_allocation.yaml`` into
strongly-typed :class:`ParsedCapitalAllocation`. Missing file falls
through to :func:`default_policies` so the forecast orchestrator can
still run against tickers whose analyst package is incomplete.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from portfolio_thesis_engine.schemas.base import BaseSchema
from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.storage.base import normalise_ticker


class ParsedDividendPolicy(BaseSchema):
    type: str = "PAYOUT_RATIO"
    payout_ratio: Decimal | None = None
    fixed_amount: Decimal | None = None
    growth_rate: Decimal | None = None
    rationale: str = ""
    confidence: str = "MEDIUM"


class ParsedBuybackPolicy(BaseSchema):
    type: str = "NONE"
    annual_amount: Decimal = Decimal("0")
    condition: str | None = None
    rationale: str = ""
    confidence: str = "MEDIUM"


class ParsedDebtPolicy(BaseSchema):
    type: str = "MAINTAIN_CURRENT"
    current_debt: Decimal = Decimal("0")
    target_debt_to_ebitda: Decimal | None = None
    alternative_for_ma: dict[str, Any] | None = None
    rationale: str = ""
    confidence: str = "MEDIUM"


class ParsedMAPolicy(BaseSchema):
    type: str = "NONE"
    annual_deployment_target: Decimal = Decimal("0")
    funding_source: str = "CASH"
    geography_focus: list[str] = []
    rationale: str = ""
    confidence: str = "MEDIUM"


class ParsedShareIssuancePolicy(BaseSchema):
    type: str = "ZERO"
    annual_dilution_rate: Decimal = Decimal("0")
    rationale: str = ""
    confidence: str = "HIGH"


class ParsedCapitalAllocation(BaseSchema):
    ticker: str
    last_updated: str
    dividend_policy: ParsedDividendPolicy
    buyback_policy: ParsedBuybackPolicy
    debt_policy: ParsedDebtPolicy
    ma_policy: ParsedMAPolicy
    share_issuance_policy: ParsedShareIssuancePolicy
    net_cash_baseline: Decimal = Decimal("0")


def _dec(value: Any, default: Decimal | None = None) -> Decimal | None:
    """Coerce a YAML scalar (int, float, str, ``None``) to ``Decimal``."""
    if value is None:
        return default
    try:
        return Decimal(str(value))
    except Exception:
        return default


def _parse_dividend(block: dict[str, Any]) -> ParsedDividendPolicy:
    return ParsedDividendPolicy(
        type=str(block.get("type", "PAYOUT_RATIO")),
        payout_ratio=_dec(block.get("payout_ratio")),
        fixed_amount=_dec(block.get("fixed_amount")),
        growth_rate=_dec(block.get("growth_rate")),
        rationale=str(block.get("rationale", "")),
        confidence=str(block.get("confidence", "MEDIUM")),
    )


def _parse_buyback(block: dict[str, Any]) -> ParsedBuybackPolicy:
    annual = (
        block.get("annual_amount_if_condition_met")
        or block.get("annual_amount")
        or 0
    )
    return ParsedBuybackPolicy(
        type=str(block.get("type", "NONE")),
        annual_amount=_dec(annual, Decimal("0")) or Decimal("0"),
        condition=(
            str(block["condition"]) if block.get("condition") is not None else None
        ),
        rationale=str(block.get("rationale", "")),
        confidence=str(block.get("confidence", "MEDIUM")),
    )


def _parse_debt(block: dict[str, Any]) -> ParsedDebtPolicy:
    return ParsedDebtPolicy(
        type=str(block.get("type", "MAINTAIN_CURRENT")),
        current_debt=_dec(block.get("current_debt"), Decimal("0"))
        or Decimal("0"),
        target_debt_to_ebitda=_dec(block.get("target_debt_to_ebitda")),
        alternative_for_ma=block.get("alternative_for_ma"),
        rationale=str(block.get("rationale", "")),
        confidence=str(block.get("confidence", "MEDIUM")),
    )


def _parse_ma(block: dict[str, Any]) -> ParsedMAPolicy:
    return ParsedMAPolicy(
        type=str(block.get("type", "NONE")),
        annual_deployment_target=_dec(
            block.get("annual_deployment_target"), Decimal("0")
        ) or Decimal("0"),
        funding_source=str(block.get("funding_source", "CASH")),
        geography_focus=list(block.get("geography_focus", []) or []),
        rationale=str(block.get("rationale", "")),
        confidence=str(block.get("confidence", "MEDIUM")),
    )


def _parse_share_issuance(block: dict[str, Any]) -> ParsedShareIssuancePolicy:
    return ParsedShareIssuancePolicy(
        type=str(block.get("type", "ZERO")),
        annual_dilution_rate=_dec(
            block.get("annual_dilution_rate"), Decimal("0")
        ) or Decimal("0"),
        rationale=str(block.get("rationale", "")),
        confidence=str(block.get("confidence", "HIGH")),
    )


def _extract_net_cash_baseline(payload: dict[str, Any]) -> Decimal:
    """Pull the most recent ``net_cash`` entry from
    ``historical_context.cash_evolution``; fall back to zero when absent."""
    hc = payload.get("historical_context") or {}
    evolution = hc.get("cash_evolution") or []
    if not evolution:
        return Decimal("0")
    last = evolution[-1]
    if not isinstance(last, dict):
        return Decimal("0")
    return _dec(last.get("net_cash"), Decimal("0")) or Decimal("0")


def _yaml_path(ticker: str) -> Path:
    return (
        settings.data_dir
        / "yamls"
        / "companies"
        / normalise_ticker(ticker)
        / "capital_allocation.yaml"
    )


def load_capital_allocation(ticker: str) -> ParsedCapitalAllocation | None:
    """Load capital_allocation.yaml for ticker.

    Returns ``None`` when the file is absent so callers can fall back
    to :func:`default_policies`.
    """
    path = _yaml_path(ticker)
    if not path.exists():
        return None

    with path.open() as fh:
        payload = yaml.safe_load(fh) or {}

    policies = payload.get("policies", {}) or {}

    return ParsedCapitalAllocation(
        ticker=str(payload.get("target_ticker", ticker)),
        last_updated=str(payload.get("last_updated", "")),
        dividend_policy=_parse_dividend(policies.get("dividend_policy", {}) or {}),
        buyback_policy=_parse_buyback(policies.get("buyback_policy", {}) or {}),
        debt_policy=_parse_debt(policies.get("debt_policy", {}) or {}),
        ma_policy=_parse_ma(policies.get("ma_policy", {}) or {}),
        share_issuance_policy=_parse_share_issuance(
            policies.get("share_issuance_policy", {}) or {}
        ),
        net_cash_baseline=_extract_net_cash_baseline(payload),
    )


def default_policies() -> ParsedCapitalAllocation:
    """Fallback policy pack — used when no ``capital_allocation.yaml`` exists."""
    return ParsedCapitalAllocation(
        ticker="DEFAULT",
        last_updated="",
        dividend_policy=ParsedDividendPolicy(
            type="PAYOUT_RATIO", payout_ratio=Decimal("0.30")
        ),
        buyback_policy=ParsedBuybackPolicy(
            type="NONE", annual_amount=Decimal("0")
        ),
        debt_policy=ParsedDebtPolicy(
            type="MAINTAIN_CURRENT", current_debt=Decimal("0")
        ),
        ma_policy=ParsedMAPolicy(
            type="NONE", annual_deployment_target=Decimal("0")
        ),
        share_issuance_policy=ParsedShareIssuancePolicy(
            type="ZERO", annual_dilution_rate=Decimal("0")
        ),
    )


__all__ = [
    "ParsedBuybackPolicy",
    "ParsedCapitalAllocation",
    "ParsedDebtPolicy",
    "ParsedDividendPolicy",
    "ParsedMAPolicy",
    "ParsedShareIssuancePolicy",
    "default_policies",
    "load_capital_allocation",
]
