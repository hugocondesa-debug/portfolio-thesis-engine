"""Phase 2 Sprint 4A-alpha.2 — M10 Transaction Precedent engine.

Methodology: apply a user-specified (or database-sourced) transaction
multiple to a metric (TTM EBITDA typical), add a control premium,
treat the result as the immediate equity-realisable value (no PV
discount — the premise is "what a strategic / PE buyer would pay
today"). Thin on logic, deliberately so — the rigor lives in the
analyst's selection of multiple + premium.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from portfolio_thesis_engine.dcf.schemas import (
    DCFValuation,
    Scenario,
    TransactionPrecedentMethodologyConfig,
    ValuationMethodology,
)


class TransactionPrecedentEngine:
    """M10 — M&A precedent multiple with control premium."""

    def value(
        self,
        *,
        scenario: Scenario,
        methodology: TransactionPrecedentMethodologyConfig,
        base_drivers: dict[str, Any],
        period_inputs: Any,
        ttm_ebitda: Decimal | None = None,
    ) -> DCFValuation:
        multiple = methodology.multiple_value
        if multiple is None:
            # Sprint 4A-alpha.2 ships only USER_SPECIFIED; database
            # sourcing lands in a later sprint.
            multiple = Decimal("0")
        # Metric resolution — simplest: caller passes ttm_ebitda; else
        # derive from base drivers' current-margin × base-revenue.
        if ttm_ebitda is None:
            ttm_ebitda = _derive_ttm_ebitda_from_base(base_drivers)
        standalone_ev = ttm_ebitda * multiple
        premium_multiplier = Decimal("1") + methodology.control_premium
        enterprise_value = standalone_ev * premium_multiplier

        equity_value = (
            enterprise_value
            - period_inputs.net_debt
            + period_inputs.non_operating_assets
        )
        shares = (
            period_inputs.shares_outstanding
            if period_inputs.shares_outstanding != 0
            else Decimal("1")
        )
        fair_value_per_share = equity_value / shares

        summary = {
            "ttm_ebitda": ttm_ebitda,
            "multiple_source": methodology.multiple_source,
            "multiple_value": multiple,
            "standalone_enterprise_value": standalone_ev,
            "control_premium": methodology.control_premium,
            "enterprise_value_with_premium": enterprise_value,
        }

        return DCFValuation(
            ticker=period_inputs.ticker,
            scenario_name=scenario.name,
            scenario_probability=scenario.probability,
            methodology_used=ValuationMethodology.TRANSACTION_PRECEDENT,
            methodology_summary=summary,
            terminal_fcf=Decimal("0"),
            terminal_growth=Decimal("0"),
            terminal_wacc=Decimal("0"),
            terminal_value=enterprise_value,
            terminal_pv=enterprise_value,
            enterprise_value=enterprise_value,
            net_debt=period_inputs.net_debt,
            non_operating_assets=period_inputs.non_operating_assets,
            equity_value=equity_value,
            shares_outstanding=shares,
            fair_value_per_share=fair_value_per_share,
        )


def _derive_ttm_ebitda_from_base(base_drivers: dict[str, Any]) -> Decimal:
    """Approximate TTM EBITDA from the base year revenue × current
    operating margin × (1 + a D&A add-back factor). Analysts can
    refine by injecting a cleaner ``ttm_ebitda`` into the engine."""
    revenue_cfg = base_drivers.get("revenue", {})
    margin_cfg = base_drivers.get("operating_margin", {})
    depreciation_cfg = base_drivers.get("depreciation_rate", {})
    base_revenue = Decimal(str(revenue_cfg.get("base_year_value", 0)))
    margin = Decimal(str(margin_cfg.get("current", 0)))
    depreciation_rate = Decimal(str(depreciation_cfg.get("current", "0.08")))
    operating_income = base_revenue * margin
    # D&A proxy (mirrors DCFEngine): rate / 10 of revenue.
    da = base_revenue * (depreciation_rate / Decimal("10"))
    return operating_income + da


__all__ = ["TransactionPrecedentEngine"]
