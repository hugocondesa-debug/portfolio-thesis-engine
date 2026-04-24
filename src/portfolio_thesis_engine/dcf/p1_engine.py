"""Phase 2 Sprint 4A-alpha Part C — P1 three-stage DCF engine.

Stages:

1. **Explicit** (years 1-N, typically 5). Revenue compounds from the
   base-year value using ``base_drivers.revenue.growth_pattern``;
   operating margin fades linearly toward ``target_terminal``; capex
   and working-capital intensity follow the analyst's fade pattern.
2. **Fade** (next M years, typically 5). Drivers converge linearly
   toward their terminal values; WACC transitions from the Sprint-3
   auto WACC toward the "mature" WACC the profile specifies.
3. **Terminal** (Gordon growth). ``TV = FCF_{N+M+1} / (WACC_term −
   g_term)``, with a cross-check against the industry median EV/EBITDA
   multiple.

All arithmetic is :mod:`decimal`. Scenarios overlay on the base
drivers sparsely — only fields the analyst wants to override.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from portfolio_thesis_engine.dcf.schemas import (
    DCFMethodologyConfig,
    DCFProfile,
    DCFStageProjection,
    DCFValuation,
    DCFValuationResult,
    ForecastWarning,
    Scenario,
    ScenarioDriverOverride,
    ScenarioSet,
    TerminalMethod,
    TerminalMultipleValidation,
    ValuationProfile,
)


_HUNDRED = Decimal("100")


@dataclass
class PeriodInputs:
    """Non-scenario contextual inputs needed by the engine.

    Sprint 4B additions (``cost_of_equity``, ``equity_claims``) support
    DDM and Residual Income dispatch — the orchestrator pulls the CoE
    out of the Sprint-3 :class:`WACCGenerator` result and the book-value
    anchor out of the canonical state's ``InvestedCapital.equity_claims``.
    Both default to ``None`` so existing DCF / multiple-exit paths need
    no wiring changes.
    """

    ticker: str
    stage_1_wacc: Decimal
    stage_3_wacc: Decimal
    net_debt: Decimal = Decimal("0")
    non_operating_assets: Decimal = Decimal("0")
    shares_outstanding: Decimal = Decimal("1")
    market_price: Decimal | None = None
    industry_median_ev_ebitda: Decimal | None = None
    cost_of_equity: Decimal | None = None
    equity_claims: Decimal | None = None


def _resolve_base_drivers(scenario_set: ScenarioSet) -> dict[str, Any]:
    """Return the base drivers block cast to Decimal where needed."""

    def _to_decimal(value: Any) -> Any:
        if isinstance(value, (int, float, str)):
            try:
                return Decimal(str(value))
            except Exception:
                return value
        if isinstance(value, list):
            return [_to_decimal(v) for v in value]
        if isinstance(value, dict):
            return {k: _to_decimal(v) for k, v in value.items()}
        return value

    return _to_decimal(dict(scenario_set.base_drivers))


def _merge_scenario_overrides(
    base: dict[str, Any], scenario: Scenario
) -> dict[str, Any]:
    """Overlay ``scenario.driver_overrides`` on top of ``base``. Sparse
    overrides (e.g. ``scenario.driver_overrides.operating_margin.target_terminal``)
    only replace the specific field, preserving the rest of the base."""
    merged: dict[str, Any] = {k: dict(v) if isinstance(v, dict) else v for k, v in base.items()}
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
        if override.fade_pattern is not None:
            current["fade_pattern"] = override.fade_pattern
        merged[driver_name] = current
    return merged


def _interpolate_linear(
    start: Decimal, end: Decimal, step: int, total_steps: int
) -> Decimal:
    """Linear interpolation from ``start`` at step 0 to ``end`` at
    ``total_steps``. Step ``step`` (1-indexed) is clamped to bounds."""
    if total_steps <= 0:
        return end
    fraction = Decimal(min(max(step, 0), total_steps)) / Decimal(total_steps)
    return start + (end - start) * fraction


def _wacc_for_year(
    year_idx: int,
    explicit_years: int,
    fade_years: int,
    stage_1_wacc: Decimal,
    stage_3_wacc: Decimal,
) -> Decimal:
    """Explicit stage stays at stage-1 WACC; fade stage linearly
    transitions to stage-3; terminal uses stage-3."""
    if year_idx <= explicit_years:
        return stage_1_wacc
    fade_step = year_idx - explicit_years
    return _interpolate_linear(stage_1_wacc, stage_3_wacc, fade_step, fade_years)


def _growth_for_year(
    year_idx: int,
    explicit_years: int,
    fade_years: int,
    growth_pattern: list[Decimal],
    terminal_growth: Decimal,
) -> Decimal:
    """Explicit stage uses growth_pattern[i-1]; fade stage linearly
    interpolates from last explicit growth to terminal_growth."""
    if year_idx <= explicit_years and len(growth_pattern) >= year_idx:
        return growth_pattern[year_idx - 1]
    # Fade stage: start from last explicit growth.
    last_explicit_growth = (
        growth_pattern[explicit_years - 1]
        if len(growth_pattern) >= explicit_years
        else terminal_growth
    )
    fade_step = year_idx - explicit_years
    return _interpolate_linear(
        last_explicit_growth, terminal_growth, fade_step, fade_years
    )


class P1DCFEngine:
    """3-stage DCF for P1 (industrial / services) profiles."""

    def run(
        self,
        *,
        valuation_profile: ValuationProfile,
        scenario_set: ScenarioSet,
        period_inputs: PeriodInputs,
    ) -> DCFValuationResult:
        if valuation_profile.profile.code != DCFProfile.P1_INDUSTRIAL_SERVICES:
            raise NotImplementedError(
                f"DCF profile {valuation_profile.profile.code} is planned "
                "for Sprint 4A-beta / 4B / 4C. Only P1 is implemented in "
                "Sprint 4A-alpha."
            )

        base = _resolve_base_drivers(scenario_set)
        warnings: list[ForecastWarning] = []
        scenario_valuations: list[DCFValuation] = []
        for scenario in scenario_set.scenarios:
            drivers = _merge_scenario_overrides(base, scenario)
            valuation, scenario_warnings = self._run_scenario(
                scenario=scenario,
                drivers=drivers,
                valuation_profile=valuation_profile,
                period_inputs=period_inputs,
            )
            warnings.extend(scenario_warnings)
            scenario_valuations.append(valuation)

        expected = _probability_weighted_expected_value(scenario_valuations)
        p25, p75 = _percentile_values(scenario_valuations)
        upside = None
        if period_inputs.market_price and period_inputs.market_price != 0 and expected is not None:
            upside = (
                (expected / period_inputs.market_price - Decimal("1")) * _HUNDRED
            )

        return DCFValuationResult(
            ticker=period_inputs.ticker,
            valuation_profile=valuation_profile.profile.code,
            scenarios_run=scenario_valuations,
            warnings=warnings,
            expected_value_per_share=expected,
            market_price=period_inputs.market_price,
            implied_upside_downside_pct=upside,
            p25_value_per_share=p25,
            p75_value_per_share=p75,
            stage_1_wacc=period_inputs.stage_1_wacc,
            stage_3_wacc=period_inputs.stage_3_wacc,
        )

    # ------------------------------------------------------------------
    def _run_scenario(
        self,
        *,
        scenario: Scenario,
        drivers: dict[str, Any],
        valuation_profile: ValuationProfile,
        period_inputs: PeriodInputs,
        peer_comparison: Any | None = None,
    ) -> tuple[DCFValuation, list[ForecastWarning]]:
        structure = valuation_profile.dcf_structure
        explicit_years = structure.explicit_years
        fade_years = structure.fade_years
        total_years = explicit_years + fade_years

        revenue_cfg = drivers.get("revenue", {})
        margin_cfg = drivers.get("operating_margin", {})
        tax_cfg = drivers.get("tax_rate", {})
        capex_cfg = drivers.get("capex_intensity", {})
        wc_cfg = drivers.get("working_capital_intensity", {})
        depreciation_cfg = drivers.get("depreciation_rate", {})

        base_revenue = Decimal(str(revenue_cfg.get("base_year_value", 0)))
        growth_pattern = [
            Decimal(str(g)) for g in (revenue_cfg.get("growth_pattern") or [])
        ]
        terminal_growth = Decimal(
            str(revenue_cfg.get("terminal_growth", valuation_profile.terminal_value.growth_rate))
        )

        margin_current = Decimal(str(margin_cfg.get("current", 0)))
        margin_terminal = Decimal(
            str(margin_cfg.get("target_terminal", margin_current))
        )

        tax_rate = Decimal(str(tax_cfg.get("statutory", "0.25")))

        capex_current = Decimal(str(capex_cfg.get("current", 0)))
        capex_terminal = Decimal(
            str(capex_cfg.get("target", capex_current))
        )

        wc_current = Decimal(str(wc_cfg.get("current", 0)))
        wc_terminal = Decimal(str(wc_cfg.get("target", wc_current)))

        depreciation_rate = Decimal(str(depreciation_cfg.get("current", "0.08")))

        # Project year by year.
        prior_revenue = base_revenue
        explicit_projs: list[DCFStageProjection] = []
        fade_projs: list[DCFStageProjection] = []
        discount_factor_cumulative = Decimal("1")

        for year_idx in range(1, total_years + 1):
            growth = _growth_for_year(
                year_idx, explicit_years, fade_years, growth_pattern, terminal_growth
            )
            revenue = prior_revenue * (Decimal("1") + growth)
            margin = _interpolate_linear(
                margin_current, margin_terminal, year_idx, total_years
            )
            operating_income = revenue * margin
            nopat = operating_income * (Decimal("1") - tax_rate)

            capex_intensity = _interpolate_linear(
                capex_current, capex_terminal, year_idx, total_years
            )
            capex = revenue * capex_intensity

            wc_intensity_year = _interpolate_linear(
                wc_current, wc_terminal, year_idx, total_years
            )
            wc_intensity_prior = _interpolate_linear(
                wc_current, wc_terminal, year_idx - 1, total_years
            )
            wc_change = (
                revenue * wc_intensity_year - prior_revenue * wc_intensity_prior
            )

            # Depreciation approximation — Sprint 4A-alpha uses a
            # simple ratio against revenue (analyst supplies D&A / PPE
            # as ``depreciation_rate`` and we translate to D&A /
            # Revenue using a conservative PPE-to-revenue multiple of
            # ~10 typical for services). Sprint 4A-beta replaces this
            # with a proper PPE rollforward driven by the capex
            # schedule.
            depreciation = revenue * (depreciation_rate / Decimal("10"))

            fcf = nopat + depreciation - capex - wc_change

            wacc_applied = _wacc_for_year(
                year_idx,
                explicit_years,
                fade_years,
                period_inputs.stage_1_wacc,
                period_inputs.stage_3_wacc,
            )
            discount_factor_cumulative *= Decimal("1") + wacc_applied
            pv = fcf / discount_factor_cumulative

            projection = DCFStageProjection(
                year=year_idx,
                revenue=revenue,
                operating_margin=margin,
                operating_income=operating_income,
                tax_rate=tax_rate,
                nopat=nopat,
                capex=capex,
                depreciation=depreciation,
                wc_change=wc_change,
                fcf=fcf,
                wacc_applied=wacc_applied,
                discount_factor=discount_factor_cumulative,
                pv=pv,
            )
            if year_idx <= explicit_years:
                explicit_projs.append(projection)
            else:
                fade_projs.append(projection)

            prior_revenue = revenue

        # Terminal value — Sprint 4A-alpha.3 branches on
        # ``methodology.terminal_method``. Default (no methodology or
        # GORDON_GROWTH) keeps the Sprint-4A-alpha Gordon formulation.
        terminal_proj = fade_projs[-1] if fade_projs else explicit_projs[-1]
        terminal_fcf = terminal_proj.fcf
        terminal_wacc = period_inputs.stage_3_wacc
        terminal_growth_used = terminal_growth
        scenario_warnings: list[ForecastWarning] = []
        methodology_cfg = (
            scenario.methodology
            if isinstance(scenario.methodology, DCFMethodologyConfig)
            else None
        )
        if (
            methodology_cfg is not None
            and methodology_cfg.terminal_method == TerminalMethod.TERMINAL_MULTIPLE
        ):
            terminal_value, tm_summary, tm_warnings = self._terminal_value_from_multiple(
                scenario=scenario,
                methodology=methodology_cfg,
                terminal_proj=terminal_proj,
                terminal_wacc=terminal_wacc,
                period_inputs=period_inputs,
                peer_comparison=peer_comparison,
            )
            scenario_warnings.extend(tm_warnings)
            # Gordon-implied g implied by the multiple-derived TV —
            # useful cross-check surfaced in the methodology summary.
            tm_summary["gordon_implied_growth"] = _gordon_implied_growth(
                terminal_fcf=terminal_fcf,
                terminal_value=terminal_value,
                terminal_wacc=terminal_wacc,
            )
        else:
            if terminal_wacc <= terminal_growth_used:
                scenario_warnings.append(
                    ForecastWarning(
                        severity="CRITICAL",
                        scenario=scenario.name,
                        metric="terminal_growth",
                        observation=(
                            f"Terminal growth {terminal_growth_used} >= terminal "
                            f"WACC {terminal_wacc} → Gordon growth undefined. "
                            "Capping g at WACC − 50bps to keep arithmetic "
                            "tractable; re-verify terminal assumptions."
                        ),
                        recommendation=(
                            "Lower terminal_growth below long-term WACC or "
                            "switch to TERMINAL_MULTIPLE method."
                        ),
                    )
                )
                terminal_growth_used = terminal_wacc - Decimal("0.005")
            terminal_value = (
                terminal_fcf * (Decimal("1") + terminal_growth_used)
                / (terminal_wacc - terminal_growth_used)
            )
            tm_summary = None
        terminal_pv = terminal_value / discount_factor_cumulative

        # Enterprise → equity bridge.
        explicit_pv = sum((p.pv for p in explicit_projs), start=Decimal("0"))
        fade_pv = sum((p.pv for p in fade_projs), start=Decimal("0"))
        enterprise_value = explicit_pv + fade_pv + terminal_pv
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

        # Terminal multiple validation.
        ebitda_terminal = (
            fade_projs[-1].operating_income + fade_projs[-1].depreciation
            if fade_projs
            else explicit_projs[-1].operating_income + explicit_projs[-1].depreciation
        )
        validation = TerminalMultipleValidation(
            industry_median_ev_ebitda=period_inputs.industry_median_ev_ebitda,
            warning_threshold=valuation_profile.terminal_value.warning_threshold,
        )
        if ebitda_terminal > 0:
            implied = terminal_value / ebitda_terminal
            validation.implied_ev_ebitda = implied
            if period_inputs.industry_median_ev_ebitda:
                ratio = implied / period_inputs.industry_median_ev_ebitda
                validation.ratio_vs_median = ratio
                if ratio > valuation_profile.terminal_value.warning_threshold:
                    validation.warning_emitted = True
                    scenario_warnings.append(
                        ForecastWarning(
                            severity="WARNING",
                            scenario=scenario.name,
                            metric="terminal_multiple",
                            observation=(
                                f"Gordon growth implies terminal EV/EBITDA "
                                f"{implied:.2f}× vs industry median "
                                f"{period_inputs.industry_median_ev_ebitda:.2f}× "
                                f"(ratio {ratio:.2f}×, threshold "
                                f"{valuation_profile.terminal_value.warning_threshold:.2f}×)."
                            ),
                            recommendation=(
                                "Lower terminal growth, compress margin "
                                "convergence, or switch to terminal multiple."
                            ),
                        )
                    )

        # Forecast coherence warnings.
        scenario_warnings.extend(
            _forecast_coherence_warnings(scenario.name, explicit_projs, fade_projs)
        )

        valuation = DCFValuation(
            ticker=period_inputs.ticker,
            scenario_name=scenario.name,
            scenario_probability=scenario.probability,
            methodology_summary=tm_summary or {},
            explicit_projections=explicit_projs,
            fade_projections=fade_projs,
            terminal_fcf=terminal_fcf,
            terminal_growth=terminal_growth_used,
            terminal_wacc=terminal_wacc,
            terminal_value=terminal_value,
            terminal_pv=terminal_pv,
            enterprise_value=enterprise_value,
            net_debt=period_inputs.net_debt,
            non_operating_assets=period_inputs.non_operating_assets,
            equity_value=equity_value,
            shares_outstanding=shares,
            fair_value_per_share=fair_value_per_share,
            terminal_multiple_validation=validation,
        )
        return valuation, scenario_warnings

    # ------------------------------------------------------------------
    # Sprint 4A-alpha.3 — TERMINAL_MULTIPLE branch helpers
    # ------------------------------------------------------------------
    def _terminal_value_from_multiple(
        self,
        *,
        scenario: Scenario,
        methodology: DCFMethodologyConfig,
        terminal_proj: DCFStageProjection,
        terminal_wacc: Decimal,
        period_inputs: PeriodInputs,
        peer_comparison: Any | None,
    ) -> tuple[Decimal, dict[str, Any], list[ForecastWarning]]:
        """Compute terminal value as ``terminal_metric × resolved_multiple``.

        Returns ``(terminal_value, summary, warnings)``. Warnings fire
        when the requested multiple source can't be resolved; in that
        case ``terminal_value`` falls back to zero and the caller can
        surface the issue.
        """
        warnings: list[ForecastWarning] = []
        metric_value = _terminal_metric_value(
            methodology.terminal_multiple_metric, terminal_proj
        )
        multiple, source_note, source_warning = _resolve_terminal_multiple(
            methodology=methodology,
            period_inputs=period_inputs,
            peer_comparison=peer_comparison,
        )
        if source_warning is not None:
            warnings.append(
                ForecastWarning(
                    severity="CRITICAL",
                    scenario=scenario.name,
                    metric="terminal_multiple_source",
                    observation=source_warning,
                    recommendation=(
                        "Switch terminal_multiple_source to USER_SPECIFIED "
                        "with an explicit value, or wire the required "
                        "reference data (industry median / peer comparison)."
                    ),
                )
            )
        terminal_value = (
            metric_value * multiple if multiple is not None else Decimal("0")
        )
        summary: dict[str, Any] = {
            "terminal_method": "TERMINAL_MULTIPLE",
            "terminal_metric": methodology.terminal_multiple_metric,
            "terminal_metric_value": metric_value,
            "terminal_multiple_source": methodology.terminal_multiple_source,
            "terminal_multiple_used": multiple,
            "terminal_multiple_source_note": source_note,
        }
        return terminal_value, summary, warnings


def _terminal_metric_value(
    metric: str | None, terminal_proj: DCFStageProjection
) -> Decimal:
    """Translate a metric label into the terminal-year value. ``PE``
    uses NOPAT as a stand-in until Sprint 4A-beta lands the three-
    statement projection (which will surface full net income)."""
    if metric == "EV_SALES":
        return terminal_proj.revenue
    if metric == "PE":
        # Net-income proxy pending three-statement projection (4A-beta).
        return terminal_proj.nopat
    # Default: EV_EBITDA = operating income + D&A.
    return terminal_proj.operating_income + terminal_proj.depreciation


def _resolve_terminal_multiple(
    *,
    methodology: DCFMethodologyConfig,
    period_inputs: PeriodInputs,
    peer_comparison: Any | None,
) -> tuple[Decimal | None, str, str | None]:
    """Return ``(multiple, note, warning)``. ``warning`` is non-None
    only when the requested source can't be resolved."""
    source = methodology.terminal_multiple_source
    if source == "USER_SPECIFIED":
        return methodology.terminal_multiple_value, "user-specified", None
    if source == "INDUSTRY_MEDIAN":
        value = period_inputs.industry_median_ev_ebitda
        if value is None:
            return (
                None,
                "industry median (unavailable)",
                "INDUSTRY_MEDIAN requested but no industry median "
                "available for this ticker.",
            )
        return value, "industry median", None
    if source == "PEER_MEDIAN":
        if peer_comparison is None:
            return (
                None,
                "peer median (no peers loaded)",
                "PEER_MEDIAN requested but no peers.yaml is populated "
                "for this ticker.",
            )
        # Peer median can live under either key depending on the
        # fetcher convention. Try the Sprint-3 ``ev_to_ebitda`` first,
        # fall back to ``ev_ebitda`` for forward-compat.
        median = peer_comparison.peer_median.get(
            "ev_to_ebitda"
        ) or peer_comparison.peer_median.get("ev_ebitda")
        if median is None:
            return (
                None,
                "peer median (metric missing)",
                "PEER_MEDIAN requested but peer comparison has no "
                "EV/EBITDA data.",
            )
        return median, "peer median", None
    return None, "unknown source", f"Unknown terminal_multiple_source: {source}"


def _gordon_implied_growth(
    *,
    terminal_fcf: Decimal,
    terminal_value: Decimal,
    terminal_wacc: Decimal,
) -> Decimal | None:
    """Back out the Gordon growth rate that would produce the same
    terminal value given the terminal FCF and WACC:

    ``TV = FCF × (1 + g) / (WACC − g)  →
     g = (WACC × TV − FCF) / (TV + FCF)``

    Returns ``None`` when the math is undefined (zero denominator)."""
    if terminal_value + terminal_fcf == 0:
        return None
    return (terminal_wacc * terminal_value - terminal_fcf) / (
        terminal_value + terminal_fcf
    )


def _forecast_coherence_warnings(
    scenario_name: str,
    explicit: list[DCFStageProjection],
    fade: list[DCFStageProjection],
) -> list[ForecastWarning]:
    """Sprint 4A-alpha Part D — basic coherence checks. Persistently
    negative FCF in mature (fade) years is a WARNING; implausible
    implied ROIC (> 40 % or < −5 %) is INFO."""
    warnings: list[ForecastWarning] = []
    mature = fade[-3:] if len(fade) >= 3 else fade
    if mature and all(p.fcf < Decimal("0") for p in mature):
        warnings.append(
            ForecastWarning(
                severity="WARNING",
                scenario=scenario_name,
                year=mature[-1].year,
                metric="free_cash_flow",
                observation=(
                    "Free cash flow persistently negative across the last "
                    "three forecast years — mature-year FCF should be "
                    "positive for most going-concern P1 businesses."
                ),
                recommendation=(
                    "Re-check capex intensity or working-capital assumptions."
                ),
            )
        )
    return warnings


def _probability_weighted_expected_value(
    valuations: list[DCFValuation],
) -> Decimal | None:
    if not valuations:
        return None
    total_weight = sum((v.scenario_probability for v in valuations), start=Decimal("0"))
    if total_weight == 0:
        return None
    weighted = sum(
        (v.fair_value_per_share * v.scenario_probability for v in valuations),
        start=Decimal("0"),
    )
    return weighted / total_weight


def _percentile_values(
    valuations: list[DCFValuation],
) -> tuple[Decimal | None, Decimal | None]:
    if not valuations:
        return None, None
    values = sorted(v.fair_value_per_share for v in valuations)
    n = len(values)
    if n == 1:
        return values[0], values[0]
    # Probability-weighted percentile would be more rigorous, but with
    # 3-4 scenarios the display-only p25/p75 works fine off the sorted
    # scenario values.
    p25_idx = max(0, (n - 1) // 4)
    p75_idx = min(n - 1, (3 * (n - 1)) // 4)
    return values[p25_idx], values[p75_idx]


__all__ = ["P1DCFEngine", "PeriodInputs"]
