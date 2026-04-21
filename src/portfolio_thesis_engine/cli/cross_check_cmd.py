"""``pte cross-check`` — re-run the cross-check gate for a ticker.

This is primarily a debugging tool: the production pipeline runs the
gate as part of ``pte process``. Here, operators pass the extracted
metrics explicitly via ``--values-json`` and get a rich table plus the
JSON log path.

Usage::

    pte cross-check 1846.HK \\
      --period FY2024 \\
      --values-json '{"revenue": "580", "operating_income": "110", ...}'
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal, InvalidOperation

import typer
from rich.console import Console
from rich.table import Table

from portfolio_thesis_engine.cross_check import CrossCheckGate, CrossCheckStatus
from portfolio_thesis_engine.market_data.fmp_provider import FMPProvider
from portfolio_thesis_engine.market_data.yfinance_provider import YFinanceProvider

console = Console()


_STATUS_STYLE = {
    CrossCheckStatus.PASS: "[green]PASS[/green]",
    CrossCheckStatus.WARN: "[yellow]WARN[/yellow]",
    CrossCheckStatus.FAIL: "[red]FAIL[/red]",
    CrossCheckStatus.SOURCES_DISAGREE: "[yellow]SOURCES_DISAGREE[/yellow]",
    CrossCheckStatus.UNAVAILABLE: "[dim]—[/dim]",
}


def _parse_values(values_json: str) -> dict[str, Decimal]:
    try:
        raw = json.loads(values_json)
    except json.JSONDecodeError as e:
        raise typer.BadParameter(f"--values-json is not valid JSON: {e}") from e
    if not isinstance(raw, dict):
        raise typer.BadParameter("--values-json must be a JSON object")
    out: dict[str, Decimal] = {}
    for key, value in raw.items():
        try:
            out[str(key)] = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError) as e:
            raise typer.BadParameter(
                f"--values-json: value for {key!r} is not a number: {value!r}"
            ) from e
    return out


def cross_check(
    ticker: str = typer.Argument(..., help="Target ticker (e.g. 1846.HK)."),
    period: str = typer.Option(
        "FY?",
        "--period",
        "-p",
        help="Period label for the report (e.g. FY2024, H1 2025).",
    ),
    values_json: str = typer.Option(
        "{}",
        "--values-json",
        "-v",
        help="JSON object mapping metric names to extracted numeric values.",
    ),
    override_thresholds: str = typer.Option(
        "",
        "--override-thresholds",
        help="JSON override for thresholds (see cross_check/thresholds.py).",
    ),
) -> None:
    """Re-run the cross-check gate for a ticker using supplied values."""
    extracted = _parse_values(values_json)
    overrides = override_thresholds.strip() or None

    async def _run() -> None:
        async with FMPProvider() as fmp:
            yfinance = YFinanceProvider()
            gate = CrossCheckGate(fmp, yfinance, thresholds_override_json=overrides)
            report = await gate.check(ticker=ticker, extracted_values=extracted, period=period)

        table = Table(show_header=True, header_style="bold magenta")
        table.add_column("Metric")
        table.add_column("Status")
        table.add_column("Δ", justify="right")
        table.add_column("Extracted", justify="right")
        table.add_column("FMP", justify="right")
        table.add_column("yfinance", justify="right")
        table.add_column("Notes", overflow="fold")

        for m in report.metrics:
            table.add_row(
                m.metric,
                _STATUS_STYLE.get(m.status, m.status.value),
                f"{m.max_delta_pct:.2%}" if m.max_delta_pct is not None else "—",
                str(m.extracted_value) if m.extracted_value is not None else "—",
                str(m.fmp_value) if m.fmp_value is not None else "—",
                str(m.yfinance_value) if m.yfinance_value is not None else "—",
                m.notes,
            )
        console.print(table)

        overall_style = _STATUS_STYLE.get(report.overall_status, report.overall_status.value)
        console.print(f"\n[bold]Overall:[/bold] {overall_style}")
        if report.blocking:
            console.print("[red]Pipeline would BLOCK — extraction needs review.[/red]")
        if report.provider_errors:
            console.print("\n[yellow]Provider errors:[/yellow]")
            for label, err in report.provider_errors.items():
                console.print(f"  • {label}: {err}")
        if report.log_path:
            console.print(f"\n[dim]log: {report.log_path}[/dim]")

        if report.blocking:
            raise typer.Exit(code=1)

    asyncio.run(_run())
