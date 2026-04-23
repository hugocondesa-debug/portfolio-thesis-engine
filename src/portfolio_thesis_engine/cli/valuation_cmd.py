"""Phase 2 Sprint 4A-alpha — ``pte valuation <ticker>`` CLI."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from portfolio_thesis_engine.dcf.orchestrator import DCFOrchestrator
from portfolio_thesis_engine.dcf.schemas import (
    DCFValuationResult,
    ForecastWarning,
)

console = Console()


def _fmt_money(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value:,.0f}"


def _fmt_per_share(value: Any, currency: str = "") -> str:
    if value is None:
        return "—"
    prefix = f"{currency}$" if currency else ""
    return f"{prefix}{value:,.2f}"


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "—"
    if abs(value) < Decimal("1"):
        return f"{value * 100:.2f}%"
    return f"{value:+.2f}%"


def _scenario_table(
    result: DCFValuationResult, market_price: Decimal | None
) -> Table:
    table = Table(
        title=f"{result.ticker} — Valuation scenarios ({result.valuation_profile.value})",
        title_style="bold cyan",
    )
    table.add_column("Scenario")
    table.add_column("Probability", justify="right")
    table.add_column("Methodology")
    table.add_column("FV / share", justify="right")
    table.add_column("Upside vs market", justify="right")
    for v in result.scenarios_run:
        upside: str
        if market_price and market_price != 0:
            upside_val = (v.fair_value_per_share / market_price - Decimal("1")) * Decimal("100")
            upside = f"{upside_val:+.1f}%"
        else:
            upside = "—"
        table.add_row(
            v.scenario_name,
            f"{v.scenario_probability * 100:.0f}%",
            v.methodology_used.value,
            _fmt_per_share(v.fair_value_per_share),
            upside,
        )
    return table


def _bridge_section(
    result: DCFValuationResult, scenario_name: str
) -> list[str]:
    """Sprint 4A-alpha.1 Issue 5 — render the EV-to-equity bridge so
    the analyst can trace per-share value back to its aggregate
    components without eyeballing the year-by-year PVs."""
    scenario = next(
        (s for s in result.scenarios_run if s.scenario_name == scenario_name),
        None,
    )
    if scenario is None:
        return []
    explicit_pv = sum(
        (p.pv for p in scenario.explicit_projections), start=Decimal("0")
    )
    fade_pv = sum(
        (p.pv for p in scenario.fade_projections), start=Decimal("0")
    )
    lines = [f"[bold]Projection summary — {scenario_name}[/bold]"]
    lines.append(f"  Sum of explicit PV (Y1-Y5): {_fmt_money(explicit_pv)}")
    lines.append(f"  Sum of fade PV (Y6-Y10): {_fmt_money(fade_pv)}")
    # Sprint 4A-alpha.3 — terminal block branches on the methodology's
    # terminal_method. Summary dict is populated for TERMINAL_MULTIPLE
    # runs and lets the CLI render the metric × multiple form.
    ms = scenario.methodology_summary or {}
    if ms.get("terminal_method") == "TERMINAL_MULTIPLE":
        metric = ms.get("terminal_metric") or "EV_EBITDA"
        metric_value = ms.get("terminal_metric_value")
        multiple_used = ms.get("terminal_multiple_used")
        source_note = ms.get("terminal_multiple_source_note") or ""
        implied_g = ms.get("gordon_implied_growth")
        lines.append(
            f"  Terminal metric: {metric} terminal-year = "
            f"{_fmt_money(metric_value)}"
        )
        multiple_str = (
            f"{multiple_used:.2f}×" if multiple_used is not None else "—"
        )
        lines.append(
            f"  Terminal multiple: {multiple_str} "
            f"(source: {source_note})"
        )
        lines.append(
            f"  Terminal value = Metric × Multiple = "
            f"{_fmt_money(scenario.terminal_value)}"
        )
        if implied_g is not None:
            lines.append(
                f"  Cross-check: implied Gordon g = "
                f"{implied_g * 100:.2f}% "
                f"(WACC {scenario.terminal_wacc * 100:.2f}%)"
            )
    else:
        lines.append(
            f"  Terminal FCF: {_fmt_money(scenario.terminal_fcf)} × "
            f"(1 + {scenario.terminal_growth * 100:.2f}%) ÷ "
            f"({scenario.terminal_wacc * 100:.2f}% − "
            f"{scenario.terminal_growth * 100:.2f}%)"
        )
        lines.append(f"  Terminal value: {_fmt_money(scenario.terminal_value)}")
    lines.append(f"  Terminal PV: {_fmt_money(scenario.terminal_pv)}")
    lines.append(f"  Enterprise value: {_fmt_money(scenario.enterprise_value)}")
    lines.append(
        f"  Net debt: {_fmt_money(scenario.net_debt)}"
        + (" (net cash)" if scenario.net_debt < 0 else "")
    )
    if scenario.non_operating_assets:
        lines.append(
            f"  Non-operating assets: {_fmt_money(scenario.non_operating_assets)}"
        )
    lines.append(f"  Equity value: {_fmt_money(scenario.equity_value)}")
    lines.append(f"  Shares outstanding: {_fmt_money(scenario.shares_outstanding)}")
    lines.append(
        f"  [bold]Fair value per share: "
        f"{_fmt_per_share(scenario.fair_value_per_share)}[/bold]"
    )
    return lines


def _terminal_multiple_table(
    result: DCFValuationResult, force_full: bool = False
) -> Table | list[str]:
    """Sprint 4A-alpha.1 Issue 3 — compact note when every scenario is
    within threshold; full table when any warning fires or
    ``force_full`` is True (``--detail`` flag / markdown export)."""
    any_warning = any(
        v.terminal_multiple_validation.warning_emitted
        for v in result.scenarios_run
    )
    if not any_warning and not force_full:
        return [
            "[dim]Terminal multiple cross-check: all scenarios within "
            "the 1.5× industry-median threshold.[/dim]"
        ]
    table = Table(
        title="Terminal multiple cross-check", title_style="bold yellow"
    )
    table.add_column("Scenario")
    table.add_column("Implied EV/EBITDA", justify="right")
    table.add_column("Industry median", justify="right")
    table.add_column("Ratio", justify="right")
    table.add_column("Warning")
    for v in result.scenarios_run:
        val = v.terminal_multiple_validation
        ratio = (
            f"{val.ratio_vs_median:.2f}×"
            if val.ratio_vs_median is not None
            else "—"
        )
        table.add_row(
            v.scenario_name,
            _fmt_ratio(val.implied_ev_ebitda),
            _fmt_ratio(val.industry_median_ev_ebitda),
            ratio,
            "⚠" if val.warning_emitted else "OK",
        )
    return table


def _fmt_ratio(value: Decimal | None) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}×"


def _preliminary_signal_section(
    ticker: str, result: DCFValuationResult
) -> list[str]:
    """Sprint 4A-alpha.1 Issue 6 — flag when the Phase-2 preliminary
    signal (unaudited FY YoY) exceeds every scenario's Y1 growth."""
    try:
        from portfolio_thesis_engine.analytical.historicals import (
            HistoricalNormalizer,
        )

        ts = HistoricalNormalizer().normalize(ticker)
    except Exception:
        return []
    trends = ts.trends
    if trends is None or trends.revenue_yoy_growth_preliminary is None:
        return []
    prelim = trends.revenue_yoy_growth_preliminary / Decimal("100")
    # Gather each scenario's Y1 growth (first explicit projection is
    # base_revenue × (1 + growth); derive growth back).
    scenario_y1_growths: list[tuple[str, Decimal]] = []
    for v in result.scenarios_run:
        if not v.explicit_projections:
            continue
        y1 = v.explicit_projections[0]
        # Need the base-year revenue to solve for growth. Use the same
        # y1.revenue / (1 + growth) inversion: we'd rather read the
        # growth directly from a reserved field. Since we don't
        # persist it, approximate from y1 revenue and the ticker's
        # FY2024 annual record.
        annuals = [
            r
            for r in ts.records
            if r.period_type.value == "annual"
            and r.revenue is not None
        ]
        if not annuals:
            continue
        base_rev = max(annuals, key=lambda r: r.period_end).revenue
        if base_rev and base_rev != 0:
            growth = y1.revenue / base_rev - Decimal("1")
            scenario_y1_growths.append((v.scenario_name, growth))
    if not scenario_y1_growths:
        return []
    highest_y1 = max(g for _, g in scenario_y1_growths)
    if prelim <= highest_y1:
        return []
    lines = ["[bold yellow]Preliminary signal cross-check[/bold yellow]"]
    signal_pct = prelim * Decimal("100")
    lines.append(
        f"  FY preliminary YoY: +{signal_pct:.2f}% "
        f"({trends.preliminary_signal_period or 'FY preliminary'})"
    )
    for name, growth in scenario_y1_growths:
        marker = "↓ below" if growth < prelim else "≥ above"
        lines.append(
            f"  {name} Y1 ({growth * 100:+.2f}%): {marker} preliminary signal"
        )
    lines.append(
        "  → Preliminary signal exceeds every scenario's Y1 growth; "
        "even the bull case may be conservative if the preliminary "
        "holds."
    )
    return lines


def _stage_projection_table(
    result: DCFValuationResult, scenario_name: str
) -> Table | None:
    scenario = next(
        (s for s in result.scenarios_run if s.scenario_name == scenario_name),
        None,
    )
    if scenario is None:
        return None
    table = Table(
        title=f"Projection detail: {scenario_name}",
        title_style="bold yellow",
    )
    table.add_column("Year")
    table.add_column("Revenue", justify="right")
    table.add_column("Op margin", justify="right")
    table.add_column("NOPAT", justify="right")
    table.add_column("CapEx", justify="right")
    table.add_column("FCF", justify="right")
    table.add_column("WACC", justify="right")
    table.add_column("PV", justify="right")
    for p in scenario.explicit_projections + scenario.fade_projections:
        table.add_row(
            str(p.year),
            _fmt_money(p.revenue),
            f"{p.operating_margin * 100:.2f}%",
            _fmt_money(p.nopat),
            _fmt_money(p.capex),
            _fmt_money(p.fcf),
            f"{p.wacc_applied * 100:.2f}%",
            _fmt_money(p.pv),
        )
    return table


def _warnings_section(warnings: list[ForecastWarning]) -> list[str]:
    if not warnings:
        return ["[dim]No forecast warnings — projections pass coherence checks.[/dim]"]
    severity_colour = {"INFO": "dim", "WARNING": "yellow", "CRITICAL": "red"}
    lines = ["[bold]Forecast warnings[/bold]"]
    for w in warnings:
        tag = severity_colour.get(w.severity, "")
        lines.append(
            f"  [{tag}][{w.severity}][/{tag}] "
            f"{w.scenario} / {w.metric}: {w.observation}"
        )
        if w.recommendation:
            lines.append(f"    → {w.recommendation}")
    return lines


def _summary_section(
    result: DCFValuationResult, market_price: Decimal | None
) -> list[str]:
    lines = ["[bold cyan]Valuation summary[/bold cyan]"]
    lines.append(
        f"  Stage-1 WACC: {result.stage_1_wacc * 100:.2f}% "
        f"→ Stage-3 WACC: {result.stage_3_wacc * 100:.2f}% (linear fade)"
    )
    if result.expected_value_per_share is not None:
        lines.append(
            f"  Expected value per share: "
            f"{_fmt_per_share(result.expected_value_per_share)}"
        )
    if result.p25_value_per_share is not None and result.p75_value_per_share is not None:
        lines.append(
            f"  Scenario range (P25-P75): "
            f"{_fmt_per_share(result.p25_value_per_share)} – "
            f"{_fmt_per_share(result.p75_value_per_share)}"
        )
    if market_price is not None:
        lines.append(f"  Market price: {_fmt_per_share(market_price)}")
    if result.implied_upside_downside_pct is not None:
        lines.append(
            f"  Implied upside/downside: "
            f"{result.implied_upside_downside_pct:+.1f}%"
        )
    return lines


def _run_valuation(
    ticker: str,
    export: Path | None,
    scenario_filter: str | None,
    detail: bool,
    market_price: Decimal | None,
    orchestrator: DCFOrchestrator | None,
) -> None:
    orchestrator = orchestrator or DCFOrchestrator()
    result = orchestrator.run(ticker)
    if result is None:
        console.print(
            f"[yellow]No canonical state or scenarios for {ticker}.[/yellow] "
            "Ensure `pte process` has run and "
            f"`data/yamls/companies/<ticker>/scenarios.yaml` exists."
        )
        raise typer.Exit(code=1)

    # Re-attach market price override when caller supplied one.
    if market_price is not None:
        result.market_price = market_price
        if market_price != 0 and result.expected_value_per_share is not None:
            result.implied_upside_downside_pct = (
                (result.expected_value_per_share / market_price - Decimal("1"))
                * Decimal("100")
            )

    console.print(_scenario_table(result, result.market_price))
    for line in _summary_section(result, result.market_price):
        console.print(line)

    terminal = _terminal_multiple_table(result, force_full=detail)
    if isinstance(terminal, Table):
        console.print(terminal)
    else:
        for line in terminal:
            console.print(line)

    for line in _warnings_section(result.warnings):
        console.print(line)

    # EV-to-equity bridge for the base (or filtered) scenario.
    for line in _bridge_section(result, scenario_filter or "base"):
        console.print(line)

    if detail:
        scenario_name = scenario_filter or "base"
        projection = _stage_projection_table(result, scenario_name)
        if projection is not None:
            console.print(projection)

    for line in _preliminary_signal_section(ticker, result):
        console.print(line)

    if export is not None:
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_text(
            render_valuation_markdown(result, ticker=ticker),
            encoding="utf-8",
        )
        console.print(f"\n[dim]Valuation report written to {export}[/dim]")


def render_valuation_markdown(
    result: DCFValuationResult, *, ticker: str | None = None
) -> str:
    """Full markdown report — Sprint 4A-alpha.1 Issue 2 expands the
    scaffold from 19 lines to a complete document."""
    ticker = ticker or result.ticker
    from datetime import UTC, datetime

    lines: list[str] = [
        f"# {result.ticker} — DCF Valuation Report",
        "",
        f"Generated: {datetime.now(UTC).date().isoformat()}",
        f"Valuation profile: **{result.valuation_profile.value}**",
    ]
    market = result.market_price
    if market is not None:
        lines.append(f"Market price: {_fmt_per_share(market)}")

    # DCF structure
    lines.extend([
        "",
        "## DCF structure",
        "",
        f"- Type: THREE_STAGE (5 explicit + 5 fade + Gordon growth terminal)",
        f"- Stage-1 WACC: {result.stage_1_wacc * 100:.2f}%",
        f"- Stage-3 WACC: {result.stage_3_wacc * 100:.2f}%",
        f"- Fade: linear from stage 1 to stage 3 across years 6-10",
    ])

    # Scenarios table
    lines.extend([
        "",
        "## Scenarios",
        "",
        "| Scenario | Probability | Methodology | FV / share | Upside vs market |",
        "|---|---:|---|---:|---:|",
    ])
    for v in result.scenarios_run:
        if market and market != 0:
            upside = (v.fair_value_per_share / market - Decimal("1")) * Decimal("100")
            upside_str = f"{upside:+.1f}%"
        else:
            upside_str = "—"
        lines.append(
            f"| {v.scenario_name} | {v.scenario_probability * 100:.0f}% | "
            f"{v.methodology_used.value} | "
            f"{_fmt_per_share(v.fair_value_per_share)} | {upside_str} |"
        )

    # Base scenario projections
    base = next(
        (s for s in result.scenarios_run if s.scenario_name == "base"),
        result.scenarios_run[0] if result.scenarios_run else None,
    )
    if base is not None:
        lines.extend([
            "",
            f"## Base scenario projections ({base.scenario_name})",
            "",
            "| Year | Revenue | Op margin | NOPAT | CapEx | FCF | WACC | PV |",
            "|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for p in base.explicit_projections + base.fade_projections:
            lines.append(
                f"| {p.year} | {_fmt_money(p.revenue)} | "
                f"{p.operating_margin * 100:.2f}% | "
                f"{_fmt_money(p.nopat)} | {_fmt_money(p.capex)} | "
                f"{_fmt_money(p.fcf)} | "
                f"{p.wacc_applied * 100:.2f}% | {_fmt_money(p.pv)} |"
            )
        # EV → Equity bridge
        explicit_pv = sum(
            (p.pv for p in base.explicit_projections), start=Decimal("0")
        )
        fade_pv = sum(
            (p.pv for p in base.fade_projections), start=Decimal("0")
        )
        lines.extend([
            "",
            "### Enterprise-to-equity bridge",
            "",
            f"- Σ explicit PV (Y1-Y5): {_fmt_money(explicit_pv)}",
            f"- Σ fade PV (Y6-Y10): {_fmt_money(fade_pv)}",
        ])
        # Sprint 4A-alpha.3 — branch on terminal method for the
        # terminal-value breakdown.
        base_ms = base.methodology_summary or {}
        if base_ms.get("terminal_method") == "TERMINAL_MULTIPLE":
            metric = base_ms.get("terminal_metric") or "EV_EBITDA"
            metric_value = base_ms.get("terminal_metric_value")
            multiple_used = base_ms.get("terminal_multiple_used")
            source_note = base_ms.get("terminal_multiple_source_note") or ""
            implied_g = base_ms.get("gordon_implied_growth")
            lines.extend([
                f"- Terminal method: TERMINAL_MULTIPLE ({source_note})",
                f"- Terminal metric ({metric}): {_fmt_money(metric_value)}",
                f"- Terminal multiple: "
                + (f"{multiple_used:.2f}×" if multiple_used is not None else "—"),
                f"- Terminal value (metric × multiple): "
                f"{_fmt_money(base.terminal_value)}",
            ])
            if implied_g is not None:
                lines.append(
                    f"- Gordon-implied growth cross-check: "
                    f"{implied_g * 100:.2f}% (WACC "
                    f"{base.terminal_wacc * 100:.2f}%)"
                )
            lines.append(f"- Terminal PV: {_fmt_money(base.terminal_pv)}")
        else:
            lines.extend([
                f"- Terminal FCF: {_fmt_money(base.terminal_fcf)}",
                f"- Terminal growth: {base.terminal_growth * 100:.2f}%",
                f"- Terminal WACC: {base.terminal_wacc * 100:.2f}%",
                f"- Terminal value: {_fmt_money(base.terminal_value)}",
                f"- Terminal PV: {_fmt_money(base.terminal_pv)}",
            ])
        lines.extend([
            f"- **Enterprise value: {_fmt_money(base.enterprise_value)}**",
            f"- Net debt: {_fmt_money(base.net_debt)}"
            + (" (net cash)" if base.net_debt < 0 else ""),
            f"- Non-operating assets: {_fmt_money(base.non_operating_assets)}",
            f"- **Equity value: {_fmt_money(base.equity_value)}**",
            f"- Shares outstanding: {_fmt_money(base.shares_outstanding)}",
            f"- **Fair value per share: "
            f"{_fmt_per_share(base.fair_value_per_share)}**",
        ])

    # Terminal multiple validation (always full)
    lines.extend([
        "",
        "## Terminal multiple cross-check",
        "",
        "| Scenario | Implied EV/EBITDA | Industry median | Ratio | Warning |",
        "|---|---:|---:|---:|---|",
    ])
    for v in result.scenarios_run:
        val = v.terminal_multiple_validation
        ratio = (
            f"{val.ratio_vs_median:.2f}×"
            if val.ratio_vs_median is not None
            else "—"
        )
        warning = "⚠" if val.warning_emitted else "OK"
        lines.append(
            f"| {v.scenario_name} | {_fmt_ratio(val.implied_ev_ebitda)} | "
            f"{_fmt_ratio(val.industry_median_ev_ebitda)} | {ratio} | "
            f"{warning} |"
        )
    lines.append("")
    lines.append(
        f"_Warning threshold: "
        f"{result.scenarios_run[0].terminal_multiple_validation.warning_threshold:.2f}× "
        f"industry median._" if result.scenarios_run else ""
    )

    # Summary
    lines.extend(["", "## Summary", ""])
    if result.expected_value_per_share is not None:
        lines.append(
            f"- Expected value per share: "
            f"{_fmt_per_share(result.expected_value_per_share)}"
        )
    if base is not None:
        lines.append(
            f"- Base scenario: {_fmt_per_share(base.fair_value_per_share)} "
            f"({base.scenario_probability * 100:.0f}% probability)"
        )
    if (
        result.p25_value_per_share is not None
        and result.p75_value_per_share is not None
    ):
        lines.append(
            f"- Scenario range (P25-P75): "
            f"{_fmt_per_share(result.p25_value_per_share)} – "
            f"{_fmt_per_share(result.p75_value_per_share)}"
        )
    if result.market_price is not None:
        lines.append(f"- Market price: {_fmt_per_share(result.market_price)}")
    if result.implied_upside_downside_pct is not None:
        lines.append(
            f"- Implied upside/downside: "
            f"{result.implied_upside_downside_pct:+.1f}%"
        )
    if result.warnings:
        lines.extend(["", "### Forecast warnings", ""])
        for w in result.warnings:
            lines.append(
                f"- **{w.severity}** — {w.scenario} / {w.metric}: "
                f"{w.observation}"
            )
    else:
        lines.append("- Warnings: none")

    # Assumptions summary
    lines.extend([
        "",
        "## Assumptions summary",
        "",
        f"- Base year: latest audited annual fed through Sprint-3 "
        f"auto-WACC {result.stage_1_wacc * 100:.2f}%",
        f"- Mature (stage-3) WACC: {result.stage_3_wacc * 100:.2f}%",
        f"- Terminal growth: "
        f"{result.scenarios_run[0].terminal_growth * 100:.2f}%"
        if result.scenarios_run else "",
        "- Driver overrides per scenario are sparse on top of base "
        "drivers declared in scenarios.yaml.",
    ])

    # Preliminary signal
    prelim_lines = _preliminary_signal_section(ticker, result)
    if prelim_lines:
        lines.extend(["", "## Preliminary signal cross-check", ""])
        for raw in prelim_lines[1:]:  # skip the Rich bold header
            cleaned = raw.strip()
            if cleaned:
                lines.append(f"- {cleaned}")

    return "\n".join(lines) + "\n"


def valuation(
    ticker: str = typer.Argument(..., help="Target ticker (e.g. 1846.HK)."),
    export: Path | None = typer.Option(
        None, "--export", help="Write valuation markdown report to PATH."
    ),
    scenario: str | None = typer.Option(
        None, "--scenario", help="Scenario name for detailed projection table."
    ),
    detail: bool = typer.Option(
        False, "--detail", help="Print full year-by-year projection detail."
    ),
    market_price: float | None = typer.Option(
        None, "--market-price", help="Override market price for upside calc."
    ),
) -> None:
    """Produce a scenario-weighted DCF valuation for ``ticker``."""
    mp = Decimal(str(market_price)) if market_price is not None else None
    _run_valuation(ticker, export, scenario, detail, mp, orchestrator=None)


__all__ = ["_run_valuation", "render_valuation_markdown", "valuation"]
