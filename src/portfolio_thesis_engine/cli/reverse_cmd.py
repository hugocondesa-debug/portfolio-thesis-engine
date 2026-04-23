"""Phase 2 Sprint 4A-alpha.4 — ``pte reverse <ticker>`` CLI.

Runs :class:`ReverseDCFSolver` against the same inputs the forward DCF
uses (Sprint-3 auto WACC + scenario.yaml + valuation_profile.yaml).
Two modes:

- ``--solve-for <driver>``: single-driver mode (detailed section with
  evidence comparison).
- ``--enumerate``: matrix mode (all supported drivers in a single
  table, each with its plausibility rating).
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from portfolio_thesis_engine.analytical.historicals import (
    HistoricalNormalizer,
)
from portfolio_thesis_engine.dcf.orchestrator import DCFOrchestrator
from portfolio_thesis_engine.dcf.profiles import load_valuation_profile
from portfolio_thesis_engine.dcf.reverse import (
    ImpliedValue,
    PlausibilityAssessment,
    ReverseDCFReport,
    ReverseDCFSolver,
    assess_plausibility,
)
from portfolio_thesis_engine.dcf.scenarios import load_scenarios

console = Console()


# ---------------------------------------------------------------------------
# Context assembly
# ---------------------------------------------------------------------------
def _prepare_context(ticker: str) -> dict[str, Any] | None:
    """Load everything a reverse-DCF run needs for ``ticker``. Returns
    ``None`` when the ticker is missing canonical state or scenarios."""
    orch = DCFOrchestrator()
    state = orch._latest_canonical_state(ticker)  # noqa: SLF001
    if state is None:
        return None
    scenario_set = load_scenarios(ticker)
    if scenario_set is None:
        return None
    valuation_profile = load_valuation_profile(ticker)
    stage_1 = orch._stage_1_wacc(ticker, state)  # noqa: SLF001
    stage_3 = orch._stage_3_wacc(  # noqa: SLF001
        state, valuation_profile, stage_1
    )
    period_inputs = orch._period_inputs(  # noqa: SLF001
        ticker=ticker,
        state=state,
        stage_1_wacc=stage_1,
        stage_3_wacc=stage_3,
        valuation_profile=valuation_profile,
    )
    peer_comparison = orch._load_peer_comparison(ticker)  # noqa: SLF001
    try:
        historicals = HistoricalNormalizer().normalize(ticker).records
    except Exception:
        historicals = []
    return {
        "ticker": ticker,
        "state": state,
        "scenario_set": scenario_set,
        "valuation_profile": valuation_profile,
        "period_inputs": period_inputs,
        "peer_comparison": peer_comparison,
        "historicals": historicals,
        "stage_1_wacc": stage_1,
    }


def _forward_fv(ctx: dict[str, Any], scenario_name: str) -> tuple[Decimal, Any]:
    """Run the forward DCF for ``scenario_name`` and return
    ``(fair_value_per_share, scenario_obj)`` so the reverse caller can
    display the forward anchor."""
    from portfolio_thesis_engine.dcf.engine import ValuationEngine

    scenario = next(
        (s for s in ctx["scenario_set"].scenarios if s.name == scenario_name),
        None,
    )
    if scenario is None:
        raise ValueError(
            f"Scenario '{scenario_name}' not found for {ctx['ticker']}"
        )
    result = ValuationEngine().run(
        valuation_profile=ctx["valuation_profile"],
        scenario_set=ctx["scenario_set"],
        period_inputs=ctx["period_inputs"],
        peer_comparison=ctx["peer_comparison"],
    )
    match = next(
        (v for v in result.scenarios_run if v.scenario_name == scenario_name),
        None,
    )
    if match is None:
        raise ValueError(
            f"Forward engine produced no output for scenario '{scenario_name}'"
        )
    return match.fair_value_per_share, scenario


# ---------------------------------------------------------------------------
# Solver driver
# ---------------------------------------------------------------------------
def _run_solve(
    ctx: dict[str, Any],
    scenario_name: str,
    target_fv: Decimal,
    drivers: list[str],
) -> list[ImpliedValue]:
    solver = ReverseDCFSolver()
    scenario = next(
        (s for s in ctx["scenario_set"].scenarios if s.name == scenario_name),
        None,
    )
    if scenario is None:
        raise ValueError(f"Scenario '{scenario_name}' not found")
    results = []
    for driver in drivers:
        implied = solver.solve(
            scenario=scenario,
            valuation_profile=ctx["valuation_profile"],
            period_inputs=ctx["period_inputs"],
            base_drivers=ctx["scenario_set"].base_drivers,
            peer_comparison=ctx["peer_comparison"],
            solve_for=driver,
            target_fv=target_fv,
        )
        results.append(implied)
    return results


# ---------------------------------------------------------------------------
# Rendering helpers
# ---------------------------------------------------------------------------
def _fmt_pct(value: Decimal | None, *, sign: bool = False) -> str:
    if value is None:
        return "—"
    return (
        f"{value * Decimal('100'):+.2f}%"
        if sign
        else f"{value * Decimal('100'):.2f}%"
    )


def _fmt_bps(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"{value * Decimal('10000'):+.0f} bps"


def _enumerate_table(
    results: list[ImpliedValue],
    plausibilities: list[PlausibilityAssessment],
) -> Table:
    table = Table(
        title="Reverse DCF — implied values to reproduce target price",
        title_style="bold cyan",
    )
    table.add_column("Driver")
    table.add_column("Baseline", justify="right")
    table.add_column("Implied", justify="right")
    table.add_column("Gap", justify="right")
    table.add_column("Plausibility")
    for implied, plaus in zip(results, plausibilities, strict=True):
        table.add_row(
            implied.display_name,
            _fmt_pct(implied.baseline_value),
            _fmt_pct(implied.implied_value) if implied.implied_value is not None else "—",
            _fmt_bps(implied.gap_vs_baseline),
            plaus.plausibility,
        )
    return table


def _single_driver_section(
    implied: ImpliedValue, plaus: PlausibilityAssessment
) -> list[str]:
    lines = [f"[bold cyan]Solving for: {implied.display_name}[/bold cyan]"]
    if implied.implied_value is None:
        lines.append(
            f"  Convergence: [red]{implied.convergence}[/red] "
            f"(bracket {implied.bracket_tested})"
        )
        lines.append(
            f"  → No value in the tested range reproduces the target "
            "price. Market-implied scenario requires a combination of "
            "driver changes (run `--enumerate` for the full matrix)."
        )
        return lines
    lines.append(
        f"  Implied {implied.solve_for}: "
        f"[bold]{_fmt_pct(implied.implied_value)}[/bold]"
    )
    lines.append(f"  Base scenario value: {_fmt_pct(implied.baseline_value)}")
    lines.append(f"  Gap: {_fmt_bps(implied.gap_vs_baseline)}")
    if plaus.historical_range is not None:
        lo, hi = plaus.historical_range
        lines.append(
            f"  Historical range: {_fmt_pct(lo)} – {_fmt_pct(hi)}"
        )
    if plaus.historical_mean is not None:
        lines.append(f"  Historical mean: {_fmt_pct(plaus.historical_mean)}")
    lines.append(f"  Plausibility: [bold]{plaus.plausibility}[/bold]")
    lines.append(f"  {plaus.rationale}")
    return lines


# ---------------------------------------------------------------------------
# Markdown export
# ---------------------------------------------------------------------------
def render_reverse_markdown(report: ReverseDCFReport) -> str:
    lines: list[str] = [
        f"# {report.ticker} — Reverse DCF Analysis",
        "",
        f"Generated: {report.generated_at.date().isoformat()}",
        f"Scenario: **{report.scenario_name}** ({report.methodology})",
        f"Forward DCF FV/share: {report.forward_fv:,.2f}",
        f"Target price: {report.target_fv:,.2f}",
    ]
    if report.market_price is not None:
        lines.append(f"Market price: {report.market_price:,.2f}")
    lines.extend([
        "",
        "## Single-driver implied values",
        "",
        "| Driver | Baseline | Implied | Gap | Plausibility |",
        "|---|---:|---:|---:|---|",
    ])
    for implied, plaus in zip(
        report.implied_values, report.plausibility, strict=True
    ):
        impl_str = (
            _fmt_pct(implied.implied_value)
            if implied.implied_value is not None
            else f"— ({implied.convergence})"
        )
        lines.append(
            f"| {implied.display_name} | {_fmt_pct(implied.baseline_value)} | "
            f"{impl_str} | {_fmt_bps(implied.gap_vs_baseline)} | "
            f"{plaus.plausibility} |"
        )
    lines.extend(["", "## Evidence + rationale", ""])
    for implied, plaus in zip(
        report.implied_values, report.plausibility, strict=True
    ):
        lines.append(f"### {implied.display_name}")
        lines.append("")
        lines.append(f"- Convergence: {implied.convergence}")
        if implied.implied_value is not None:
            lines.append(
                f"- Implied: {_fmt_pct(implied.implied_value)} "
                f"(baseline {_fmt_pct(implied.baseline_value)}, "
                f"gap {_fmt_bps(implied.gap_vs_baseline)})"
            )
        else:
            lines.append(
                f"- Implied: not reachable within "
                f"{implied.bracket_tested} bracket"
            )
        lines.append(f"- Plausibility: **{plaus.plausibility}**")
        lines.append(f"- Rationale: {plaus.rationale}")
        lines.append("")
    # Conclusion
    lines.extend([
        "## Conclusion",
        "",
    ])
    high_plaus = [p for p in report.plausibility if p.plausibility == "HIGH"]
    low_plaus = [
        p for p in report.plausibility
        if p.plausibility in ("LOW", "VERY_LOW")
    ]
    if not high_plaus and low_plaus:
        lines.append(
            "- No single realistic driver change reproduces the target "
            "price. Market price consistent only with combinations of "
            "adverse assumptions, each individually implausible given "
            "company evidence."
        )
    elif high_plaus:
        lines.append(
            "- At least one single-driver solve is HIGH plausibility — "
            "market price can be reconciled without demanding implausible "
            "combinations."
        )
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Runner + typer entry
# ---------------------------------------------------------------------------
def _run_reverse(
    ticker: str,
    *,
    solve_for: str | None,
    enumerate_all: bool,
    scenario_name: str,
    target_price: Decimal | None,
    export: Path | None,
) -> None:
    ctx = _prepare_context(ticker)
    if ctx is None:
        console.print(
            f"[yellow]No canonical state or scenarios for {ticker}.[/yellow]"
        )
        raise typer.Exit(code=1)

    market_price = target_price or ctx["period_inputs"].market_price
    if market_price is None:
        console.print(
            "[yellow]No market price available for reverse DCF. "
            "Pass --target <price> or populate wacc_inputs.md.[/yellow]"
        )
        raise typer.Exit(code=1)

    forward_fv, scenario = _forward_fv(ctx, scenario_name)
    methodology = scenario.methodology.type if hasattr(scenario.methodology, "type") else "UNKNOWN"

    console.print(f"[bold]{ticker} — Reverse DCF[/bold]")
    console.print(
        f"  Market/target price: {market_price:,.2f}   "
        f"Scenario: {scenario_name} ({methodology})   "
        f"Forward FV: {forward_fv:,.2f}"
    )
    console.print("")

    # Select drivers
    solver = ReverseDCFSolver()
    if enumerate_all:
        drivers = list(solver.SUPPORTED_DRIVERS)
    elif solve_for is not None:
        if solve_for not in solver.SUPPORTED_DRIVERS:
            console.print(
                f"[red]Unsupported driver '{solve_for}'.[/red] "
                f"Choose from {list(solver.SUPPORTED_DRIVERS)}."
            )
            raise typer.Exit(code=2)
        drivers = [solve_for]
    else:
        console.print(
            "[yellow]Pass --solve-for <driver> or --enumerate.[/yellow]"
        )
        raise typer.Exit(code=2)

    implieds = _run_solve(ctx, scenario_name, market_price, drivers)
    plausibilities = [
        assess_plausibility(
            implied,
            historicals=ctx["historicals"],
            auto_wacc=ctx["stage_1_wacc"],
        )
        for implied in implieds
    ]

    if enumerate_all:
        console.print(_enumerate_table(implieds, plausibilities))
    else:
        for line in _single_driver_section(implieds[0], plausibilities[0]):
            console.print(line)

    report = ReverseDCFReport(
        ticker=ticker,
        scenario_name=scenario_name,
        methodology=methodology,
        market_price=market_price,
        forward_fv=forward_fv,
        target_fv=market_price,
        implied_values=implieds,
        plausibility=plausibilities,
    )

    if export is not None:
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_text(render_reverse_markdown(report), encoding="utf-8")
        console.print(f"\n[dim]Reverse DCF report written to {export}[/dim]")


def reverse(
    ticker: str = typer.Argument(..., help="Target ticker (e.g. 1846.HK)."),
    solve_for: str | None = typer.Option(
        None,
        "--solve-for",
        help="Driver to solve for: operating_margin, terminal_growth, "
        "wacc, revenue_growth_terminal, capex_intensity.",
    ),
    enumerate_all: bool = typer.Option(
        False,
        "--enumerate",
        help="Solve all supported drivers and render the matrix.",
    ),
    scenario: str = typer.Option(
        "base", "--scenario", help="Scenario to reverse-solve against."
    ),
    target: float | None = typer.Option(
        None, "--target", help="Target price (defaults to market price)."
    ),
    export: Path | None = typer.Option(
        None, "--export", help="Write markdown report to PATH."
    ),
) -> None:
    """Solve the reverse DCF — what assumptions must the market price
    be implying, versus the analyst's base scenario?"""
    target_decimal = Decimal(str(target)) if target is not None else None
    _run_reverse(
        ticker,
        solve_for=solve_for,
        enumerate_all=enumerate_all,
        scenario_name=scenario,
        target_price=target_decimal,
        export=export,
    )


__all__ = [
    "_run_reverse",
    "render_reverse_markdown",
    "reverse",
]
