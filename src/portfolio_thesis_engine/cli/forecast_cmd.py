"""Phase 2 Sprint 4A-beta — ``pte forecast`` command.

Generates per-scenario three-statement forecasts for a ticker,
renders them as rich tables, optionally exports a markdown report,
and persists the full result as JSON under
``data/forecast_snapshots/{ticker}/``.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from portfolio_thesis_engine.forecast import (
    ForecastOrchestrator,
    ForecastResult,
    persist_forecast,
)

console = Console()


def forecast(
    ticker: str = typer.Argument(..., help="Target ticker (e.g. 1846.HK)"),
    scenario: str | None = typer.Option(
        None, "--scenario", help="Restrict output to a single scenario name"
    ),
    export: Path | None = typer.Option(
        None, "--export", help="Write a Markdown summary to this path"
    ),
    years: int = typer.Option(5, "--years", help="Projection horizon in years"),
    no_persist: bool = typer.Option(
        False, "--no-persist", help="Skip writing the JSON snapshot"
    ),
) -> None:
    """Produce a three-statement forecast across all scenarios."""
    orchestrator = ForecastOrchestrator()
    result = orchestrator.run(ticker, years=years)

    if result is None:
        console.print(
            f"[yellow]No canonical state or scenarios.yaml for {ticker}.[/yellow] "
            f"Run [bold]pte process {ticker}[/bold] + generate scenarios first."
        )
        raise typer.Exit(1)

    if scenario is not None:
        result = result.model_copy(
            update={
                "projections": [
                    p for p in result.projections if p.scenario_name == scenario
                ]
            }
        )
        if not result.projections:
            console.print(f"[yellow]No scenario named '{scenario}'.[/yellow]")
            raise typer.Exit(1)

    _render_forecast(result)

    if not no_persist:
        path = persist_forecast(result)
        console.print(f"[dim]Snapshot written to {path}[/dim]")

    if export is not None:
        markdown = _render_forecast_markdown(result)
        export.write_text(markdown)
        console.print(f"[dim]Markdown written to {export}[/dim]")


def _fmt_money(x: Decimal) -> str:
    return f"{x:,.0f}"


def _fmt_pct(x: Decimal) -> str:
    return f"{x * 100:.2f}%"


def _fmt_ratio(x: Decimal | None) -> str:
    if x is None:
        return "—"
    return f"{x:.2f}"


def _render_forecast(result: ForecastResult) -> None:
    console.print(
        f"[bold]{result.ticker}[/bold] — three-statement forecast "
        f"({len(result.projections)} scenarios, generated {result.generated_at})"
    )

    for projection in result.projections:
        header = (
            f"[bold cyan]{projection.scenario_name}[/bold cyan] "
            f"(p={projection.scenario_probability:.2f}, "
            f"base={projection.base_year_label})"
        )
        console.print(f"\n{header}")

        is_table = Table(title="Income Statement")
        is_table.add_column("Y")
        is_table.add_column("Revenue", justify="right")
        is_table.add_column("OI margin", justify="right")
        is_table.add_column("Operating income", justify="right")
        is_table.add_column("Net income", justify="right")
        is_table.add_column("EPS", justify="right")
        for y in projection.income_statement:
            is_table.add_row(
                f"Y{y.year}",
                _fmt_money(y.revenue),
                _fmt_pct(y.operating_margin),
                _fmt_money(y.operating_income),
                _fmt_money(y.net_income),
                f"{y.eps:.3f}",
            )
        console.print(is_table)

        bs_table = Table(title="Balance Sheet")
        bs_table.add_column("Y")
        bs_table.add_column("PPE", justify="right")
        bs_table.add_column("Goodwill", justify="right")
        bs_table.add_column("WC (net)", justify="right")
        bs_table.add_column("Cash", justify="right")
        bs_table.add_column("Debt", justify="right")
        bs_table.add_column("Equity", justify="right")
        for y in projection.balance_sheet:
            bs_table.add_row(
                f"Y{y.year}",
                _fmt_money(y.ppe_net),
                _fmt_money(y.goodwill),
                _fmt_money(y.working_capital_net),
                _fmt_money(y.cash),
                _fmt_money(y.debt),
                _fmt_money(y.equity),
            )
        console.print(bs_table)

        cf_table = Table(title="Cash Flow")
        cf_table.add_column("Y")
        cf_table.add_column("CFO", justify="right")
        cf_table.add_column("CFI", justify="right")
        cf_table.add_column("CFF", justify="right")
        cf_table.add_column("Δcash", justify="right")
        for y in projection.cash_flow:
            cf_table.add_row(
                f"Y{y.year}",
                _fmt_money(y.cfo),
                _fmt_money(y.cfi),
                _fmt_money(y.cff),
                _fmt_money(y.net_change_cash),
            )
        console.print(cf_table)

        ratios_table = Table(title="Forward ratios")
        ratios_table.add_column("Y")
        ratios_table.add_column("PER (mkt)", justify="right")
        ratios_table.add_column("FCF yield", justify="right")
        ratios_table.add_column("ROIC", justify="right")
        ratios_table.add_column("ROE", justify="right")
        ratios_table.add_column("WACC", justify="right")
        for r in projection.forward_ratios:
            ratios_table.add_row(
                f"Y{r.year}",
                _fmt_ratio(r.per_at_market_price),
                _fmt_pct(r.fcf_yield_at_market) if r.fcf_yield_at_market else "—",
                _fmt_pct(r.roic) if r.roic else "—",
                _fmt_pct(r.roe) if r.roe else "—",
                _fmt_pct(r.wacc_applied) if r.wacc_applied else "—",
            )
        console.print(ratios_table)

        if projection.solver_convergence.get("converged"):
            console.print(
                f"[green]Solver converged in "
                f"{projection.solver_convergence.get('iterations')} "
                f"iterations[/green]"
            )
        else:
            residual = projection.solver_convergence.get("final_residual")
            residual_str = f"{residual:.4f}" if residual is not None else "n/a"
            console.print(
                f"[yellow]Solver did not converge; residual = {residual_str}"
                f"[/yellow]"
            )

        for warning in projection.warnings:
            console.print(f"[yellow]⚠ {warning}[/yellow]")


def _render_forecast_markdown(result: ForecastResult) -> str:
    lines: list[str] = []
    lines.append(f"# {result.ticker} — Three-Statement Forecast")
    lines.append("")
    lines.append(f"- Generated: {result.generated_at}")
    lines.append(f"- Scenarios: {len(result.projections)}")
    if result.expected_forward_eps_y1 is not None:
        lines.append(
            f"- Expected Y1 EPS (probability-weighted): "
            f"{result.expected_forward_eps_y1:.4f}"
        )
    lines.append("")

    for projection in result.projections:
        lines.append(
            f"## {projection.scenario_name} "
            f"(p={projection.scenario_probability:.2f}, "
            f"base={projection.base_year_label})"
        )
        lines.append("")

        lines.append("### Income Statement")
        lines.append("| Year | Revenue | OI margin | OI | NI | EPS |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for y in projection.income_statement:
            lines.append(
                f"| Y{y.year} | {_fmt_money(y.revenue)} | "
                f"{_fmt_pct(y.operating_margin)} | "
                f"{_fmt_money(y.operating_income)} | "
                f"{_fmt_money(y.net_income)} | {y.eps:.3f} |"
            )
        lines.append("")

        lines.append("### Balance Sheet")
        lines.append("| Year | PPE | Goodwill | WC | Cash | Debt | Equity |")
        lines.append("|---|---:|---:|---:|---:|---:|---:|")
        for y in projection.balance_sheet:
            lines.append(
                f"| Y{y.year} | {_fmt_money(y.ppe_net)} | "
                f"{_fmt_money(y.goodwill)} | "
                f"{_fmt_money(y.working_capital_net)} | "
                f"{_fmt_money(y.cash)} | {_fmt_money(y.debt)} | "
                f"{_fmt_money(y.equity)} |"
            )
        lines.append("")

        lines.append("### Cash Flow")
        lines.append("| Year | CFO | CFI | CFF | Δcash |")
        lines.append("|---|---:|---:|---:|---:|")
        for y in projection.cash_flow:
            lines.append(
                f"| Y{y.year} | {_fmt_money(y.cfo)} | "
                f"{_fmt_money(y.cfi)} | {_fmt_money(y.cff)} | "
                f"{_fmt_money(y.net_change_cash)} |"
            )
        lines.append("")

        lines.append("### Forward ratios")
        lines.append("| Year | PER (mkt) | FCF yield | ROIC | ROE | WACC |")
        lines.append("|---|---:|---:|---:|---:|---:|")
        for r in projection.forward_ratios:
            lines.append(
                f"| Y{r.year} | {_fmt_ratio(r.per_at_market_price)} | "
                f"{_fmt_pct(r.fcf_yield_at_market) if r.fcf_yield_at_market else '—'} | "
                f"{_fmt_pct(r.roic) if r.roic else '—'} | "
                f"{_fmt_pct(r.roe) if r.roe else '—'} | "
                f"{_fmt_pct(r.wacc_applied) if r.wacc_applied else '—'} |"
            )
        lines.append("")

        conv = projection.solver_convergence
        lines.append(
            f"**Solver**: "
            f"{'converged' if conv.get('converged') else 'not converged'}; "
            f"iterations={conv.get('iterations')}, "
            f"residual={conv.get('final_residual')}"
        )
        lines.append("")

    return "\n".join(lines)


__all__ = ["forecast"]
