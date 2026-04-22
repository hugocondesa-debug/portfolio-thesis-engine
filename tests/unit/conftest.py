"""Shared fixtures for Phase 1.5.3 extraction-module unit tests."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from portfolio_thesis_engine.extraction.base import (
    ExtractionContext,
    parse_fiscal_period,
)
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.schemas.common import Currency, Profile
from portfolio_thesis_engine.schemas.raw_extraction import (
    DocumentType,
    ExtractionType,
    RawExtraction,
)
from portfolio_thesis_engine.schemas.wacc import (
    CapitalStructure,
    CostOfCapitalInputs,
    ScenarioDriversManual,
    WACCInputs,
)


@pytest.fixture
def cost_tracker(tmp_path: Path) -> CostTracker:
    return CostTracker(log_path=tmp_path / "costs.jsonl")


@pytest.fixture
def wacc_inputs() -> WACCInputs:
    return WACCInputs(
        ticker="TST",
        profile=Profile.P1_INDUSTRIAL,
        valuation_date="2024-12-31",
        current_price=Decimal("100"),
        cost_of_capital=CostOfCapitalInputs(
            risk_free_rate=Decimal("3"),
            equity_risk_premium=Decimal("5"),
            beta=Decimal("1"),
            cost_of_debt_pretax=Decimal("5"),
            tax_rate_for_wacc=Decimal("25"),
        ),
        capital_structure=CapitalStructure(
            debt_weight=Decimal("30"),
            equity_weight=Decimal("70"),
        ),
        scenarios={
            "base": ScenarioDriversManual(
                probability=Decimal("100"),
                revenue_cagr_explicit_period=Decimal("5"),
                terminal_growth=Decimal("2"),
                terminal_operating_margin=Decimal("18"),
            )
        },
    )


def build_raw(
    *,
    is_lines: list[dict] | None = None,
    bs_lines: list[dict] | None = None,
    cf_lines: list[dict] | None = None,
    notes: list[dict] | None = None,
    segments: list[dict] | None = None,
    historical: dict | None = None,
    operational_kpis: list[dict] | None = None,
    ticker: str = "TST",
    period: str = "FY2024",
    second_period: str | None = None,
    second_period_end: str | None = None,
    second_bs_lines: list[dict] | None = None,
) -> RawExtraction:
    """Build a minimal valid :class:`RawExtraction` for tests."""
    periods: list[dict] = [
        {"period": period, "end_date": "2024-12-31", "is_primary": True}
    ]
    if second_period is not None:
        periods.append(
            {
                "period": second_period,
                "end_date": second_period_end or "2023-12-31",
                "is_primary": False,
            }
        )
    default_is_lines: list[dict] = [
        {"order": 1, "label": "Revenue", "value": "1000"},
        {
            "order": 2, "label": "Profit for the year",
            "value": "100", "is_subtotal": True,
        },
    ]
    default_bs_lines: list[dict] = [
        {
            "order": 1, "label": "Total assets",
            "value": "1000", "section": "total_assets",
            "is_subtotal": True,
        },
    ]
    payload: dict[str, Any] = {
        "metadata": {
            "ticker": ticker,
            "company_name": "Test Co",
            "document_type": DocumentType.ANNUAL_REPORT,
            "extraction_type": ExtractionType.NUMERIC,
            "reporting_currency": Currency.USD,
            "unit_scale": "units",
            "extraction_date": "2025-01-01",
            "fiscal_periods": periods,
        },
        "income_statement": {
            period: {"line_items": is_lines if is_lines is not None else default_is_lines},
        },
        "balance_sheet": {
            period: {"line_items": bs_lines if bs_lines is not None else default_bs_lines},
        },
    }
    if second_period is not None and second_bs_lines is not None:
        payload["balance_sheet"][second_period] = {"line_items": second_bs_lines}
    if cf_lines is not None:
        payload["cash_flow"] = {period: {"line_items": cf_lines}}
    if notes is not None:
        payload["notes"] = notes
    if segments is not None:
        payload["segments"] = segments
    if historical is not None:
        payload["historical"] = historical
    if operational_kpis is not None:
        payload["operational_kpis"] = operational_kpis
    return RawExtraction.model_validate(payload)


def make_context(raw: RawExtraction, wacc: WACCInputs) -> ExtractionContext:
    return ExtractionContext(
        ticker=raw.metadata.ticker,
        fiscal_period_label=raw.primary_period.period,
        primary_period=parse_fiscal_period(raw.primary_period.period),
        raw_extraction=raw,
        wacc_inputs=wacc,
    )
