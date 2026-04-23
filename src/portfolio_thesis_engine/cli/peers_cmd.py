"""Phase 2 Sprint 3 — ``pte peers <ticker>`` CLI.

Builds a :class:`PeerComparison` + :class:`PeerValuation` for the
target ticker and renders it as Rich tables. Analytical layer callers
(``pte analyze``) embed a summarised version; this command is the
detailed view.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from portfolio_thesis_engine.peers import (
    PeerDiscoverer,
    PeerMetricsFetcher,
    build_peer_valuation,
)
from portfolio_thesis_engine.peers.fetcher import PeerFundamentalsProvider
from portfolio_thesis_engine.schemas.peers import (
    PeerComparison,
    PeerSet,
    PeerValuation,
)

console = Console()


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}%"


def _fmt_ratio(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}×"


def _fmt_bps(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value:+.0f} bps"


def _peers_table(peer_set: PeerSet) -> Table:
    table = Table(title=f"{peer_set.target_ticker} — Peer set", title_style="bold magenta")
    table.add_column("Ticker")
    table.add_column("Name")
    table.add_column("Country")
    table.add_column("Source")
    table.add_column("Included")
    table.add_column("Rationale")
    for p in peer_set.peers:
        table.add_row(
            p.ticker,
            p.name,
            p.country or "—",
            p.source,
            "yes" if p.included else "no",
            p.rationale or "—",
        )
    return table


def _fundamentals_table(comparison: PeerComparison) -> Table:
    metrics = [
        ("revenue_growth_3y_cagr", "Revenue growth 3Y", _fmt_pct),
        ("operating_margin", "Operating margin", _fmt_pct),
        ("roic", "ROIC", _fmt_pct),
        ("net_margin", "Net margin", _fmt_pct),
        ("financial_leverage", "Financial leverage", _fmt_ratio),
    ]
    table = Table(
        title="Fundamentals — target vs peer median",
        title_style="bold blue",
    )
    table.add_column("Metric")
    table.add_column("Target", justify="right")
    table.add_column("Peer median", justify="right")
    table.add_column("Δ vs median", justify="right")
    target = comparison.target_fundamentals
    for field, label, fmt in metrics:
        target_val = getattr(target, field)
        median = comparison.peer_median.get(field)
        delta_bps = comparison.target_vs_median_bps.get(field)
        table.add_row(
            label,
            fmt(target_val),
            fmt(median),
            _fmt_bps(delta_bps),
        )
    return table


def _multiples_table(valuation: PeerValuation) -> Table | None:
    m = valuation.multiples
    if m is None:
        return None
    table = Table(
        title="Multiples — target vs peer median",
        title_style="bold blue",
    )
    table.add_column("Metric")
    table.add_column("Target", justify="right")
    table.add_column("Peer median", justify="right")
    table.add_column("Discount/Premium %", justify="right")
    rows = [
        ("P/E", m.target_current_pe, m.peer_median_pe, m.target_discount_pe_pct),
        ("EV/EBITDA", m.target_current_ev_ebitda, m.peer_median_ev_ebitda, m.target_discount_ev_ebitda_pct),
        ("EV/Sales", m.target_current_ev_sales, m.peer_median_ev_sales, m.target_discount_ev_sales_pct),
    ]
    for label, target_val, median, disc in rows:
        table.add_row(
            label,
            _fmt_ratio(target_val),
            _fmt_ratio(median),
            _fmt_pct(disc),
        )
    return table


def _regression_section(valuation: PeerValuation) -> list[str]:
    r = valuation.regression
    if r is None:
        return [
            "[dim]Regression skipped: fewer than min_peers with complete data.[/dim]"
        ]
    lines = [
        "[bold blue]Regression (simple linear)[/bold blue]",
        f"  Model: {r.dependent_variable} ~ "
        + " + ".join(r.explanatory_variables),
        f"  Peers used: {r.n_peers_used}  R²: {r.r_squared:.3f}",
    ]
    if r.target_predicted_multiple is not None:
        lines.append(
            f"  Target predicted {r.dependent_variable}: "
            f"{r.target_predicted_multiple:.2f}× "
            f"(actual {r.target_actual_multiple:.2f}×)"
        )
    if r.residual_bps is not None and r.signal is not None:
        lines.append(
            f"  Residual: {r.residual_bps:+d} bps → {r.signal}"
        )
    return lines


def _run_peers(
    ticker: str,
    export: Path | None,
    discoverer: PeerDiscoverer | None = None,
    fetcher: PeerMetricsFetcher | None = None,
    provider: PeerFundamentalsProvider | None = None,
) -> None:
    discoverer = discoverer or PeerDiscoverer()
    peer_set = discoverer.load_or_create(ticker)
    if not peer_set.peers:
        yaml_path = discoverer._yaml_path(ticker)  # noqa: SLF001
        console.print(
            f"[yellow]No peer declaration for {ticker}.[/yellow] "
            f"Create {yaml_path} or configure an FMP provider."
        )
        raise typer.Exit(code=1)

    if fetcher is None:
        # No provider injected → can't fetch fundamentals, render
        # just the peer declaration.
        console.print(_peers_table(peer_set))
        console.print(
            "[dim]No fundamentals provider configured — "
            "install FMP credentials or inject a provider to see "
            "target-vs-peer comparisons.[/dim]"
        )
        return

    comparison = fetcher.fetch(peer_set)
    if comparison is None:
        console.print(
            "[yellow]Target fundamentals unavailable — "
            "cannot build peer comparison.[/yellow]"
        )
        raise typer.Exit(code=1)

    valuation = build_peer_valuation(
        comparison, min_peers=peer_set.min_peers_regression
    )

    console.print(_peers_table(peer_set))
    console.print(_fundamentals_table(comparison))
    mult = _multiples_table(valuation)
    if mult is not None:
        console.print(mult)
    for line in _regression_section(valuation):
        console.print(line)
    if valuation.summary_bullets:
        console.print("")
        console.print("[bold]Summary[/bold]")
        for b in valuation.summary_bullets:
            console.print(f"  • {b}")

    if export is not None:
        export.parent.mkdir(parents=True, exist_ok=True)
        export.write_text(
            render_peers_markdown(peer_set, comparison, valuation),
            encoding="utf-8",
        )
        console.print(f"\n[dim]Peer report written to {export}[/dim]")


def render_peers_markdown(
    peer_set: PeerSet,
    comparison: PeerComparison,
    valuation: PeerValuation,
) -> str:
    lines: list[str] = [
        f"# {peer_set.target_ticker} — Peer analysis",
        "",
        f"Peer set: {len(peer_set.peers)} peers "
        f"({peer_set.discovery_method})",
        "",
        "## Peers",
        "",
        "| Ticker | Name | Country | Source | Included |",
        "|---|---|---|---|---|",
    ]
    for p in peer_set.peers:
        lines.append(
            f"| {p.ticker} | {p.name} | {p.country or '—'} | "
            f"{p.source} | {'yes' if p.included else 'no'} |"
        )
    lines.extend(["", "## Fundamentals vs peer median", "",
                  "| Metric | Target | Peer median | Δ bps |",
                  "|---|---:|---:|---:|"])
    for field, label in (
        ("revenue_growth_3y_cagr", "Revenue growth 3Y"),
        ("operating_margin", "Operating margin"),
        ("roic", "ROIC"),
        ("net_margin", "Net margin"),
    ):
        lines.append(
            f"| {label} | "
            f"{_fmt_pct(getattr(comparison.target_fundamentals, field))} | "
            f"{_fmt_pct(comparison.peer_median.get(field))} | "
            f"{_fmt_bps(comparison.target_vs_median_bps.get(field))} |"
        )
    m = valuation.multiples
    if m is not None:
        lines.extend([
            "", "## Multiples", "",
            "| Metric | Target | Peer median | Discount % |",
            "|---|---:|---:|---:|",
            f"| P/E | {_fmt_ratio(m.target_current_pe)} | "
            f"{_fmt_ratio(m.peer_median_pe)} | "
            f"{_fmt_pct(m.target_discount_pe_pct)} |",
            f"| EV/EBITDA | {_fmt_ratio(m.target_current_ev_ebitda)} | "
            f"{_fmt_ratio(m.peer_median_ev_ebitda)} | "
            f"{_fmt_pct(m.target_discount_ev_ebitda_pct)} |",
            f"| EV/Sales | {_fmt_ratio(m.target_current_ev_sales)} | "
            f"{_fmt_ratio(m.peer_median_ev_sales)} | "
            f"{_fmt_pct(m.target_discount_ev_sales_pct)} |",
        ])
    r = valuation.regression
    if r is not None:
        lines.extend([
            "", "## Regression", "",
            f"- Model: {r.dependent_variable} ~ "
            + " + ".join(r.explanatory_variables),
            f"- R² {r.r_squared:.3f} over {r.n_peers_used} peers",
        ])
        if r.residual_bps is not None and r.signal is not None:
            lines.append(
                f"- Target predicted {r.dependent_variable}: "
                f"{r.target_predicted_multiple}× (actual "
                f"{r.target_actual_multiple}×), residual "
                f"{r.residual_bps:+d} bps → {r.signal}"
            )
    if valuation.summary_bullets:
        lines.extend(["", "## Summary", ""])
        for b in valuation.summary_bullets:
            lines.append(f"- {b}")
    return "\n".join(lines) + "\n"


def peers(
    ticker: str = typer.Argument(..., help="Target ticker (e.g. 1846.HK)."),
    export: Path | None = typer.Option(
        None,
        "--export",
        help="Write peer-analysis markdown report to PATH.",
    ),
) -> None:
    """Produce a peer-relative analysis (fundamentals, multiples,
    regression) for ``ticker``."""
    _run_peers(ticker, export)


__all__ = ["_run_peers", "peers", "render_peers_markdown"]
