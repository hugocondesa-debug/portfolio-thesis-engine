"""``pte show`` — render the aggregate Ficha view for a ticker.

After :command:`pte process` runs, this command gives the analyst an
at-a-glance view: identity, valuation (E[V], fair value range, upside),
scenario drivers + IRR, a short guardrails summary and a staleness
flag. Reads from the three YAML repositories; never touches the LLM
or external providers.

Usage::

    pte show 1846.HK            # default Rich tables
    pte show 1846.HK --json     # machine-readable output
"""

from __future__ import annotations

import json
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from portfolio_thesis_engine.ficha import FichaBundle, FichaLoader
from portfolio_thesis_engine.schemas.common import GuardrailStatus

console = Console()


def _format_money(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value:,}"


def _format_pct(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}%"


def _identity_table(bundle: FichaBundle) -> Table:
    ficha = bundle.ficha
    state = bundle.canonical_state
    identity = ficha.identity if ficha else (state.identity if state else None)
    table = Table(show_header=False, title="Identity", title_style="bold magenta")
    table.add_column("Field", style="dim")
    table.add_column("Value")
    if identity is None:
        table.add_row("—", "No identity data.")
        return table
    table.add_row("Ticker", identity.ticker)
    table.add_row("Name", identity.name)
    table.add_row("Profile", str(identity.profile.value))
    table.add_row("Currency", str(identity.reporting_currency.value))
    table.add_row("Exchange", identity.exchange)
    if identity.shares_outstanding is not None:
        table.add_row("Shares outstanding", _format_money(identity.shares_outstanding))
    return table


def _valuation_table(bundle: FichaBundle) -> Table | None:
    snap = bundle.valuation_snapshot
    if snap is None:
        return None
    table = Table(show_header=False, title="Valuation", title_style="bold cyan")
    table.add_column("Field", style="dim")
    table.add_column("Value")
    table.add_row("Market price", _format_money(snap.market.price))
    table.add_row("E[V] per share", _format_money(snap.weighted.expected_value))
    table.add_row(
        "Fair value range",
        f"{_format_money(snap.weighted.fair_value_range_low)} — "
        f"{_format_money(snap.weighted.fair_value_range_high)}",
    )
    table.add_row("Upside vs market", _format_pct(snap.weighted.upside_pct))
    table.add_row("Asymmetry ratio", f"{snap.weighted.asymmetry_ratio:.2f}")
    if snap.weighted.weighted_irr_3y is not None:
        table.add_row("Weighted IRR (3y)", _format_pct(snap.weighted.weighted_irr_3y))
    return table


def _scenarios_table(bundle: FichaBundle) -> Table | None:
    snap = bundle.valuation_snapshot
    if snap is None or not snap.scenarios:
        return None
    table = Table(title="Scenarios", title_style="bold green")
    table.add_column("Label")
    table.add_column("Probability", justify="right")
    table.add_column("Revenue CAGR", justify="right")
    table.add_column("Terminal margin", justify="right")
    table.add_column("Target / share", justify="right")
    table.add_column("Upside", justify="right")
    table.add_column("IRR (3y)", justify="right")
    for sc in snap.scenarios:
        target = sc.targets.get("dcf_fcff_per_share")
        table.add_row(
            sc.label,
            _format_pct(sc.probability),
            _format_pct(sc.drivers.revenue_cagr),
            _format_pct(sc.drivers.terminal_margin),
            _format_money(target) if target is not None else "—",
            _format_pct(sc.upside_pct),
            _format_pct(sc.irr_3y),
        )
    return table


def _guardrails_panel(bundle: FichaBundle) -> str | None:
    state = bundle.canonical_state
    if state is None:
        return None
    v = state.validation
    lines = [
        f"Confidence rating: [bold]{v.confidence_rating}[/bold]",
        f"Universal checks: {len(v.universal_checksums)} · "
        f"Profile checks: {len(v.profile_specific_checksums)}",
    ]
    if v.blocking_issues:
        lines.append(f"[red]Blocking issues ({len(v.blocking_issues)})[/red]:")
        for issue in v.blocking_issues:
            lines.append(f"  • {issue}")
    return "\n".join(lines)


def _staleness_line(bundle: FichaBundle) -> str:
    ficha = bundle.ficha
    if ficha is None:
        return "[dim]No ficha saved yet — run `pte process`.[/dim]"
    if ficha.snapshot_age_days is None:
        return "[dim]No valuation on record.[/dim]"
    tone = "red" if ficha.is_stale else "green"
    stale_txt = "STALE" if ficha.is_stale else "fresh"
    return f"[{tone}]Valuation age: {ficha.snapshot_age_days} days ({stale_txt})[/{tone}]"


def _render_rich(bundle: FichaBundle) -> None:
    if not bundle.has_data and bundle.ficha is None:
        console.print(
            f"[red]No data for {bundle.ticker}.[/red] Run `pte process {bundle.ticker}` first."
        )
        return

    console.print(_identity_table(bundle))
    val_table = _valuation_table(bundle)
    if val_table is not None:
        console.print(val_table)
    sc_table = _scenarios_table(bundle)
    if sc_table is not None:
        console.print(sc_table)
    guard = _guardrails_panel(bundle)
    if guard is not None:
        console.print(f"\n[bold]Validation[/bold]\n{guard}")
    console.print(f"\n{_staleness_line(bundle)}")


def _render_json(bundle: FichaBundle) -> None:
    payload: dict[str, Any] = {"ticker": bundle.ticker}
    if bundle.ficha is not None:
        payload["ficha"] = json.loads(bundle.ficha.model_dump_json())
    if bundle.valuation_snapshot is not None:
        snap = bundle.valuation_snapshot
        payload["valuation"] = {
            "snapshot_id": snap.snapshot_id,
            "expected_value": str(snap.weighted.expected_value),
            "fair_value_range": [
                str(snap.weighted.fair_value_range_low),
                str(snap.weighted.fair_value_range_high),
            ],
            "upside_pct": str(snap.weighted.upside_pct),
            "scenarios": [
                {
                    "label": sc.label,
                    "probability": str(sc.probability),
                    "target_per_share": (
                        str(sc.targets.get("dcf_fcff_per_share"))
                        if sc.targets.get("dcf_fcff_per_share") is not None
                        else None
                    ),
                    "upside_pct": str(sc.upside_pct) if sc.upside_pct is not None else None,
                    "irr_3y": str(sc.irr_3y) if sc.irr_3y is not None else None,
                }
                for sc in snap.scenarios
            ],
        }
    console.print_json(data=payload)


def show(
    ticker: str = typer.Argument(..., help="Target ticker (e.g. 1846.HK)."),
    as_json: bool = typer.Option(
        False,
        "--json",
        help="Emit machine-readable JSON instead of Rich tables.",
    ),
) -> None:
    """Render the aggregate :class:`Ficha` view for ``ticker``."""
    bundle = FichaLoader().load(ticker)
    if as_json:
        _render_json(bundle)
    else:
        _render_rich(bundle)

    # Exit code: 0 when at least canonical state or ficha is present;
    # 1 when nothing is on record (sentinel for scripts).
    if not bundle.has_data and bundle.ficha is None:
        raise typer.Exit(code=1)
    # Exit 2 when guardrails FAIL'd at extraction time. Phase 1:
    # canonical_state.validation.blocking_issues is empty unless a
    # blocking guardrail was recorded.
    if (
        bundle.canonical_state is not None
        and bundle.canonical_state.validation.blocking_issues
    ):
        raise typer.Exit(code=2)
    # Stale → exit 0 but caller can inspect output for the warning.
    _ = GuardrailStatus  # keep the import alive for type-stability tools


__all__ = ["show"]
