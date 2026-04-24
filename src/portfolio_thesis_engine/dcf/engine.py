"""Phase 2 Sprint 4A-alpha.2 — :class:`ValuationEngine` dispatcher.

Per-scenario methodology routing. Each :class:`Scenario` in a
:class:`ScenarioSet` declares its methodology config; the dispatcher
instantiates the appropriate engine (DCF 3-stage, DCF 2-stage,
Multiple Exit, Transaction Precedent). Sprint 4B / 4C methodologies
raise :class:`NotImplementedError` with explicit sprint pointers.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from portfolio_thesis_engine.dcf.multiple_exit import MultipleExitEngine
from portfolio_thesis_engine.dcf.p1_engine import (
    P1DCFEngine,
    PeriodInputs,
    _forecast_coherence_warnings,
    _merge_scenario_overrides,
    _resolve_base_drivers,
)
from portfolio_thesis_engine.dcf.schemas import (
    DCFMethodologyConfig,
    DCFStructure,
    DCFValuation,
    DCFValuationResult,
    DDMMethodologyConfig,
    ForecastWarning,
    MultipleExitMethodologyConfig,
    ResidualIncomeMethodologyConfig,
    Scenario,
    ScenarioSet,
    TransactionPrecedentMethodologyConfig,
    ValuationMethodology,
    ValuationProfile,
)
from portfolio_thesis_engine.dcf.transaction_precedent import (
    TransactionPrecedentEngine,
)
from portfolio_thesis_engine.valuation_methodologies.ddm import DDMEngine
from portfolio_thesis_engine.valuation_methodologies.residual_income import (
    RIEngine,
)


_BPS = Decimal("10000")
_HUNDRED = Decimal("100")


class ValuationEngine:
    """Dispatcher — routes each scenario to its methodology engine and
    assembles the :class:`DCFValuationResult`."""

    def __init__(self) -> None:
        self._dcf = P1DCFEngine()
        self._multiple_exit = MultipleExitEngine()
        self._transaction_precedent = TransactionPrecedentEngine()
        self._ddm = DDMEngine()
        self._ri = RIEngine()

    # ------------------------------------------------------------------
    def run(
        self,
        *,
        valuation_profile: ValuationProfile,
        scenario_set: ScenarioSet,
        period_inputs: PeriodInputs,
        peer_comparison: Any | None = None,
        forecast_result: Any | None = None,
    ) -> DCFValuationResult:
        base_drivers = _resolve_base_drivers(scenario_set)
        scenario_valuations: list[DCFValuation] = []
        warnings: list[ForecastWarning] = []

        # Sprint 4B — DDM / RI dispatch looks up a per-scenario
        # :class:`ThreeStatementProjection` from the optional
        # ``forecast_result``. DCF-only scenario sets skip the lookup.
        projection_by_scenario: dict[str, Any] = {}
        if forecast_result is not None:
            for projection in forecast_result.projections:
                projection_by_scenario[projection.scenario_name] = projection

        for scenario in scenario_set.scenarios:
            methodology = scenario.methodology
            try:
                valuation, scenario_warnings = self._dispatch(
                    scenario=scenario,
                    methodology=methodology,
                    valuation_profile=valuation_profile,
                    base_drivers=base_drivers,
                    period_inputs=period_inputs,
                    peer_comparison=peer_comparison,
                    projection_by_scenario=projection_by_scenario,
                )
            except NotImplementedError as exc:
                warnings.append(
                    ForecastWarning(
                        severity="CRITICAL",
                        scenario=scenario.name,
                        metric="methodology",
                        observation=str(exc),
                        recommendation=(
                            "Swap the scenario's methodology to a "
                            "Sprint 4A-alpha-supported type "
                            "(DCF_3_STAGE, DCF_2_STAGE, MULTIPLE_EXIT, "
                            "TRANSACTION_PRECEDENT) or wait for the "
                            "target sprint."
                        ),
                    )
                )
                continue
            scenario_valuations.append(valuation)
            warnings.extend(scenario_warnings)

        expected = _probability_weighted_expected_value(scenario_valuations)
        p25, p75 = _percentile_values(scenario_valuations)
        upside = None
        if (
            period_inputs.market_price
            and period_inputs.market_price != 0
            and expected is not None
        ):
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
    def _dispatch(
        self,
        *,
        scenario: Scenario,
        methodology: Any,
        valuation_profile: ValuationProfile,
        base_drivers: dict[str, Any],
        period_inputs: PeriodInputs,
        peer_comparison: Any | None,
        projection_by_scenario: dict[str, Any] | None = None,
    ) -> tuple[DCFValuation, list[ForecastWarning]]:
        if isinstance(methodology, DCFMethodologyConfig):
            return self._run_dcf(
                scenario=scenario,
                methodology=methodology,
                valuation_profile=valuation_profile,
                base_drivers=base_drivers,
                period_inputs=period_inputs,
                peer_comparison=peer_comparison,
            )
        if isinstance(methodology, MultipleExitMethodologyConfig):
            valuation = self._multiple_exit.value(
                scenario=scenario,
                methodology=methodology,
                base_drivers=base_drivers,
                period_inputs=period_inputs,
                peer_comparison=peer_comparison,
            )
            return valuation, []
        if isinstance(methodology, TransactionPrecedentMethodologyConfig):
            valuation = self._transaction_precedent.value(
                scenario=scenario,
                methodology=methodology,
                base_drivers=base_drivers,
                period_inputs=period_inputs,
            )
            return valuation, []
        if isinstance(methodology, DDMMethodologyConfig):
            return self._run_ddm(
                scenario=scenario,
                methodology=methodology,
                period_inputs=period_inputs,
                projection_by_scenario=projection_by_scenario or {},
            )
        if isinstance(methodology, ResidualIncomeMethodologyConfig):
            return self._run_ri(
                scenario=scenario,
                methodology=methodology,
                period_inputs=period_inputs,
                projection_by_scenario=projection_by_scenario or {},
            )
        methodology_type = getattr(methodology, "type", "UNKNOWN")
        if methodology_type == "FFO_BASED":
            raise NotImplementedError(
                "FFO_BASED is planned for Sprint 4C (REITs)."
            )
        if methodology_type in ("NORMALIZED_DCF", "THROUGH_CYCLE_DCF"):
            raise NotImplementedError(
                f"{methodology_type} is planned for Sprint 4C (cyclicals / commodities)."
            )
        if methodology_type == "ASSET_BASED":
            raise NotImplementedError(
                "ASSET_BASED is planned for Sprint 4D (sum-of-parts / NAV)."
            )
        raise NotImplementedError(
            f"Unknown methodology type '{methodology_type}'"
        )

    # ------------------------------------------------------------------
    def _run_ddm(
        self,
        *,
        scenario: Scenario,
        methodology: DDMMethodologyConfig,
        period_inputs: PeriodInputs,
        projection_by_scenario: dict[str, Any],
    ) -> tuple[DCFValuation, list[ForecastWarning]]:
        """Dispatch a DDM scenario. Wraps the :class:`DDMProjection`
        output into a :class:`DCFValuation` so the orchestrator's
        aggregation pipeline (probability weighting, p25 / p75) works
        unchanged. The native DDM detail lives in ``methodology_summary``.
        """
        projection = projection_by_scenario.get(scenario.name)
        if projection is None:
            raise NotImplementedError(
                f"DDM scenario '{scenario.name}' requires a three-statement "
                "projection — the orchestrator did not produce one. Check "
                "that scenarios.yaml is consumable by the forecast engine."
            )
        coe = (
            methodology.cost_of_equity_override
            if methodology.cost_of_equity_override is not None
            else period_inputs.cost_of_equity
        )
        if coe is None:
            raise NotImplementedError(
                f"DDM scenario '{scenario.name}' needs a cost_of_equity — "
                "set methodology.cost_of_equity_override or wire the "
                "Sprint-3 WACCGenerator output into PeriodInputs."
            )
        ddm_result = self._ddm.compute(
            projection=projection,
            cost_of_equity=coe,
            terminal_growth_rate=methodology.terminal_growth,
        )
        valuation = DCFValuation(
            ticker=period_inputs.ticker,
            scenario_name=scenario.name,
            scenario_probability=scenario.probability,
            methodology_used=ValuationMethodology.DDM,
            methodology_summary={
                "methodology": "DDM",
                "terminal_dividend": ddm_result.terminal_dividend,
                "terminal_growth": methodology.terminal_growth,
                "terminal_discount_rate": ddm_result.terminal_discount_rate,
                "cost_of_equity_applied": coe,
                "explicit_years": methodology.explicit_years,
            },
            terminal_growth=methodology.terminal_growth,
            terminal_wacc=coe,
            terminal_value=ddm_result.terminal_value,
            terminal_pv=ddm_result.terminal_pv,
            enterprise_value=ddm_result.enterprise_value,
            net_debt=Decimal("0"),
            non_operating_assets=Decimal("0"),
            equity_value=ddm_result.equity_value,
            shares_outstanding=ddm_result.shares_outstanding_terminal,
            fair_value_per_share=ddm_result.fair_value_per_share,
        )
        return valuation, _ddm_warnings(ddm_result)

    # ------------------------------------------------------------------
    def _run_ri(
        self,
        *,
        scenario: Scenario,
        methodology: ResidualIncomeMethodologyConfig,
        period_inputs: PeriodInputs,
        projection_by_scenario: dict[str, Any],
    ) -> tuple[DCFValuation, list[ForecastWarning]]:
        """Dispatch a Residual Income scenario. Same wrap-into-DCFValuation
        pattern as :meth:`_run_ddm`."""
        projection = projection_by_scenario.get(scenario.name)
        if projection is None:
            raise NotImplementedError(
                f"RESIDUAL_INCOME scenario '{scenario.name}' requires a "
                "three-statement projection — orchestrator did not "
                "produce one."
            )
        coe = (
            methodology.cost_of_equity_override
            if methodology.cost_of_equity_override is not None
            else period_inputs.cost_of_equity
        )
        if coe is None:
            raise NotImplementedError(
                f"RESIDUAL_INCOME scenario '{scenario.name}' needs a "
                "cost_of_equity — set methodology.cost_of_equity_override "
                "or wire the Sprint-3 WACCGenerator output into PeriodInputs."
            )
        base_equity = period_inputs.equity_claims
        if base_equity is None or base_equity <= 0:
            raise NotImplementedError(
                f"RESIDUAL_INCOME scenario '{scenario.name}' needs a "
                "positive base book value — canonical state does not "
                "expose equity_claims, or it is non-positive."
            )
        ri_result = self._ri.compute(
            projection=projection,
            cost_of_equity=coe,
            base_equity=base_equity,
            terminal_growth_rate=methodology.terminal_growth,
        )
        valuation = DCFValuation(
            ticker=period_inputs.ticker,
            scenario_name=scenario.name,
            scenario_probability=scenario.probability,
            methodology_used=ValuationMethodology.RESIDUAL_INCOME,
            methodology_summary={
                "methodology": "RESIDUAL_INCOME",
                "base_book_value": ri_result.base_book_value,
                "terminal_residual_income": ri_result.terminal_residual_income,
                "terminal_growth": methodology.terminal_growth,
                "terminal_discount_rate": ri_result.terminal_discount_rate,
                "cost_of_equity_applied": coe,
                "sum_pv_residual_income": ri_result.sum_pv_residual_income,
                "explicit_years": methodology.explicit_years,
            },
            terminal_growth=methodology.terminal_growth,
            terminal_wacc=coe,
            terminal_value=ri_result.terminal_value,
            terminal_pv=ri_result.terminal_pv,
            enterprise_value=ri_result.enterprise_value,
            net_debt=Decimal("0"),
            non_operating_assets=Decimal("0"),
            equity_value=ri_result.equity_value,
            shares_outstanding=ri_result.shares_outstanding_terminal,
            fair_value_per_share=ri_result.fair_value_per_share,
        )
        return valuation, _ri_warnings(ri_result)

    # ------------------------------------------------------------------
    def _run_dcf(
        self,
        *,
        scenario: Scenario,
        methodology: DCFMethodologyConfig,
        valuation_profile: ValuationProfile,
        base_drivers: dict[str, Any],
        period_inputs: PeriodInputs,
        peer_comparison: Any | None = None,
    ) -> tuple[DCFValuation, list[ForecastWarning]]:
        """Run the underlying P1 DCF engine with a per-scenario
        override of ``dcf_structure`` (explicit_years / fade_years /
        terminal_growth sourced from the methodology config)."""
        structure_type = "TWO_STAGE" if methodology.fade_years == 0 else "THREE_STAGE"
        structure = DCFStructure(
            type=structure_type,
            explicit_years=methodology.explicit_years,
            fade_years=methodology.fade_years,
            terminal_method=(
                "TERMINAL_MULTIPLE"
                if methodology.terminal_method.value == "TERMINAL_MULTIPLE"
                else "GORDON_GROWTH"
            ),
        )
        profile_copy = valuation_profile.model_copy(
            update={"dcf_structure": structure}
        )
        # Update terminal growth via terminal_value block for Gordon
        # scenarios. TERMINAL_MULTIPLE leaves the existing config intact
        # and reads methodology fields directly in the engine.
        if (
            methodology.terminal_method.value == "GORDON_GROWTH"
            and methodology.terminal_growth is not None
        ):
            terminal_value = profile_copy.terminal_value.model_copy(
                update={"growth_rate": methodology.terminal_growth}
            )
            profile_copy = profile_copy.model_copy(
                update={"terminal_value": terminal_value}
            )
        drivers = _merge_scenario_overrides(base_drivers, scenario)
        valuation, warnings = self._dcf._run_scenario(  # noqa: SLF001
            scenario=scenario,
            drivers=drivers,
            valuation_profile=profile_copy,
            period_inputs=period_inputs,
            peer_comparison=peer_comparison,
        )
        valuation.methodology_used = (
            ValuationMethodology.DCF_3_STAGE
            if methodology.fade_years > 0
            else ValuationMethodology.DCF_2_STAGE
        )
        # Preserve terminal-multiple details set by ``_run_scenario``
        # while adding structural metadata.
        valuation.methodology_summary = {
            **valuation.methodology_summary,
            "explicit_years": methodology.explicit_years,
            "fade_years": methodology.fade_years,
            "terminal_growth": methodology.terminal_growth,
            "terminal_method": methodology.terminal_method.value,
        }
        return valuation, warnings


# ----------------------------------------------------------------------
# Helpers — translate engine-native warning strings into
# :class:`ForecastWarning` entries for the unified warnings pipeline.
# ----------------------------------------------------------------------
def _ddm_warnings(result) -> list[ForecastWarning]:
    return [
        ForecastWarning(
            severity="WARNING",
            scenario=result.scenario_name,
            metric="ddm",
            observation=msg,
        )
        for msg in result.warnings
    ]


def _ri_warnings(result) -> list[ForecastWarning]:
    return [
        ForecastWarning(
            severity="WARNING",
            scenario=result.scenario_name,
            metric="residual_income",
            observation=msg,
        )
        for msg in result.warnings
    ]


# ----------------------------------------------------------------------
# Helpers shared with the legacy P1DCFEngine top-level ``run``.
# Duplicated to keep ``engine.py`` self-contained.
# ----------------------------------------------------------------------
def _probability_weighted_expected_value(
    valuations: list[DCFValuation],
) -> Decimal | None:
    if not valuations:
        return None
    total_weight = sum(
        (v.scenario_probability for v in valuations), start=Decimal("0")
    )
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
    p25_idx = max(0, (n - 1) // 4)
    p75_idx = min(n - 1, (3 * (n - 1)) // 4)
    return values[p25_idx], values[p75_idx]


__all__ = ["ValuationEngine"]
