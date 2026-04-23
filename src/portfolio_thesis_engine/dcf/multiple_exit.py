"""Phase 2 Sprint 4A-alpha.2 — M3 Multiple Exit engine.

Methodology: project a key metric (forward EBITDA typically) to
``metric_year``, apply a target multiple sourced from peers / industry
/ user, adjust via ``multiple_multiplier``, treat the product as an
exit enterprise value, and discount back to present at WACC. Equity
bridge via net debt, per-share via shares outstanding.

Intended as a complementary view to the DCF 3-stage: useful when the
analyst's thesis rests on a re-rating narrative rather than
fundamental cash-flow compounding.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from portfolio_thesis_engine.dcf.schemas import (
    DCFStageProjection,
    DCFValuation,
    MultipleExitMethodologyConfig,
    Scenario,
    ScenarioDriverOverride,
    ValuationMethodology,
)


class MultipleExitEngine:
    """M3 — forward-multiple exit valuation."""

    def value(
        self,
        *,
        scenario: Scenario,
        methodology: MultipleExitMethodologyConfig,
        base_drivers: dict[str, Any],
        period_inputs: Any,
        peer_comparison: Any | None = None,
    ) -> DCFValuation:
        # Project revenue + margin forward to metric_year.
        projections = _project_to_exit(
            base_drivers=base_drivers,
            scenario=scenario,
            metric_year=methodology.metric_year,
            stage_1_wacc=period_inputs.stage_1_wacc,
        )
        forward_ebitda = _forward_ebitda(projections, methodology)

        target_multiple = self._resolve_multiple(
            methodology=methodology,
            peer_comparison=peer_comparison,
        )
        if target_multiple is None:
            # Fallback: industry median from valuation_profile if caller
            # supplied it via period_inputs; else zero → FV 0 (clearly
            # degenerate, surfaced via warning caller-side).
            target_multiple = period_inputs.industry_median_ev_ebitda or Decimal("0")
        adjusted_multiple = target_multiple * methodology.multiple_multiplier

        exit_enterprise_value = forward_ebitda * adjusted_multiple
        discount_rate = (
            methodology.discount_rate_override
            if methodology.discount_rate_source == "USER_SPECIFIED"
            and methodology.discount_rate_override is not None
            else period_inputs.stage_1_wacc
        )
        years = max(methodology.metric_year, 0)
        discount_factor = (Decimal("1") + discount_rate) ** years if years > 0 else Decimal("1")
        exit_pv = (
            exit_enterprise_value / discount_factor
            if discount_factor != 0
            else exit_enterprise_value
        )

        equity_value = (
            exit_pv - period_inputs.net_debt + period_inputs.non_operating_assets
        )
        shares = (
            period_inputs.shares_outstanding
            if period_inputs.shares_outstanding != 0
            else Decimal("1")
        )
        fair_value_per_share = equity_value / shares

        summary = {
            "forward_year": years,
            "forward_ebitda": forward_ebitda,
            "target_multiple": target_multiple,
            "multiple_multiplier": methodology.multiple_multiplier,
            "adjusted_multiple": adjusted_multiple,
            "exit_enterprise_value": exit_enterprise_value,
            "discount_rate": discount_rate,
            "exit_pv": exit_pv,
            "multiple_source": methodology.multiple_source,
        }

        return DCFValuation(
            ticker=period_inputs.ticker,
            scenario_name=scenario.name,
            scenario_probability=scenario.probability,
            methodology_used=ValuationMethodology.MULTIPLE_EXIT,
            methodology_summary=summary,
            explicit_projections=projections,
            fade_projections=[],
            terminal_fcf=Decimal("0"),
            terminal_growth=Decimal("0"),
            terminal_wacc=discount_rate,
            terminal_value=exit_enterprise_value,
            terminal_pv=exit_pv,
            enterprise_value=exit_pv,
            net_debt=period_inputs.net_debt,
            non_operating_assets=period_inputs.non_operating_assets,
            equity_value=equity_value,
            shares_outstanding=shares,
            fair_value_per_share=fair_value_per_share,
        )

    # ------------------------------------------------------------------
    def _resolve_multiple(
        self,
        *,
        methodology: MultipleExitMethodologyConfig,
        peer_comparison: Any | None,
    ) -> Decimal | None:
        source = methodology.multiple_source
        if source == "USER_SPECIFIED":
            return methodology.multiple_value
        if source == "PEER_MEDIAN":
            if peer_comparison is None:
                return None
            median = peer_comparison.peer_median.get("ev_to_ebitda")
            return median
        if source == "INDUSTRY_MEDIAN":
            # Caller is responsible for passing industry_median via the
            # period_inputs fallback path.
            return None
        if source == "HISTORICAL_OWN":
            # Historical own-company multiple — Sprint 4B can wire this
            # from the analytical layer's trend data.
            return None
        return None


def _project_to_exit(
    *,
    base_drivers: dict[str, Any],
    scenario: Scenario,
    metric_year: int,
    stage_1_wacc: Decimal,
) -> list[DCFStageProjection]:
    """Project revenue + margin + EBITDA forward ``metric_year`` steps.

    Uses the same base_drivers + scenario.driver_overrides semantics
    as the DCF engine — reuses the override-merge logic by duplicating
    the critical fields here instead of importing from ``p1_engine``
    to avoid a circular dep.
    """
    merged = _merge_overrides(base_drivers, scenario)
    revenue_cfg = merged.get("revenue", {})
    margin_cfg = merged.get("operating_margin", {})
    depreciation_cfg = merged.get("depreciation_rate", {})

    base_revenue = Decimal(str(revenue_cfg.get("base_year_value", 0)))
    growth_pattern = [
        Decimal(str(g)) for g in (revenue_cfg.get("growth_pattern") or [])
    ]
    margin_current = Decimal(str(margin_cfg.get("current", 0)))
    margin_terminal = Decimal(str(margin_cfg.get("target_terminal", margin_current)))
    depreciation_rate = Decimal(str(depreciation_cfg.get("current", "0.08")))

    projections: list[DCFStageProjection] = []
    prior_revenue = base_revenue
    for year in range(1, max(metric_year, 1) + 1):
        growth = (
            growth_pattern[year - 1]
            if len(growth_pattern) >= year
            else Decimal(str(base_drivers.get("revenue", {}).get("terminal_growth", "0.025")))
        )
        revenue = prior_revenue * (Decimal("1") + growth)
        total_years = max(metric_year, 1)
        fraction = Decimal(year) / Decimal(total_years)
        margin = margin_current + (margin_terminal - margin_current) * fraction
        operating_income = revenue * margin
        depreciation = revenue * (depreciation_rate / Decimal("10"))
        projections.append(
            DCFStageProjection(
                year=year,
                revenue=revenue,
                operating_margin=margin,
                operating_income=operating_income,
                tax_rate=Decimal("0"),
                nopat=operating_income,
                capex=Decimal("0"),
                depreciation=depreciation,
                wc_change=Decimal("0"),
                fcf=operating_income + depreciation,
                wacc_applied=stage_1_wacc,
                discount_factor=Decimal("1"),
                pv=Decimal("0"),
            )
        )
        prior_revenue = revenue
    return projections


def _forward_ebitda(
    projections: list[DCFStageProjection],
    methodology: MultipleExitMethodologyConfig,
) -> Decimal:
    if not projections:
        return Decimal("0")
    year_idx = methodology.metric_year
    if year_idx <= 0 or year_idx > len(projections):
        # CURRENT / TTM_EBITDA → use year 1 as the most forward signal
        # we have; year 0 is the base year and would require caller
        # input that's out of scope here.
        proj = projections[0]
    else:
        proj = projections[year_idx - 1]
    return proj.operating_income + proj.depreciation


def _merge_overrides(
    base: dict[str, Any], scenario: Scenario
) -> dict[str, Any]:
    merged: dict[str, Any] = {
        k: dict(v) if isinstance(v, dict) else v for k, v in base.items()
    }
    for driver_name, override in scenario.driver_overrides.items():
        if not isinstance(override, ScenarioDriverOverride):
            continue
        current = merged.setdefault(driver_name, {})
        if override.current is not None:
            current["current"] = override.current
        if override.target_terminal is not None:
            current["target_terminal"] = override.target_terminal
        if override.growth_pattern is not None:
            current["growth_pattern"] = list(override.growth_pattern)
        merged[driver_name] = current
    return merged


__all__ = ["MultipleExitEngine"]
