"""Phase 2 Sprint 1 — ``pte historicals <ticker>`` CLI.

Builds a :class:`CompanyTimeSeries` via :class:`HistoricalNormalizer`
and renders it in Rich tables (stdout). When ``--export PATH`` is
passed, also writes a markdown report to ``PATH``.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from portfolio_thesis_engine.analytical.historicals import (
    HistoricalNormalizer,
)
from portfolio_thesis_engine.schemas.historicals import (
    CompanyTimeSeries,
    FiscalYearChangeEvent,
    HistoricalRecord,
    NarrativeTimeline,
    RestatementEvent,
)

console = Console()


def _fmt_money(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, Decimal):
        return f"{value:,.0f}"
    return str(value)


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}%"


def _render_periods_table(ts: CompanyTimeSeries) -> Table:
    table = Table(
        title=f"{ts.ticker} — Historical time-series",
        title_style="bold magenta",
    )
    table.add_column("Period")
    table.add_column("End", justify="right")
    table.add_column("Type")
    table.add_column("Audit")
    table.add_column("Revenue", justify="right")
    table.add_column("Op Income", justify="right")
    table.add_column("NOPAT", justify="right")
    table.add_column("ROIC", justify="right")
    table.add_column("Source")
    for r in ts.records:
        table.add_row(
            r.period,
            r.period_end.isoformat(),
            r.period_type.value,
            r.audit_status.value,
            _fmt_money(r.revenue),
            _fmt_money(r.operating_income),
            _fmt_money(r.nopat),
            _fmt_pct(r.roic_primary),
            str(r.source_document_type),
        )
    return table


def _render_restatements(events: list[RestatementEvent]) -> Table | None:
    if not events:
        return None
    table = Table(
        title="Restatement events",
        title_style="bold red",
    )
    table.add_column("Period")
    table.add_column("Metric")
    table.add_column("Class")
    table.add_column("From (unaudited)", justify="right")
    table.add_column("To (audited)", justify="right")
    table.add_column("Δ%", justify="right")
    table.add_column("Direction")
    table.add_column("Severity")
    for e in events:
        table.add_row(
            e.period,
            e.metric,
            e.metric_class,
            _fmt_money(e.source_a_value),
            _fmt_money(e.source_b_value),
            _fmt_pct(e.delta_pct),
            e.direction or "—",
            e.severity,
        )
    return table


def _render_fiscal_year_changes(
    events: list[FiscalYearChangeEvent],
) -> Table | None:
    if not events:
        return None
    table = Table(
        title="Fiscal-year changes",
        title_style="bold yellow",
    )
    table.add_column("At period")
    table.add_column("Previous FY end")
    table.add_column("New FY end")
    table.add_column("Transition months")
    for e in events:
        table.add_row(
            e.detected_at_period,
            e.previous_fiscal_year_end,
            e.new_fiscal_year_end,
            str(e.transition_period_months),
        )
    return table


def _render_narrative_timeline(
    timeline: NarrativeTimeline,
) -> list[str]:
    lines: list[str] = []
    if timeline.themes_evolution:
        lines.append("[bold]Themes[/bold]")
        for t in timeline.themes_evolution:
            flag = "✓ consistent" if t.was_consistent else "—"
            lines.append(
                f"  • {t.theme_text} [{', '.join(t.periods_mentioned)}] {flag}"
            )
        lines.append("")
    if timeline.risks_evolution:
        lines.append("[bold]Risks[/bold]")
        for r in timeline.risks_evolution:
            flag = "✓ consistent" if r.was_consistent else "—"
            lines.append(
                f"  • {r.risk_text} [{', '.join(r.periods_mentioned)}] {flag}"
            )
        lines.append("")
    if timeline.guidance_evolution:
        lines.append("[bold]Guidance[/bold]")
        for g in timeline.guidance_evolution:
            flag = "✓ consistent" if g.was_consistent else "—"
            lines.append(
                f"  • {g.guidance_text} [{', '.join(g.periods_mentioned)}] {flag}"
            )
        lines.append("")
    if timeline.capital_allocation_evolution:
        lines.append("[bold]Capital allocation[/bold]")
        for c in timeline.capital_allocation_evolution:
            flag = "✓ consistent" if c.was_consistent else "—"
            lines.append(
                f"  • {c.capital_allocation_text} "
                f"[{', '.join(c.periods_mentioned)}] {flag}"
            )
    return lines


# ----------------------------------------------------------------------
# Markdown export
# ----------------------------------------------------------------------
def render_markdown_report(ts: CompanyTimeSeries) -> str:
    lines: list[str] = [
        f"# {ts.ticker} — Historical time-series",
        "",
        f"Generated: {ts.generated_at.date().isoformat()}",
        f"Source canonical_states: {len(ts.source_canonical_state_ids)}",
        "",
        "## Periods",
        "",
        "| Period | End | Type | Audit | Revenue | Op Income | NOPAT | ROIC | Source |",
        "|---|---|---|---|---:|---:|---:|---:|---|",
    ]
    for r in ts.records:
        lines.append(
            "| {period} | {end} | {ptype} | {audit} | {rev} | {oi} | "
            "{nopat} | {roic} | {src} |".format(
                period=r.period,
                end=r.period_end.isoformat(),
                ptype=r.period_type.value,
                audit=r.audit_status.value,
                rev=_fmt_money(r.revenue),
                oi=_fmt_money(r.operating_income),
                nopat=_fmt_money(r.nopat),
                roic=_fmt_pct(r.roic_primary),
                src=str(r.source_document_type),
            )
        )
    lines.extend(["", f"## Restatement events: {len(ts.restatement_events)}"])
    if ts.restatement_events:
        lines.append("")
        lines.append("| Period | Metric | From | To | Δ% |")
        lines.append("|---|---|---:|---:|---:|")
        for e in ts.restatement_events:
            lines.append(
                f"| {e.period} | {e.metric} | {_fmt_money(e.source_a_value)} | "
                f"{_fmt_money(e.source_b_value)} | {_fmt_pct(e.delta_pct)} |"
            )
    lines.extend(["", f"## Fiscal-year changes: {len(ts.fiscal_year_changes)}"])
    for e in ts.fiscal_year_changes:
        lines.append(
            f"- At {e.detected_at_period}: "
            f"{e.previous_fiscal_year_end} → {e.new_fiscal_year_end} "
            f"(transition {e.transition_period_months} months)"
        )
    lines.extend(["", "## Narrative timeline"])
    if ts.narrative_timeline.themes_evolution:
        lines.extend(["", "### Themes"])
        for t in ts.narrative_timeline.themes_evolution:
            flag = " — consistent" if t.was_consistent else ""
            lines.append(
                f"- {t.theme_text} [{', '.join(t.periods_mentioned)}]{flag}"
            )
    if ts.narrative_timeline.risks_evolution:
        lines.extend(["", "### Risks"])
        for r in ts.narrative_timeline.risks_evolution:
            flag = " — consistent" if r.was_consistent else ""
            lines.append(
                f"- {r.risk_text} [{', '.join(r.periods_mentioned)}]{flag}"
            )
    if ts.narrative_timeline.guidance_evolution:
        lines.extend(["", "### Guidance"])
        for g in ts.narrative_timeline.guidance_evolution:
            flag = " — consistent" if g.was_consistent else ""
            lines.append(
                f"- {g.guidance_text} [{', '.join(g.periods_mentioned)}]{flag}"
            )
    if ts.narrative_timeline.capital_allocation_evolution:
        lines.extend(["", "### Capital allocation"])
        for c in ts.narrative_timeline.capital_allocation_evolution:
            flag = " — consistent" if c.was_consistent else ""
            lines.append(
                f"- {c.capital_allocation_text} "
                f"[{', '.join(c.periods_mentioned)}]{flag}"
            )
    return "\n".join(lines) + "\n"


# ----------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------
def _run_historicals(
    ticker: str,
    export: Path | None,
    normalizer: HistoricalNormalizer | None,
) -> None:
    """Testable entry point — takes an optional :class:`HistoricalNormalizer`
    injection so tests can feed a stub repo without patching."""
    normalizer = normalizer or HistoricalNormalizer()
    ts = normalizer.normalize(ticker)
    if not ts.records:
        console.print(
            f"[yellow]No canonical states found for {ticker}.[/yellow] "
            "Run `pte process` first."
        )
        raise typer.Exit(code=1)

    console.print(_render_periods_table(ts))
    restatements_table = _render_restatements(ts.restatement_events)
    if restatements_table is not None:
        console.print(restatements_table)
    fy_table = _render_fiscal_year_changes(ts.fiscal_year_changes)
    if fy_table is not None:
        console.print(fy_table)
    for line in _render_narrative_timeline(ts.narrative_timeline):
        console.print(line)

    if export is not None:
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_text(render_markdown_report(ts), encoding="utf-8")
        console.print(f"\n[dim]Markdown report written to {export}[/dim]")


def historicals(
    ticker: str = typer.Argument(..., help="Target ticker (e.g. 1846.HK)."),
    export: Path | None = typer.Option(
        None,
        "--export",
        help="Write a markdown report to PATH (in addition to stdout).",
    ),
) -> None:
    """Build + render the historical time-series for ``ticker``."""
    _run_historicals(ticker, export, normalizer=None)


__all__ = ["_run_historicals", "historicals", "render_markdown_report"]
