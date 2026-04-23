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
    ForecastWarning,
    MultipleExitMethodologyConfig,
    Scenario,
    ScenarioSet,
    TransactionPrecedentMethodologyConfig,
    ValuationMethodology,
    ValuationProfile,
)
from portfolio_thesis_engine.dcf.transaction_precedent import (
    TransactionPrecedentEngine,
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

    # ------------------------------------------------------------------
    def run(
        self,
        *,
        valuation_profile: ValuationProfile,
        scenario_set: ScenarioSet,
        period_inputs: PeriodInputs,
        peer_comparison: Any | None = None,
    ) -> DCFValuationResult:
        base_drivers = _resolve_base_drivers(scenario_set)
        scenario_valuations: list[DCFValuation] = []
        warnings: list[ForecastWarning] = []

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
        methodology_type = getattr(methodology, "type", "UNKNOWN")
        if methodology_type in ("DDM", "RESIDUAL_INCOME", "FFO_BASED"):
            raise NotImplementedError(
                f"{methodology_type} is planned for Sprint 4B (financials / REITs)."
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
