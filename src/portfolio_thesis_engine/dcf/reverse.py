"""Phase 2 Sprint 4A-alpha.4 — Reverse DCF solver.

Answers the inverse question — "given today's market price, what
assumptions must the market be implying?" — following Mauboussin's
framing. Rather than defending a fair-value estimate, the reverse DCF
isolates the single driver value that would reconcile the market
price with the analyst's scenario projection.

Uses pure-Python bisection (no scipy dependency) on a bracketed root
of the objective ``fair_value(driver) − target_price``. The objective
is monotonic in each supported driver over the declared bracket, so
bisection converges in ~15 iterations for 1 bp precision.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Callable, Literal

from pydantic import Field

from portfolio_thesis_engine.dcf.engine import ValuationEngine
from portfolio_thesis_engine.dcf.p1_engine import PeriodInputs
from portfolio_thesis_engine.dcf.schemas import (
    DCFMethodologyConfig,
    Scenario,
    ScenarioDriverOverride,
    ScenarioSet,
    TerminalMethod,
    ValuationProfile,
)
from portfolio_thesis_engine.schemas.base import BaseSchema


_Convergence = Literal["CONVERGED", "NO_ROOT_IN_BRACKET", "MAX_ITER"]
_Plausibility = Literal["HIGH", "MODERATE", "LOW", "VERY_LOW"]

# ---------------------------------------------------------------------------
# Driver specs — declaration of what the solver knows how to tweak.
# ---------------------------------------------------------------------------
_DRIVER_SPECS: dict[str, dict[str, Any]] = {
    "operating_margin": {
        "bracket": (Decimal("-0.05"), Decimal("0.40")),
        "display_name": "Operating margin (terminal)",
        "injection": "operating_margin.target_terminal",
    },
    "terminal_growth": {
        "bracket": (Decimal("-0.05"), Decimal("0.10")),
        "display_name": "Terminal growth",
        "injection": "methodology.terminal_growth",
    },
    "wacc": {
        "bracket": (Decimal("0.03"), Decimal("0.30")),
        "display_name": "WACC (stage 1)",
        "injection": "context.stage_1_wacc",
    },
    "revenue_growth_terminal": {
        "bracket": (Decimal("-0.05"), Decimal("0.20")),
        "display_name": "Revenue growth (terminal)",
        "injection": "revenue.terminal_growth",
    },
    "capex_intensity": {
        "bracket": (Decimal("0.02"), Decimal("0.25")),
        "display_name": "Capex intensity (target)",
        "injection": "capex_intensity.target",
    },
}


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------
class ImpliedValue(BaseSchema):
    """Result of one reverse-DCF solve."""

    solve_for: str
    display_name: str
    implied_value: Decimal | None = None
    baseline_value: Decimal
    gap_vs_baseline: Decimal | None = None
    target_fv: Decimal
    convergence: _Convergence = "CONVERGED"
    bracket_tested: tuple[Decimal, Decimal] | None = None
    error: str | None = None


class PlausibilityAssessment(BaseSchema):
    driver: str
    implied_value: Decimal
    baseline_value: Decimal
    historical_range: tuple[Decimal, Decimal] | None = None
    historical_mean: Decimal | None = None
    latest_audited: Decimal | None = None
    guidance_value: Decimal | None = None
    plausibility: _Plausibility
    rationale: str


class ReverseDCFReport(BaseSchema):
    """Top-level output of a reverse DCF run (single or enumerate)."""

    ticker: str
    scenario_name: str
    methodology: str
    market_price: Decimal | None = None
    forward_fv: Decimal
    target_fv: Decimal
    implied_values: list[ImpliedValue] = Field(default_factory=list)
    plausibility: list[PlausibilityAssessment] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ---------------------------------------------------------------------------
# Root finder
# ---------------------------------------------------------------------------
def _bisect_root(
    f: Callable[[float], float],
    a: float,
    b: float,
    xtol: float = 1e-5,
    ytol: float = 1e-4,
    maxiter: int = 100,
) -> float:
    """Pure-Python bisection. Returns ``x`` in ``[a, b]`` with
    ``|f(x)| < ytol`` or bracket width below ``xtol``. Raises
    ``ValueError`` when the bracket does not contain a sign change."""
    fa = f(a)
    fb = f(b)
    if fa == 0:
        return a
    if fb == 0:
        return b
    if fa * fb > 0:
        raise ValueError(
            f"f({a})={fa:.6g} and f({b})={fb:.6g} share sign; "
            "no root in bracket."
        )
    for _ in range(maxiter):
        c = (a + b) / 2
        fc = f(c)
        if abs(fc) < ytol or (b - a) / 2 < xtol:
            return c
        if fa * fc < 0:
            b, fb = c, fc
        else:
            a, fa = c, fc
    return (a + b) / 2


# ---------------------------------------------------------------------------
# Solver
# ---------------------------------------------------------------------------
class ReverseDCFSolver:
    """Finds the single-driver value that makes the DCF output match
    a target fair-value-per-share. Works with any methodology the
    :class:`ValuationEngine` supports; drivers without meaning for
    a given methodology (``terminal_growth`` on a MULTIPLE_EXIT
    scenario) will simply produce a NO_ROOT_IN_BRACKET result."""

    SUPPORTED_DRIVERS = tuple(_DRIVER_SPECS.keys())

    def __init__(self) -> None:
        self._engine = ValuationEngine()

    # ------------------------------------------------------------------
    def solve(
        self,
        *,
        scenario: Scenario,
        valuation_profile: ValuationProfile,
        period_inputs: PeriodInputs,
        base_drivers: dict[str, Any],
        peer_comparison: Any | None,
        solve_for: str,
        target_fv: Decimal,
    ) -> ImpliedValue:
        if solve_for not in _DRIVER_SPECS:
            raise ValueError(
                f"Unsupported driver: {solve_for}. Choose from "
                f"{list(self.SUPPORTED_DRIVERS)}"
            )
        spec = _DRIVER_SPECS[solve_for]
        baseline = _baseline_value(
            solve_for, scenario, period_inputs, base_drivers
        )
        bracket = spec["bracket"]

        def objective(candidate: float) -> float:
            try:
                fv = _eval_fv(
                    engine=self._engine,
                    scenario=scenario,
                    valuation_profile=valuation_profile,
                    period_inputs=period_inputs,
                    base_drivers=base_drivers,
                    peer_comparison=peer_comparison,
                    solve_for=solve_for,
                    driver_value=Decimal(str(candidate)),
                )
            except Exception:
                # Infeasible points (Gordon degeneracy) → push root
                # finder away by returning a large residual signed the
                # same as the mid-bracket objective would be.
                return 1e18
            return float(fv - target_fv)

        try:
            implied_float = _bisect_root(
                objective, float(bracket[0]), float(bracket[1])
            )
            implied = Decimal(str(round(implied_float, 6)))
            gap = implied - baseline
            return ImpliedValue(
                solve_for=solve_for,
                display_name=spec["display_name"],
                implied_value=implied,
                baseline_value=baseline,
                gap_vs_baseline=gap,
                target_fv=target_fv,
                convergence="CONVERGED",
                bracket_tested=bracket,
            )
        except ValueError as exc:
            return ImpliedValue(
                solve_for=solve_for,
                display_name=spec["display_name"],
                implied_value=None,
                baseline_value=baseline,
                gap_vs_baseline=None,
                target_fv=target_fv,
                convergence="NO_ROOT_IN_BRACKET",
                bracket_tested=bracket,
                error=str(exc),
            )

    # ------------------------------------------------------------------
    def solve_all(
        self,
        *,
        scenario: Scenario,
        valuation_profile: ValuationProfile,
        period_inputs: PeriodInputs,
        base_drivers: dict[str, Any],
        peer_comparison: Any | None,
        target_fv: Decimal,
    ) -> list[ImpliedValue]:
        return [
            self.solve(
                scenario=scenario,
                valuation_profile=valuation_profile,
                period_inputs=period_inputs,
                base_drivers=base_drivers,
                peer_comparison=peer_comparison,
                solve_for=driver,
                target_fv=target_fv,
            )
            for driver in self.SUPPORTED_DRIVERS
        ]


def _eval_fv(
    *,
    engine: ValuationEngine,
    scenario: Scenario,
    valuation_profile: ValuationProfile,
    period_inputs: PeriodInputs,
    base_drivers: dict[str, Any],
    peer_comparison: Any | None,
    solve_for: str,
    driver_value: Decimal,
) -> Decimal:
    """Inject ``driver_value`` into the right hook, run the engine on a
    single-scenario copy of the set, and return fair-value-per-share."""
    modified_scenario, modified_pi, modified_base = _inject(
        scenario=scenario,
        period_inputs=period_inputs,
        base_drivers=base_drivers,
        solve_for=solve_for,
        driver_value=driver_value,
    )
    # Normalise probability to 1.0 for the single-scenario run so the
    # ScenarioSet's probability-sum validator passes. The engine's
    # output reads ``fair_value_per_share`` which is independent of
    # scenario probability anyway.
    modified_scenario = modified_scenario.model_copy(
        update={"probability": Decimal("1")}
    )
    scenario_set = ScenarioSet(
        target_ticker=period_inputs.ticker,
        valuation_profile=valuation_profile.profile.code,
        base_year="reverse-dcf",
        base_drivers=modified_base,
        scenarios=[modified_scenario],
    )
    result = engine.run(
        valuation_profile=valuation_profile,
        scenario_set=scenario_set,
        period_inputs=modified_pi,
        peer_comparison=peer_comparison,
    )
    if not result.scenarios_run:
        return Decimal("0")
    return result.scenarios_run[0].fair_value_per_share


def _inject(
    *,
    scenario: Scenario,
    period_inputs: PeriodInputs,
    base_drivers: dict[str, Any],
    solve_for: str,
    driver_value: Decimal,
) -> tuple[Scenario, PeriodInputs, dict[str, Any]]:
    """Produce a modified ``(scenario, period_inputs, base_drivers)``
    triple for one candidate driver value. We never mutate the
    caller's objects. Some drivers write into ``base_drivers`` because
    ``ScenarioDriverOverride`` doesn't have a field matching the
    engine's lookup key (e.g. ``revenue.terminal_growth`` or
    ``capex_intensity.target``)."""
    # Deep-copy base_drivers so we can mutate safely.
    new_base = {
        k: dict(v) if isinstance(v, dict) else v
        for k, v in base_drivers.items()
    }

    if solve_for == "wacc":
        delta = driver_value - period_inputs.stage_1_wacc
        new_pi = PeriodInputs(
            ticker=period_inputs.ticker,
            stage_1_wacc=driver_value,
            stage_3_wacc=period_inputs.stage_3_wacc + delta,
            net_debt=period_inputs.net_debt,
            non_operating_assets=period_inputs.non_operating_assets,
            shares_outstanding=period_inputs.shares_outstanding,
            market_price=period_inputs.market_price,
            industry_median_ev_ebitda=period_inputs.industry_median_ev_ebitda,
        )
        return scenario, new_pi, new_base

    new_scenario = scenario.model_copy(deep=True)
    overrides = dict(new_scenario.driver_overrides)

    if solve_for == "operating_margin":
        override = overrides.get("operating_margin") or ScenarioDriverOverride()
        overrides["operating_margin"] = override.model_copy(
            update={"target_terminal": driver_value}
        )
    elif solve_for == "capex_intensity":
        # Engine reads capex_intensity.target; write directly into
        # base_drivers because ScenarioDriverOverride has no matching
        # field name.
        cap = new_base.setdefault("capex_intensity", {})
        cap["target"] = driver_value
    elif solve_for == "revenue_growth_terminal":
        # Engine reads revenue.terminal_growth; again base_drivers is
        # the right hook.
        rev = new_base.setdefault("revenue", {})
        rev["terminal_growth"] = driver_value
    elif solve_for == "terminal_growth":
        new_methodology = new_scenario.methodology
        if isinstance(new_methodology, DCFMethodologyConfig):
            if new_methodology.terminal_method == TerminalMethod.GORDON_GROWTH:
                new_methodology = new_methodology.model_copy(
                    update={"terminal_growth": driver_value}
                )
                new_scenario = new_scenario.model_copy(
                    update={"methodology": new_methodology}
                )
        # Also update base_drivers' revenue.terminal_growth so the
        # fade stage converges toward the new rate.
        rev = new_base.setdefault("revenue", {})
        rev["terminal_growth"] = driver_value
    new_scenario = new_scenario.model_copy(update={"driver_overrides": overrides})
    return new_scenario, period_inputs, new_base


def _baseline_value(
    solve_for: str,
    scenario: Scenario,
    period_inputs: PeriodInputs,
    base_drivers: dict[str, Any],
) -> Decimal:
    """Return the un-modified driver value currently implied by the
    scenario / period_inputs (what the forward DCF uses)."""
    if solve_for == "wacc":
        return period_inputs.stage_1_wacc
    if solve_for == "operating_margin":
        override = scenario.driver_overrides.get("operating_margin")
        if override is not None and override.target_terminal is not None:
            return override.target_terminal
        return Decimal(
            str(base_drivers.get("operating_margin", {}).get("target_terminal", 0))
        )
    if solve_for == "capex_intensity":
        override = scenario.driver_overrides.get("capex_intensity")
        if override is not None and override.target_terminal is not None:
            return override.target_terminal
        return Decimal(
            str(base_drivers.get("capex_intensity", {}).get("target", 0))
        )
    if solve_for == "revenue_growth_terminal":
        override = scenario.driver_overrides.get("revenue")
        if override is not None and override.target_terminal is not None:
            return override.target_terminal
        return Decimal(
            str(base_drivers.get("revenue", {}).get("terminal_growth", 0))
        )
    if solve_for == "terminal_growth":
        methodology = scenario.methodology
        if (
            isinstance(methodology, DCFMethodologyConfig)
            and methodology.terminal_growth is not None
        ):
            return methodology.terminal_growth
        return Decimal(
            str(base_drivers.get("revenue", {}).get("terminal_growth", "0.025"))
        )
    return Decimal("0")


# ---------------------------------------------------------------------------
# Plausibility
# ---------------------------------------------------------------------------
_BPS = Decimal("10000")


def assess_plausibility(
    implied: ImpliedValue,
    *,
    historicals: list[Any] | None = None,
    auto_wacc: Decimal | None = None,
) -> PlausibilityAssessment:
    """Translate an :class:`ImpliedValue` into a HIGH/MODERATE/LOW/
    VERY_LOW plausibility rating using historical evidence from the
    Sprint-2 :class:`HistoricalRecord` series when available, plus
    driver-specific heuristics (e.g. WACC bands around Sprint-3 auto)."""
    historicals = historicals or []

    # Pull relevant history per driver.
    audited = [
        h for h in historicals
        if getattr(h, "audit_status", None) is not None
        and str(h.audit_status.value) in ("audited", "reviewed")
    ]

    if implied.implied_value is None:
        return PlausibilityAssessment(
            driver=implied.solve_for,
            implied_value=Decimal("0"),
            baseline_value=implied.baseline_value,
            plausibility="VERY_LOW",
            rationale=(
                f"Solver did not converge within "
                f"{implied.bracket_tested} bracket; market price cannot "
                "be reconciled with this driver alone."
            ),
        )

    if implied.solve_for == "operating_margin":
        values = [
            h.operating_margin_reported
            for h in audited
            if getattr(h, "operating_margin_reported", None) is not None
        ]
        # HistoricalRecord stores operating margins as percentages (e.g. 16.2)
        values_frac = [v / Decimal("100") for v in values]
        return _margin_like_plausibility(implied, values_frac, "operating margin")

    if implied.solve_for == "terminal_growth" or implied.solve_for == "revenue_growth_terminal":
        return _growth_plausibility(implied)

    if implied.solve_for == "wacc":
        return _wacc_plausibility(implied, auto_wacc=auto_wacc)

    if implied.solve_for == "capex_intensity":
        values = [
            h.capex_revenue_ratio / Decimal("100")
            for h in audited
            if getattr(h, "capex_revenue_ratio", None) is not None
        ]
        return _capex_plausibility(implied, values)

    return PlausibilityAssessment(
        driver=implied.solve_for,
        implied_value=implied.implied_value,
        baseline_value=implied.baseline_value,
        plausibility="MODERATE",
        rationale="No driver-specific heuristic — defaulting to MODERATE.",
    )


def _margin_like_plausibility(
    implied: ImpliedValue, historical_fracs: list[Decimal], label: str
) -> PlausibilityAssessment:
    if not historical_fracs:
        return PlausibilityAssessment(
            driver=implied.solve_for,
            implied_value=implied.implied_value or Decimal("0"),
            baseline_value=implied.baseline_value,
            plausibility="MODERATE",
            rationale=(
                f"No historical {label} data available — plausibility "
                "cannot be anchored against company evidence."
            ),
        )
    implied_val = implied.implied_value  # guaranteed non-None above
    assert implied_val is not None
    lo = min(historical_fracs)
    hi = max(historical_fracs)
    mean = sum(historical_fracs, start=Decimal("0")) / Decimal(len(historical_fracs))
    if implied_val >= lo:
        plaus = "HIGH"
        rationale = (
            f"Implied {implied_val * 100:.2f}% within historical range "
            f"[{lo * 100:.2f}%, {hi * 100:.2f}%] (mean {mean * 100:.2f}%)."
        )
    elif implied_val >= lo * Decimal("0.8"):
        plaus = "MODERATE"
        rationale = (
            f"Implied {implied_val * 100:.2f}% slightly below historical "
            f"floor ({lo * 100:.2f}%)."
        )
    elif implied_val >= lo * Decimal("0.5"):
        plaus = "LOW"
        rationale = (
            f"Implied {implied_val * 100:.2f}% substantially below historical "
            f"floor ({lo * 100:.2f}%); requires persistent compression not seen "
            "in the audited history."
        )
    else:
        plaus = "VERY_LOW"
        rationale = (
            f"Implied {implied_val * 100:.2f}% less than half the historical "
            f"floor ({lo * 100:.2f}%); implies structural break from company "
            "track record."
        )
    return PlausibilityAssessment(
        driver=implied.solve_for,
        implied_value=implied_val,
        baseline_value=implied.baseline_value,
        historical_range=(lo, hi),
        historical_mean=mean,
        latest_audited=historical_fracs[-1],
        plausibility=plaus,  # type: ignore[arg-type]
        rationale=rationale,
    )


def _growth_plausibility(implied: ImpliedValue) -> PlausibilityAssessment:
    implied_val = implied.implied_value
    assert implied_val is not None
    if implied_val >= Decimal("0.02"):
        plaus, rationale = "HIGH", (
            f"Implied growth {implied_val * 100:.2f}% in line with typical "
            "mature-stage rates (~2-3 %)."
        )
    elif implied_val >= Decimal("0"):
        plaus, rationale = "MODERATE", (
            f"Implied growth {implied_val * 100:.2f}% below inflation but "
            "non-negative; plausible for a decelerating business."
        )
    elif implied_val >= Decimal("-0.02"):
        plaus, rationale = "LOW", (
            f"Implied growth {implied_val * 100:.2f}% negative — prices persistent "
            "nominal decline."
        )
    else:
        plaus, rationale = "VERY_LOW", (
            f"Implied growth {implied_val * 100:.2f}% deeply negative; implies "
            "secular liquidation premium baked into market price."
        )
    return PlausibilityAssessment(
        driver=implied.solve_for,
        implied_value=implied_val,
        baseline_value=implied.baseline_value,
        plausibility=plaus,  # type: ignore[arg-type]
        rationale=rationale,
    )


def _wacc_plausibility(
    implied: ImpliedValue, *, auto_wacc: Decimal | None
) -> PlausibilityAssessment:
    implied_val = implied.implied_value
    assert implied_val is not None
    base = auto_wacc if auto_wacc is not None else implied.baseline_value
    delta_bps = (implied_val - base) * _BPS
    abs_delta = abs(delta_bps)
    if abs_delta <= Decimal("200"):
        plaus = "HIGH"
        rationale = (
            f"Implied WACC {implied_val * 100:.2f}% within ±200 bps of "
            f"auto/baseline {base * 100:.2f}%."
        )
    elif abs_delta <= Decimal("400"):
        plaus = "MODERATE"
        rationale = (
            f"Implied WACC {implied_val * 100:.2f}% {delta_bps:+.0f} bps vs "
            f"auto {base * 100:.2f}% — explainable by modest idiosyncratic risk."
        )
    elif abs_delta <= Decimal("600"):
        plaus = "LOW"
        rationale = (
            f"Implied WACC {implied_val * 100:.2f}% {delta_bps:+.0f} bps vs "
            f"auto {base * 100:.2f}% — demands a substantial risk premium."
        )
    else:
        plaus = "VERY_LOW"
        rationale = (
            f"Implied WACC {implied_val * 100:.2f}% {delta_bps:+.0f} bps vs "
            f"auto {base * 100:.2f}% — risk premium implausible without a "
            "distressed scenario."
        )
    return PlausibilityAssessment(
        driver=implied.solve_for,
        implied_value=implied_val,
        baseline_value=implied.baseline_value,
        plausibility=plaus,  # type: ignore[arg-type]
        rationale=rationale,
    )


def _capex_plausibility(
    implied: ImpliedValue, historical_fracs: list[Decimal]
) -> PlausibilityAssessment:
    implied_val = implied.implied_value
    assert implied_val is not None
    if not historical_fracs:
        return PlausibilityAssessment(
            driver=implied.solve_for,
            implied_value=implied_val,
            baseline_value=implied.baseline_value,
            plausibility="MODERATE",
            rationale=(
                "No historical capex-intensity data available — "
                "plausibility cannot be anchored against company evidence."
            ),
        )
    mean = sum(historical_fracs, start=Decimal("0")) / Decimal(len(historical_fracs))
    if implied_val <= mean * Decimal("1.2"):
        plaus, rationale = "HIGH", (
            f"Implied capex intensity {implied_val * 100:.2f}% within 20 % of "
            f"historical mean ({mean * 100:.2f}%)."
        )
    elif implied_val <= mean * Decimal("1.5"):
        plaus, rationale = "MODERATE", (
            f"Implied capex intensity {implied_val * 100:.2f}% elevated vs "
            f"historical mean ({mean * 100:.2f}%)."
        )
    elif implied_val <= mean * Decimal("2"):
        plaus, rationale = "LOW", (
            f"Implied capex intensity {implied_val * 100:.2f}% substantially "
            f"above historical mean ({mean * 100:.2f}%)."
        )
    else:
        plaus, rationale = "VERY_LOW", (
            f"Implied capex intensity {implied_val * 100:.2f}% more than 2× "
            f"historical mean ({mean * 100:.2f}%)."
        )
    return PlausibilityAssessment(
        driver=implied.solve_for,
        implied_value=implied_val,
        baseline_value=implied.baseline_value,
        historical_range=(min(historical_fracs), max(historical_fracs)),
        historical_mean=mean,
        plausibility=plaus,  # type: ignore[arg-type]
        rationale=rationale,
    )


__all__ = [
    "ImpliedValue",
    "PlausibilityAssessment",
    "ReverseDCFReport",
    "ReverseDCFSolver",
    "assess_plausibility",
]
