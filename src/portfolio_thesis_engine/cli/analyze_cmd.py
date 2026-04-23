"""Phase 2 Sprint 2A — ``pte analyze <ticker>`` CLI.

Produces an analytical report that extends ``pte historicals`` with:

- Economic Balance Sheet evolution
- DuPont 3-way ROE decomposition per period
- ROIC decomposition per period
- Trend analysis (CAGRs, margin/ROIC trajectories)
- Quality of Earnings scoring with per-component drill-down
- Investment signal synthesis

All tables render via Rich to the CLI; ``--export PATH`` writes a
markdown report in addition.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from portfolio_thesis_engine.analytical.analyze import (
    attribute_roe_change,
    attribute_roic_change,
)
from portfolio_thesis_engine.analytical.historicals import HistoricalNormalizer
from portfolio_thesis_engine.cli.historicals_cmd import (
    _render_fiscal_year_changes,
    _render_narrative_timeline,
    _render_periods_table,
    _render_restatements,
)
from portfolio_thesis_engine.schemas.historicals import (
    CompanyTimeSeries,
    HistoricalPeriodType,
    HistoricalRecord,
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


def _fmt_bps(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value:+.0f} bps"


def _fmt_ratio(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}×"


def _economic_bs_table(ts: CompanyTimeSeries) -> Table | None:
    entries = [
        (r.period, r.economic_balance_sheet)
        for r in ts.records
        if r.economic_balance_sheet is not None
    ]
    if not entries:
        return None
    table = Table(
        title="Economic Balance Sheet evolution (IC components)",
        title_style="bold blue",
    )
    table.add_column("Period")
    table.add_column("PPE net", justify="right")
    table.add_column("ROU", justify="right")
    table.add_column("Goodwill", justify="right")
    table.add_column("WC", justify="right")
    table.add_column("IC", justify="right")
    table.add_column("Cash", justify="right")
    table.add_column("Debt", justify="right")
    table.add_column("NFP", justify="right")
    for period, bs in entries:
        table.add_row(
            period,
            _fmt_money(bs.operating_ppe_net),
            _fmt_money(bs.rou_assets),
            _fmt_money(bs.goodwill),
            _fmt_money(bs.working_capital),
            _fmt_money(bs.invested_capital),
            _fmt_money(bs.cash_and_equivalents),
            _fmt_money(bs.financial_debt),
            _fmt_money(bs.net_financial_position),
        )
    return table


def _dupont_table(ts: CompanyTimeSeries) -> Table | None:
    entries = [
        (r.period, r.dupont_3way) for r in ts.records
        if r.dupont_3way is not None
    ]
    if not entries:
        return None
    table = Table(
        title="DuPont 3-way ROE decomposition",
        title_style="bold blue",
    )
    table.add_column("Period")
    table.add_column("Net margin %", justify="right")
    table.add_column("Asset turnover", justify="right")
    table.add_column("Leverage", justify="right")
    table.add_column("ROE (computed)", justify="right")
    table.add_column("ROE (reported)", justify="right")
    for period, d in entries:
        table.add_row(
            period,
            _fmt_pct(d.net_margin),
            _fmt_ratio(d.asset_turnover),
            _fmt_ratio(d.financial_leverage),
            _fmt_pct(d.roe_computed),
            _fmt_pct(d.roe_reported),
        )
    return table


def _roic_table(ts: CompanyTimeSeries) -> Table | None:
    entries = [
        (r.period, r.roic_decomposition) for r in ts.records
        if r.roic_decomposition is not None
    ]
    if not entries:
        return None
    table = Table(
        title="ROIC decomposition (NOPAT margin × IC turnover)",
        title_style="bold blue",
    )
    table.add_column("Period")
    table.add_column("NOPAT margin %", justify="right")
    table.add_column("IC turnover", justify="right")
    table.add_column("ROIC (computed)", justify="right")
    table.add_column("WACC", justify="right")
    table.add_column("Spread", justify="right")
    table.add_column("Signal")
    for period, d in entries:
        table.add_row(
            period,
            _fmt_pct(d.nopat_margin),
            _fmt_ratio(d.ic_turnover),
            _fmt_pct(d.roic_computed),
            _fmt_pct(d.wacc),
            _fmt_bps(d.spread_bps),
            d.value_signal or "—",
        )
    return table


def _trends_table(ts: CompanyTimeSeries) -> Table | None:
    t = ts.trends
    if t is None:
        return None
    table = Table(
        show_header=False,
        title="Trend analysis",
        title_style="bold yellow",
    )
    table.add_column("Metric", style="dim")
    table.add_column("Value", justify="right")
    table.add_row("Period start", t.period_start)
    table.add_row("Period end", t.period_end)
    table.add_row(
        "Annuals available", f"{t.annuals_used_for_cagr}"
    )
    table.add_row("Revenue YoY growth", _fmt_pct(t.revenue_yoy_growth))
    table.add_row("Revenue CAGR (2Y)", _fmt_pct(t.revenue_cagr_2y))
    table.add_row("Revenue CAGR (3Y)", _fmt_pct(t.revenue_cagr_3y))
    table.add_row("Revenue CAGR (5Y)", _fmt_pct(t.revenue_cagr_5y))
    table.add_row("Revenue trajectory", t.revenue_trajectory)
    table.add_row(
        "Operating margin Δ", _fmt_bps(t.operating_margin_delta_bps)
    )
    table.add_row("Margin trajectory", t.operating_margin_trajectory)
    table.add_row("ROIC Δ", _fmt_bps(t.roic_delta_bps))
    table.add_row("ROIC trajectory", t.roic_trajectory)
    return table


def _consecutive_annuals(ts: CompanyTimeSeries) -> list[HistoricalRecord]:
    """Ordered, audited annual records used for period-over-period
    attribution (DuPont / ROIC). Comparatives count since they are
    annual observations, as long as audit status is not UNAUDITED."""
    from portfolio_thesis_engine.schemas.raw_extraction import AuditStatus

    annuals = [
        r
        for r in ts.records
        if r.period_type == HistoricalPeriodType.ANNUAL
        and r.audit_status != AuditStatus.UNAUDITED
    ]
    return sorted(annuals, key=lambda r: r.period_end)


def _roic_attribution_section(ts: CompanyTimeSeries) -> list[str]:
    """Render a compact period-over-period ROIC attribution section for
    every consecutive pair of annuals that has both decompositions
    populated."""
    annuals = _consecutive_annuals(ts)
    lines: list[str] = []
    if len(annuals) < 2:
        return lines
    any_attribution = False
    for i in range(1, len(annuals)):
        a = annuals[i - 1]
        b = annuals[i]
        if a.roic_decomposition is None or b.roic_decomposition is None:
            continue
        attr = attribute_roic_change(a.roic_decomposition, b.roic_decomposition)
        if attr is None:
            continue
        if not any_attribution:
            lines.append("[bold blue]ROIC attribution[/bold blue]")
            any_attribution = True
        lines.append(
            f"  {a.period} → {b.period}: ΔROIC {_fmt_bps(attr.roic_delta_bps)}"
        )
        lines.append(
            f"    NOPAT margin contribution: {_fmt_bps(attr.nopat_margin_contribution_bps)}"
        )
        lines.append(
            f"    IC turnover contribution:  {_fmt_bps(attr.ic_turnover_contribution_bps)}"
        )
        lines.append(
            f"    Cross residual:            {_fmt_bps(attr.cross_residual_bps)}"
        )
    return lines


def _roe_attribution_section(ts: CompanyTimeSeries) -> list[str]:
    """Period-over-period ROE attribution via DuPont 3-way."""
    annuals = _consecutive_annuals(ts)
    lines: list[str] = []
    if len(annuals) < 2:
        return lines
    any_attribution = False
    for i in range(1, len(annuals)):
        a = annuals[i - 1]
        b = annuals[i]
        if a.dupont_3way is None or b.dupont_3way is None:
            continue
        attr = attribute_roe_change(a.dupont_3way, b.dupont_3way)
        if attr is None:
            continue
        if not any_attribution:
            lines.append("[bold blue]ROE attribution (DuPont 3-way)[/bold blue]")
            any_attribution = True
        lines.append(
            f"  {a.period} → {b.period}: ΔROE {_fmt_bps(attr.roe_delta_bps)}"
        )
        lines.append(
            f"    Net margin contribution:     {_fmt_bps(attr.margin_contribution_bps)}"
        )
        lines.append(
            f"    Asset turnover contribution: {_fmt_bps(attr.turnover_contribution_bps)}"
        )
        lines.append(
            f"    Leverage contribution:       {_fmt_bps(attr.leverage_contribution_bps)}"
        )
        lines.append(
            f"    Cross residual:              {_fmt_bps(attr.cross_residual_bps)}"
        )
    return lines


def _qoe_table(ts: CompanyTimeSeries) -> Table | None:
    entries = [
        (r.period, r.quality_of_earnings) for r in ts.records
        if r.quality_of_earnings is not None
    ]
    if not entries:
        return None
    table = Table(
        title="Quality of Earnings",
        title_style="bold blue",
    )
    table.add_column("Period")
    table.add_column("Composite", justify="right")
    table.add_column("Accruals", justify="right")
    table.add_column("CFO/NI", justify="right")
    table.add_column("AR/Rev", justify="right")
    table.add_column("Non-rec", justify="right")
    table.add_column("Audit", justify="right")
    table.add_column("Flags")
    for period, q in entries:
        table.add_row(
            period,
            str(q.composite_score) if q.composite_score is not None else "—",
            str(q.accruals_quality_score) if q.accruals_quality_score is not None else "—",
            str(q.cfo_ni_score) if q.cfo_ni_score is not None else "—",
            str(q.ar_revenue_score) if q.ar_revenue_score is not None else "—",
            str(q.non_recurring_score) if q.non_recurring_score is not None else "—",
            str(q.audit_score) if q.audit_score is not None else "—",
            ", ".join(q.flags) if q.flags else "—",
        )
    return table


def _signal_section(ts: CompanyTimeSeries) -> list[str]:
    s = ts.investment_signal
    if s is None:
        return []
    lines = ["[bold magenta]Investment signal[/bold magenta]"]
    lines.append(f"  Value creation: {s.current_value_creation}")
    if s.current_value_spread_bps is not None:
        lines.append(
            f"    Spread vs WACC: {s.current_value_spread_bps:+d} bps"
        )
    lines.append(f"  Growth trajectory: {s.growth_trajectory}")
    lines.append(f"  Capital efficiency: {s.capital_efficiency_trend}")
    lines.append(f"  Margin trend: {s.margin_trend}")
    if s.earnings_quality_score is not None:
        lines.append(
            f"  Earnings quality composite: {s.earnings_quality_score}/100"
        )
    lines.append(f"  Balance sheet: {s.balance_sheet_strength}")
    if s.summary_bullets:
        lines.append("")
        lines.append("[bold]Summary[/bold]")
        for b in s.summary_bullets:
            lines.append(f"  • {b}")
    return lines


# ----------------------------------------------------------------------
# Markdown export
# ----------------------------------------------------------------------
def render_analytical_markdown(ts: CompanyTimeSeries) -> str:
    """Produce a markdown report spanning every analytical section the
    CLI renders (Sprint 2A.1 expands this from the initial trends +
    signal scaffold to the full report)."""
    lines: list[str] = [
        f"# {ts.ticker} — Analytical report",
        "",
        f"Generated: {ts.generated_at.date().isoformat()}",
        f"Records: {len(ts.records)}",
        "",
        "## Periods",
        "",
        "| Period | End | Type | Audit | Revenue | Op Income | NOPAT | ROIC |",
        "|---|---|---|---|---:|---:|---:|---:|",
    ]
    for r in ts.records:
        lines.append(
            f"| {r.period} | {r.period_end.isoformat()} | "
            f"{r.period_type.value} | {r.audit_status.value} | "
            f"{_fmt_money(r.revenue)} | {_fmt_money(r.operating_income)} | "
            f"{_fmt_money(r.nopat)} | {_fmt_pct(r.roic_primary)} |"
        )

    # Economic BS
    ebs_rows = [r for r in ts.records if r.economic_balance_sheet is not None]
    if ebs_rows:
        lines.extend([
            "",
            "## Economic Balance Sheet",
            "",
            "| Period | PPE net | ROU | Goodwill | WC | IC | Cash | Debt | NFP |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for r in ebs_rows:
            bs = r.economic_balance_sheet
            assert bs is not None
            lines.append(
                f"| {r.period} | {_fmt_money(bs.operating_ppe_net)} | "
                f"{_fmt_money(bs.rou_assets)} | {_fmt_money(bs.goodwill)} | "
                f"{_fmt_money(bs.working_capital)} | "
                f"{_fmt_money(bs.invested_capital)} | "
                f"{_fmt_money(bs.cash_and_equivalents)} | "
                f"{_fmt_money(bs.financial_debt)} | "
                f"{_fmt_money(bs.net_financial_position)} |"
            )

    # DuPont 3-way
    dupont_rows = [r for r in ts.records if r.dupont_3way is not None]
    if dupont_rows:
        lines.extend([
            "",
            "## DuPont 3-way ROE decomposition",
            "",
            "| Period | Net margin % | Asset turnover | Leverage | ROE computed | ROE reported |",
            "|---|---:|---:|---:|---:|---:|",
        ])
        for r in dupont_rows:
            d = r.dupont_3way
            assert d is not None
            lines.append(
                f"| {r.period} | {_fmt_pct(d.net_margin)} | "
                f"{_fmt_ratio(d.asset_turnover)} | "
                f"{_fmt_ratio(d.financial_leverage)} | "
                f"{_fmt_pct(d.roe_computed)} | {_fmt_pct(d.roe_reported)} |"
            )

    # DuPont attribution (period-over-period)
    roe_attr_lines = _roe_attribution_section(ts)
    if roe_attr_lines:
        lines.extend(["", "### ROE attribution (period-over-period)", ""])
        for raw in roe_attr_lines:
            lines.append(_strip_markup(raw))

    # ROIC decomposition
    roic_rows = [r for r in ts.records if r.roic_decomposition is not None]
    if roic_rows:
        lines.extend([
            "",
            "## ROIC decomposition",
            "",
            "| Period | NOPAT margin % | IC turnover | ROIC | WACC | Spread | Signal |",
            "|---|---:|---:|---:|---:|---:|---|",
        ])
        for r in roic_rows:
            d = r.roic_decomposition
            assert d is not None
            lines.append(
                f"| {r.period} | {_fmt_pct(d.nopat_margin)} | "
                f"{_fmt_ratio(d.ic_turnover)} | {_fmt_pct(d.roic_computed)} | "
                f"{_fmt_pct(d.wacc)} | {_fmt_bps(d.spread_bps)} | "
                f"{d.value_signal or '—'} |"
            )

    # ROIC attribution
    roic_attr_lines = _roic_attribution_section(ts)
    if roic_attr_lines:
        lines.extend(["", "### ROIC attribution (period-over-period)", ""])
        for raw in roic_attr_lines:
            lines.append(_strip_markup(raw))

    # Trends
    if ts.trends is not None:
        t = ts.trends
        lines.extend([
            "",
            "## Trends",
            "",
            f"- Period: {t.period_start} → {t.period_end}",
            f"- Annuals available: {t.annuals_used_for_cagr}",
            f"- Revenue YoY growth: {_fmt_pct(t.revenue_yoy_growth)}",
            f"- Revenue CAGR 2Y: {_fmt_pct(t.revenue_cagr_2y)}",
            f"- Revenue CAGR 3Y: {_fmt_pct(t.revenue_cagr_3y)}",
            f"- Revenue CAGR 5Y: {_fmt_pct(t.revenue_cagr_5y)}",
            f"- Revenue trajectory: {t.revenue_trajectory}",
            f"- Operating margin Δ: {_fmt_bps(t.operating_margin_delta_bps)}",
            f"- Margin trajectory: {t.operating_margin_trajectory}",
            f"- ROIC Δ: {_fmt_bps(t.roic_delta_bps)}",
            f"- ROIC trajectory: {t.roic_trajectory}",
        ])

    # Quality of Earnings
    qoe_rows = [r for r in ts.records if r.quality_of_earnings is not None]
    if qoe_rows:
        lines.extend([
            "",
            "## Quality of Earnings",
            "",
            "| Period | Composite | Accruals | CFO/NI | AR/Rev | Non-rec | Audit | Flags |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ])
        for r in qoe_rows:
            q = r.quality_of_earnings
            assert q is not None
            flags = ", ".join(q.flags) if q.flags else "—"
            lines.append(
                f"| {r.period} | "
                f"{q.composite_score if q.composite_score is not None else '—'} | "
                f"{q.accruals_quality_score if q.accruals_quality_score is not None else '—'} | "
                f"{q.cfo_ni_score if q.cfo_ni_score is not None else '—'} | "
                f"{q.ar_revenue_score if q.ar_revenue_score is not None else '—'} | "
                f"{q.non_recurring_score if q.non_recurring_score is not None else '—'} | "
                f"{q.audit_score if q.audit_score is not None else '—'} | "
                f"{flags} |"
            )

    # Restatement events
    if ts.restatement_events:
        lines.extend([
            "",
            f"## Restatement events ({len(ts.restatement_events)})",
            "",
            "| Period | Metric | From | To | Δ% | Severity |",
            "|---|---|---:|---:|---:|---|",
        ])
        for e in ts.restatement_events:
            lines.append(
                f"| {e.period} | {e.metric} | "
                f"{_fmt_money(e.source_a_value)} | "
                f"{_fmt_money(e.source_b_value)} | "
                f"{_fmt_pct(e.delta_pct)} | {e.severity} |"
            )

    # Fiscal year changes
    if ts.fiscal_year_changes:
        lines.extend([
            "",
            f"## Fiscal-year changes ({len(ts.fiscal_year_changes)})",
            "",
        ])
        for e in ts.fiscal_year_changes:
            lines.append(
                f"- {e.detected_at_period}: "
                f"{e.previous_fiscal_year_end} → {e.new_fiscal_year_end} "
                f"({e.transition_period_months} months)"
            )

    # Narrative timeline
    nt = ts.narrative_timeline
    if nt.themes_evolution or nt.risks_evolution or nt.guidance_evolution:
        lines.extend(["", "## Narrative timeline"])
        if nt.themes_evolution:
            lines.extend(["", "### Themes"])
            for th in nt.themes_evolution:
                flag = " — consistent" if th.was_consistent else ""
                lines.append(
                    f"- {th.theme_text} [{', '.join(th.periods_mentioned)}]{flag}"
                )
        if nt.risks_evolution:
            lines.extend(["", "### Risks"])
            for rk in nt.risks_evolution:
                flag = " — consistent" if rk.was_consistent else ""
                lines.append(
                    f"- {rk.risk_text} [{', '.join(rk.periods_mentioned)}]{flag}"
                )
        if nt.guidance_evolution:
            lines.extend(["", "### Guidance"])
            for g in nt.guidance_evolution:
                flag = " — consistent" if g.was_consistent else ""
                lines.append(
                    f"- {g.guidance_text} [{', '.join(g.periods_mentioned)}]{flag}"
                )

    # Investment signal
    if ts.investment_signal is not None:
        s = ts.investment_signal
        lines.extend([
            "",
            "## Investment signal",
            "",
            f"- Value creation: {s.current_value_creation}"
            + (
                f" ({s.current_value_spread_bps:+d} bps vs WACC)"
                if s.current_value_spread_bps is not None
                else ""
            ),
            f"- Growth trajectory: {s.growth_trajectory}",
            f"- Capital efficiency: {s.capital_efficiency_trend}",
            f"- Margin trend: {s.margin_trend}",
            "- Earnings quality: "
            + (
                f"{s.earnings_quality_score}/100"
                if s.earnings_quality_score is not None
                else "—"
            ),
            f"- Balance sheet: {s.balance_sheet_strength}",
        ])
    return "\n".join(lines) + "\n"


_MARKUP_RE = None


def _strip_markup(text: str) -> str:
    """Remove Rich [bold]/[/bold] style tags for markdown output."""
    import re

    global _MARKUP_RE
    if _MARKUP_RE is None:
        _MARKUP_RE = re.compile(r"\[/?[a-z][a-z0-9 ]*\]")
    return _MARKUP_RE.sub("", text)


# ----------------------------------------------------------------------
# Runner + Typer entry
# ----------------------------------------------------------------------
def _run_analyze(
    ticker: str, export: Path | None, normalizer: HistoricalNormalizer | None
) -> None:
    normalizer = normalizer or HistoricalNormalizer()
    ts = normalizer.normalize(ticker)
    if not ts.records:
        console.print(
            f"[yellow]No canonical states found for {ticker}.[/yellow] "
            "Run `pte process` first."
        )
        raise typer.Exit(code=1)

    # 1. Periods
    console.print(_render_periods_table(ts))
    # 2. Economic BS evolution
    ebs = _economic_bs_table(ts)
    if ebs is not None:
        console.print(ebs)
    # 3. DuPont
    dupont = _dupont_table(ts)
    if dupont is not None:
        console.print(dupont)
    # 4. ROIC
    roic = _roic_table(ts)
    if roic is not None:
        console.print(roic)
    # 4b. DuPont + ROIC period-over-period attribution
    for line in _roe_attribution_section(ts):
        console.print(line)
    for line in _roic_attribution_section(ts):
        console.print(line)
    # 5. Trends
    trends = _trends_table(ts)
    if trends is not None:
        console.print(trends)
    # 6. QoE
    qoe = _qoe_table(ts)
    if qoe is not None:
        console.print(qoe)
    # 7. Restatements
    restatements = _render_restatements(ts.restatement_events)
    if restatements is not None:
        console.print(restatements)
    # 8. Fiscal year changes
    fy = _render_fiscal_year_changes(ts.fiscal_year_changes)
    if fy is not None:
        console.print(fy)
    # 9. Narrative
    for line in _render_narrative_timeline(ts.narrative_timeline):
        console.print(line)
    # 10. Investment signal
    for line in _signal_section(ts):
        console.print(line)

    if export is not None:
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_text(render_analytical_markdown(ts), encoding="utf-8")
        console.print(
            f"\n[dim]Analytical markdown report written to {export}[/dim]"
        )


def analyze(
    ticker: str = typer.Argument(..., help="Target ticker (e.g. 1846.HK)."),
    export: Path | None = typer.Option(
        None,
        "--export",
        help="Write analytical markdown report to PATH (in addition to stdout).",
    ),
) -> None:
    """Produce an analytical report (Economic BS, DuPont, ROIC, trends,
    QoE, investment signal) for ``ticker``."""
    _run_analyze(ticker, export, normalizer=None)


__all__ = ["_run_analyze", "analyze", "render_analytical_markdown"]
