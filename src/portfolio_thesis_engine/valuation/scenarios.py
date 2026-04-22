"""Scenario composition — run DCF + Equity + IRR per scenario.

:class:`ScenarioComposer` consumes :class:`WACCInputs` (three scenario
drivers from ``wacc_inputs.md``), runs the DCF / equity / IRR chain
for each, and returns a list of :class:`Scenario` objects suitable for
attaching directly to :class:`ValuationSnapshot.scenarios`.

Per-scenario WACC selection:

- If ``scenario.wacc_override`` is set on :class:`ScenarioDriversManual`,
  use it.
- Else use the headline ``WACCInputs.wacc`` property (capital-weighted).

Phase 1 scope: every scenario uses the same ``revenue_cagr`` +
``terminal_growth`` + ``terminal_margin`` from its driver block. No
custom margin paths, no SOTP, no stress overlays.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from portfolio_thesis_engine.schemas.company import CanonicalCompanyState
from portfolio_thesis_engine.schemas.valuation import (
    EquityBridgeDetail,
    EVBreakdown,
    MarketSnapshot,
    ProjectionYear,
    Scenario,
    ScenarioDrivers,
    SensitivityGrid,
    TerminalProjection,
)
from portfolio_thesis_engine.schemas.wacc import ScenarioDriversManual, WACCInputs
from portfolio_thesis_engine.valuation.base import IRRResult, ValuationResult
from portfolio_thesis_engine.valuation.dcf import FCFFDCFEngine
from portfolio_thesis_engine.valuation.equity_bridge import EquityBridge
from portfolio_thesis_engine.valuation.irr import IRRDecomposer

_PCT_MIN = Decimal("-100")
_PCT_MAX = Decimal("1000")
_SCENARIO_ORDER = ("bear", "base", "bull")


def _clip_pct(value: Decimal) -> Decimal:
    """Clip a percentage to the :class:`Percentage` schema bounds
    (−100, 1000). Deep-bear scenarios can overshoot mathematically; the
    schema treats −100 % as a full wipeout and caller semantics don't
    rely on values beyond that."""
    if value < _PCT_MIN:
        return _PCT_MIN
    if value > _PCT_MAX:
        return _PCT_MAX
    return value
_DESCRIPTIONS = {
    "bear": "Bear scenario: pessimistic growth / margin assumptions.",
    "base": "Base scenario: most-likely trajectory.",
    "bull": "Bull scenario: optimistic growth / margin assumptions.",
}


class ScenarioComposer:
    """Compose the Bear / Base / Bull bundle from :class:`WACCInputs`."""

    def __init__(
        self,
        dcf_engine: FCFFDCFEngine | None = None,
        equity_bridge: EquityBridge | None = None,
        irr_decomposer: IRRDecomposer | None = None,
        horizon_years: int = 3,
    ) -> None:
        self.dcf_engine = dcf_engine or FCFFDCFEngine()
        self.equity_bridge = equity_bridge or EquityBridge()
        self.irr_decomposer = irr_decomposer or IRRDecomposer()
        self.horizon_years = horizon_years

    # ------------------------------------------------------------------
    def compose(
        self,
        wacc_inputs: WACCInputs,
        canonical_state: CanonicalCompanyState,
        market: MarketSnapshot | None = None,
    ) -> list[Scenario]:
        """Return one :class:`Scenario` per label in ``wacc_inputs``,
        in ``bear → base → bull`` order (filtering out labels that
        aren't supplied).

        Phase 1.5.9: delegates the full transparency build-up
        (projection / terminal / EV breakdown / equity bridge /
        sensitivity grids) to :meth:`FCFFDCFEngine.compute`. The composer
        still handles IRR + upside + scenario metadata.
        """
        current_price = wacc_inputs.current_price
        scenarios_out: list[Scenario] = []

        for label in _SCENARIO_ORDER:
            driver = wacc_inputs.scenarios.get(label)
            if driver is None:
                continue
            scenario_stub = _build_scenario_stub(label, driver, self.horizon_years)
            wacc_used = self._wacc_for(driver, wacc_inputs)

            # Build a MarketSnapshot stub so the engine can read the
            # WACC — callers that have a real market snapshot pass it
            # in to capture price / shares.
            market_for_engine = market or MarketSnapshot(
                price=current_price,
                price_date=wacc_inputs.valuation_date,
                shares_outstanding=canonical_state.identity.shares_outstanding,
                wacc=wacc_used,
                currency=canonical_state.identity.reporting_currency,
            )
            result: ValuationResult = self.dcf_engine.compute(
                canonical_state=canonical_state,
                scenario=scenario_stub,
                market=market_for_engine,
            )
            equity_per_share = result.target_per_share
            equity_value = result.equity_bridge.equity_value

            if equity_per_share is None:
                irr: IRRResult | None = None
            else:
                irr = self.irr_decomposer.decompose(
                    target_price=equity_per_share,
                    current_price=current_price,
                    scenario=scenario_stub,
                    canonical_state=canonical_state,
                    horizon_years=self.horizon_years,
                )

            scenarios_out.append(
                _finalise_scenario(
                    stub=scenario_stub,
                    equity_per_share=equity_per_share,
                    equity_value=equity_value,
                    current_price=current_price,
                    irr=irr,
                    projection=result.projection,
                    terminal=result.terminal,
                    ev_breakdown=result.enterprise_value_breakdown,
                    equity_bridge=result.equity_bridge,
                    sensitivity_grids=result.sensitivity_grids,
                )
            )

        return scenarios_out

    # ------------------------------------------------------------------
    def compose_sensitivity(
        self,
        wacc_inputs: WACCInputs,
        canonical_state: CanonicalCompanyState,
        labels: tuple[str, ...] = ("base",),
    ) -> list[SensitivityGrid]:
        """Phase 1.5.9 — flatten per-scenario sensitivity grids to the
        top-level :class:`ValuationSnapshot.sensitivities` list. Default
        emits only the base-scenario grids (2: WACC×g and CAGR×margin).
        """
        grids: list[SensitivityGrid] = []
        current_price = wacc_inputs.current_price
        for label in labels:
            driver = wacc_inputs.scenarios.get(label)
            if driver is None:
                continue
            scenario_stub = _build_scenario_stub(label, driver, self.horizon_years)
            wacc_used = self._wacc_for(driver, wacc_inputs)
            market = MarketSnapshot(
                price=current_price,
                price_date=wacc_inputs.valuation_date,
                shares_outstanding=canonical_state.identity.shares_outstanding,
                wacc=wacc_used,
                currency=canonical_state.identity.reporting_currency,
            )
            result = self.dcf_engine.compute(
                canonical_state=canonical_state,
                scenario=scenario_stub,
                market=market,
            )
            grids.extend(result.sensitivity_grids)
        return grids

    # ------------------------------------------------------------------
    def _wacc_for(self, driver: ScenarioDriversManual, wacc_inputs: WACCInputs) -> Decimal:
        if driver.wacc_override is not None:
            return driver.wacc_override
        return wacc_inputs.wacc

    def describe(self) -> dict[str, Any]:
        return {
            "engine": "ScenarioComposer",
            "horizon_years": self.horizon_years,
            "dcf": self.dcf_engine.describe(),
        }


# ----------------------------------------------------------------------
# Conversion helpers — ScenarioDriversManual → ScenarioDrivers → Scenario
# ----------------------------------------------------------------------
def _build_scenario_stub(
    label: str,
    driver: ScenarioDriversManual,
    horizon_years: int,
) -> Scenario:
    """Build a :class:`Scenario` with drivers populated from the WACC
    manual; targets / IRR fields are filled in after DCF + IRR run."""
    return Scenario(
        label=label,
        description=_DESCRIPTIONS.get(label, f"Scenario {label}"),
        probability=driver.probability,
        horizon_years=horizon_years,
        drivers=ScenarioDrivers(
            revenue_cagr=driver.revenue_cagr_explicit_period,
            terminal_growth=driver.terminal_growth,
            terminal_margin=driver.terminal_operating_margin,
        ),
    )


def _finalise_scenario(
    stub: Scenario,
    equity_per_share: Decimal | None,
    equity_value: Decimal,
    current_price: Decimal,
    irr: IRRResult | None,
    projection: list[ProjectionYear] | None = None,
    terminal: TerminalProjection | None = None,
    ev_breakdown: EVBreakdown | None = None,
    equity_bridge: EquityBridgeDetail | None = None,
    sensitivity_grids: list[SensitivityGrid] | None = None,
) -> Scenario:
    """Return a new :class:`Scenario` with targets / IRR fields set."""
    targets: dict[str, Decimal] = {"equity_value": equity_value}
    if equity_per_share is not None:
        targets["dcf_fcff_per_share"] = equity_per_share

    irr_3y: Decimal | None = None
    irr_decomp: dict[str, Decimal] | None = None
    if irr is not None:
        irr_3y = _clip_pct(irr.total_p_a * Decimal("100"))
        irr_decomp = {
            "fundamental": _clip_pct(irr.fundamental_p_a * Decimal("100")),
            "rerating": _clip_pct(irr.rerating_p_a * Decimal("100")),
            "dividend": _clip_pct(irr.dividend_yield_p_a * Decimal("100")),
        }

    upside: Decimal | None = None
    if equity_per_share is not None and current_price != 0:
        upside = _clip_pct(
            (equity_per_share - current_price) / current_price * Decimal("100")
        )

    return Scenario(
        label=stub.label,
        description=stub.description,
        probability=stub.probability,
        horizon_years=stub.horizon_years,
        drivers=stub.drivers,
        targets=targets,
        irr_3y=irr_3y,
        irr_decomposition=irr_decomp,
        upside_pct=upside,
        projection=projection or [],
        terminal=terminal,
        enterprise_value_breakdown=ev_breakdown,
        equity_bridge=equity_bridge,
        sensitivity_grids=sensitivity_grids or [],
    )
