"""``pte show`` — render the aggregate Ficha view for a ticker.

After :command:`pte process` runs, this command gives the analyst an
at-a-glance view: identity, valuation (E[V], fair value range, upside),
scenario drivers + IRR, a short guardrails summary and a staleness
flag. Reads from the three YAML repositories; never touches the LLM
or external providers.

Phase 1.5.9 added two deep-inspection views:

- ``--detail`` renders the economic balance sheet, NOPAT bridge,
  non-recurring items, per-scenario projection schedules, EV bridges,
  and the base-scenario sensitivity grid.
- ``--scenario bear|base|bull`` zooms into one scenario at a time.

Usage::

    pte show 1846.HK            # default Rich tables
    pte show 1846.HK --detail   # full model transparency
    pte show 1846.HK --scenario base
    pte show 1846.HK --json     # machine-readable output
"""

from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import typer
from rich.console import Console
from rich.table import Table

from portfolio_thesis_engine.ficha import FichaBundle, FichaLoader
from portfolio_thesis_engine.schemas.common import GuardrailStatus
from portfolio_thesis_engine.schemas.valuation import Scenario, ValuationSnapshot

console = Console()


def _format_money(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, Decimal):
        return f"{value:,.2f}"
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


# ----------------------------------------------------------------------
# Phase 1.5.9 — deep-inspection views
# ----------------------------------------------------------------------
def _economic_bs_table(bundle: FichaBundle) -> Table | None:
    state = bundle.canonical_state
    if state is None or not state.analysis.invested_capital_by_period:
        return None
    ic = state.analysis.invested_capital_by_period[0]
    table = Table(
        show_header=False,
        title="Economic balance sheet",
        title_style="bold blue",
    )
    table.add_column("Field", style="dim")
    table.add_column("Value", justify="right")
    table.add_row("Operating assets", _format_money(ic.operating_assets))
    table.add_row("Operating liabilities", _format_money(ic.operating_liabilities))
    table.add_row("[bold]Invested capital[/bold]", _format_money(ic.invested_capital))
    table.add_row("Financial assets (cash + STI)", _format_money(ic.financial_assets))
    table.add_row("Financial liabilities (total)", _format_money(ic.financial_liabilities))
    table.add_row("  · Bank debt", _format_money(ic.bank_debt))
    table.add_row("  · Lease liabilities", _format_money(ic.lease_liabilities))
    table.add_row(
        "Operating working capital", _format_money(ic.operating_working_capital)
    )
    table.add_row("Equity (parent)", _format_money(ic.equity_claims))
    table.add_row("Non-controlling interests", _format_money(ic.nci_claims))
    table.add_row("Cross-check residual", _format_money(ic.cross_check_residual))
    return table


def _nopat_bridge_table(bundle: FichaBundle) -> Table | None:
    """Phase 1.5.9.1 — side-by-side reported vs sustainable bridge. The
    primary column (marked with ★) is the one the DCF + ROIC anchor on."""
    state = bundle.canonical_state
    if state is None or not state.analysis.nopat_bridge_by_period:
        return None
    bridge = state.analysis.nopat_bridge_by_period[0]
    title = f"NOPAT bridge ({bridge.nopat_methodology})"
    has_sustainable = (
        bridge.operating_income_sustainable is not None
        and bridge.non_recurring_operating_items != 0
    )
    primary = bridge.which_used_for_nopat  # "sustainable" | "reported"
    tag_reported = " ★" if primary == "reported" else ""
    tag_sustainable = " ★" if primary == "sustainable" else ""
    table = Table(
        title=title,
        title_style="bold blue",
    )
    table.add_column("Field", style="dim")
    table.add_column(f"Reported{tag_reported}", justify="right")
    if has_sustainable:
        table.add_column(f"Sustainable{tag_sustainable}", justify="right")

    def _row(label: str, reported: Any, sustainable: Any = None) -> None:
        if has_sustainable:
            table.add_row(label, _format_money(reported), _format_money(sustainable))
        else:
            table.add_row(label, _format_money(reported))

    _row(
        "Operating income (EBIT)",
        bridge.operating_income,
        bridge.operating_income_sustainable,
    )
    if bridge.non_recurring_operating_items != 0:
        _row(
            "Non-recurring items",
            bridge.non_recurring_operating_items,
            Decimal("0"),
        )
    if bridge.amortisation > 0:
        _row(
            "+ Amortisation",
            bridge.amortisation,
            bridge.amortisation,
        )
        ebita_reported = (bridge.operating_income or Decimal("0")) + bridge.amortisation
        ebita_sustainable = (
            (bridge.operating_income_sustainable or Decimal("0"))
            + bridge.amortisation
            if has_sustainable
            else None
        )
        _row("[bold]EBITA[/bold]", ebita_reported, ebita_sustainable)
    _row("+ Depreciation", bridge.depreciation, bridge.depreciation)
    _row("[bold]EBITDA[/bold]", bridge.ebitda, bridge.ebitda)
    # Taxes & NOPAT — the "Sustainable" column shows bridge.nopat when
    # primary, and we back out the sustainable tax from the reported one.
    _row(
        "Operating taxes",
        (bridge.operating_taxes if primary == "reported" else _implied_taxes_reported(bridge)),
        bridge.operating_taxes if primary == "sustainable" else None,
    )
    _row(
        "[bold]NOPAT[/bold]",
        bridge.nopat_reported,
        bridge.nopat if has_sustainable else None,
    )
    _row("Finance income", bridge.financial_income)
    _row("Finance expense", bridge.financial_expense)
    _row("Non-operating items", bridge.non_operating_items)
    _row("Reported net income", bridge.reported_net_income)
    return table


def _implied_taxes_reported(bridge: Any) -> Decimal:
    """Derive the reported-basis operating tax when the bridge's
    ``operating_taxes`` field is on the sustainable basis. Rate is
    backed out from the primary NOPAT."""
    if bridge.nopat_reported is None or bridge.operating_income is None:
        return bridge.operating_taxes
    reported_ebita = bridge.operating_income + bridge.amortisation
    return reported_ebita - bridge.nopat_reported


def _sustainable_oi_derivation_tables(bundle: FichaBundle) -> list[Table]:
    """Phase 1.5.10 — per-line sub-item breakdown for every parent that
    contributed to the sustainable operating income adjustment.

    Shows the Module-D decisions the DCF and NOPAT bridge depend on, with
    rationale / confidence / matched rule for each sub-item. Renders one
    table per parent line (scoped to IS lines with at least one
    ``exclude`` / ``flag_for_review`` sub-item)."""
    state = bundle.canonical_state
    if state is None:
        return []
    decomps = getattr(
        state.adjustments, "module_d_note_decompositions", {}
    ) or {}
    out: list[Table] = []
    for key, decomp in decomps.items():
        if not decomp.sub_items:
            continue
        if key.split(":", 1)[0] != "IS":
            continue
        if not any(
            s.action in ("exclude", "flag_for_review") for s in decomp.sub_items
        ):
            continue
        table = Table(
            title=(
                f"Sustainable OI derivation · {decomp.parent_label} "
                f"(reported {_format_money(decomp.parent_value)}, "
                f"method={decomp.method})"
            ),
            title_style="bold yellow",
        )
        table.add_column("Action", style="dim")
        table.add_column("Label")
        table.add_column("Value", justify="right")
        table.add_column("Op × Rec")
        table.add_column("Confidence")
        table.add_column("Rule / Rationale")
        for sub in decomp.sub_items:
            action_tag = {
                "include": "[green][included][/green]",
                "exclude": "[red][excluded][/red]",
                "flag_for_review": "[yellow][flagged][/yellow]",
            }.get(sub.action, sub.action)
            table.add_row(
                action_tag,
                sub.label,
                _format_money(sub.value),
                f"{sub.operational_classification} × {sub.recurrence_classification}",
                sub.confidence,
                f"{sub.matched_rule} — {sub.rationale[:60]}",
            )
        table.add_row(
            "[dim]totals[/dim]",
            "",
            "",
            "",
            "",
            (
                f"sustainable={_format_money(decomp.sustainable_addition)} "
                f"excluded={_format_money(decomp.excluded_total)} "
                f"flagged={_format_money(decomp.flagged_total)}"
            ),
        )
        out.append(table)
    return out


def _sustainable_oi_reconciliation_table(bundle: FichaBundle) -> Table | None:
    """Phase 1.5.10 — walk from reported OI to sustainable OI showing
    each Module-D adjustment summed."""
    state = bundle.canonical_state
    if state is None or not state.analysis.nopat_bridge_by_period:
        return None
    bridge = state.analysis.nopat_bridge_by_period[0]
    if (
        bridge.operating_income_sustainable is None
        and bridge.non_recurring_operating_items == 0
    ):
        return None
    table = Table(
        show_header=False,
        title="Sustainable operating income reconciliation",
        title_style="bold yellow",
    )
    table.add_column("Step", style="dim")
    table.add_column("Value", justify="right")
    reported = bridge.operating_income or Decimal("0")
    table.add_row("Reported OI", _format_money(reported))
    if bridge.non_recurring_items_detail:
        non_rec_total = sum(
            (s.value for s in bridge.non_recurring_items_detail),
            start=Decimal("0"),
        )
        table.add_row("− Non-recurring items (Module D)", _format_money(non_rec_total))
    elif bridge.non_recurring_operating_items != 0:
        table.add_row(
            "− Non-recurring items (regex fallback)",
            _format_money(bridge.non_recurring_operating_items),
        )
    sustainable = bridge.operating_income_sustainable or reported
    table.add_row("[bold]Sustainable OI[/bold]", _format_money(sustainable))
    return table


def _decomposition_coverage_table(bundle: FichaBundle) -> Table | None:
    """Phase 1.5.10 — per-statement decomposition coverage."""
    state = bundle.canonical_state
    if state is None:
        return None
    coverage = getattr(state.adjustments, "module_d_coverage", None)
    if coverage is None:
        return None
    table = Table(
        title="Module D decomposition coverage",
        title_style="bold blue",
    )
    table.add_column("Statement")
    table.add_column("Total", justify="right")
    table.add_column("Decomposed (note_table)", justify="right")
    table.add_column("Fallback (label)", justify="right")
    table.add_column("Not decomposable", justify="right")
    for stmt, total, decomp, fb, nd in (
        ("IS", coverage.is_total, coverage.is_decomposed,
         coverage.is_fallback, coverage.is_not_decomposable),
        ("BS", coverage.bs_total, coverage.bs_decomposed,
         coverage.bs_fallback, coverage.bs_not_decomposable),
        ("CF", coverage.cf_total, coverage.cf_decomposed,
         coverage.cf_fallback, coverage.cf_not_decomposable),
    ):
        table.add_row(stmt, str(total), str(decomp), str(fb), str(nd))
    return table


def _ratios_table(bundle: FichaBundle) -> Table | None:
    state = bundle.canonical_state
    if state is None or not state.analysis.ratios_by_period:
        return None
    r = state.analysis.ratios_by_period[0]
    table = Table(
        show_header=False, title="Key ratios", title_style="bold blue"
    )
    table.add_column("Field", style="dim")
    table.add_column("Value", justify="right")
    # Phase 1.5.9.1 — primary ROIC uses sustainable NOPAT; reported ROIC
    # surfaces for reconciliation with accounting statements.
    table.add_row("ROIC (primary)", _format_pct(r.roic))
    if r.roic_reported is not None:
        table.add_row("ROIC (reported)", _format_pct(r.roic_reported))
    table.add_row("ROE", _format_pct(r.roe))
    table.add_row("Operating margin (reported)", _format_pct(r.operating_margin))
    if r.sustainable_operating_margin is not None:
        table.add_row(
            "Operating margin (sustainable)",
            _format_pct(r.sustainable_operating_margin),
        )
    table.add_row("EBITDA margin", _format_pct(r.ebitda_margin))
    table.add_row("Net debt / EBITDA", _format_money(r.net_debt_ebitda))
    table.add_row("CapEx / Revenue", _format_pct(r.capex_revenue))
    return table


def _adjustments_table(bundle: FichaBundle) -> Table | None:
    state = bundle.canonical_state
    if state is None:
        return None
    adj_groups = [
        ("A (Taxes)", state.adjustments.module_a_taxes),
        ("B (Provisions)", state.adjustments.module_b_provisions),
        ("C (Leases)", state.adjustments.module_c_leases),
        ("D (Pensions)", state.adjustments.module_d_pensions),
        ("E (SBC)", state.adjustments.module_e_sbc),
        ("F (Capitalise)", state.adjustments.module_f_capitalize),
    ]
    rows = [(g, a) for g, group in adj_groups for a in group]
    if not rows:
        return None
    table = Table(title="Module adjustments", title_style="bold blue")
    table.add_column("Module")
    table.add_column("Description")
    table.add_column("Amount", justify="right")
    table.add_column("Rationale")
    for group, adj in rows:
        table.add_row(
            f"{group} · {adj.module}",
            adj.description,
            _format_money(adj.amount),
            adj.rationale[:60] + ("…" if len(adj.rationale) > 60 else ""),
        )
    return table


def _projection_table(scenario: Scenario) -> Table | None:
    if not scenario.projection:
        return None
    table = Table(
        title=f"Projection · {scenario.label}",
        title_style="bold yellow",
    )
    table.add_column("Year", justify="right")
    table.add_column("Revenue", justify="right")
    table.add_column("Op margin", justify="right")
    table.add_column("EBIT", justify="right")
    table.add_column("+ Amort", justify="right")
    table.add_column("EBITA", justify="right")
    table.add_column("NOPAT", justify="right")
    table.add_column("Depr", justify="right")
    table.add_column("CapEx", justify="right")
    table.add_column("ΔWC", justify="right")
    table.add_column("FCFF", justify="right")
    table.add_column("DF", justify="right")
    table.add_column("PV FCFF", justify="right")
    for row in scenario.projection:
        year_label = "0 (base)" if row.year == 0 else str(row.year)
        margin_str = _format_pct(row.operating_margin_used)
        if row.operating_margin_sustainable is not None:
            margin_str += f" / {_format_pct(row.operating_margin_sustainable)}*"
        table.add_row(
            year_label,
            _format_money(row.revenue),
            margin_str,
            _format_money(row.ebit),
            _format_money(row.amort_for_ebita),
            _format_money(row.ebita),
            _format_money(row.nopat),
            _format_money(row.depreciation),
            _format_money(row.capex),
            _format_money(row.wc_change),
            _format_money(row.fcff),
            _format_money(row.discount_factor),
            _format_money(row.pv_fcff),
        )
    return table


def _terminal_table(scenario: Scenario) -> Table | None:
    if scenario.terminal is None:
        return None
    t = scenario.terminal
    table = Table(
        show_header=False,
        title=f"Terminal · {scenario.label}",
        title_style="bold yellow",
    )
    table.add_column("Field", style="dim")
    table.add_column("Value", justify="right")
    table.add_row("Revenue (final year)", _format_money(t.revenue_final_year))
    table.add_row("Terminal growth", _format_pct(t.terminal_growth))
    table.add_row("Terminal margin", _format_pct(t.terminal_margin))
    table.add_row("Terminal WACC", _format_pct(t.terminal_wacc))
    table.add_row("Terminal NOPAT", _format_money(t.terminal_nopat))
    table.add_row("Terminal FCFF", _format_money(t.terminal_fcff))
    table.add_row("[bold]Terminal value[/bold]", _format_money(t.terminal_value))
    table.add_row("PV terminal", _format_money(t.pv_terminal))
    return table


def _ev_breakdown_table(scenario: Scenario) -> Table | None:
    if scenario.enterprise_value_breakdown is None:
        return None
    b = scenario.enterprise_value_breakdown
    table = Table(
        show_header=False,
        title=f"Enterprise value breakdown · {scenario.label}",
        title_style="bold yellow",
    )
    table.add_column("Field", style="dim")
    table.add_column("Value", justify="right")
    table.add_row("Sum PV explicit period", _format_money(b.sum_pv_explicit))
    table.add_row("PV terminal", _format_money(b.pv_terminal))
    table.add_row("[bold]Total EV[/bold]", _format_money(b.total_ev))
    return table


def _equity_bridge_table(scenario: Scenario) -> Table | None:
    if scenario.equity_bridge is None:
        return None
    b = scenario.equity_bridge
    table = Table(
        show_header=False,
        title=f"EV → equity bridge · {scenario.label}",
        title_style="bold yellow",
    )
    table.add_column("Field", style="dim")
    table.add_column("Value", justify="right")
    table.add_row("[bold]Enterprise value[/bold]", _format_money(b.enterprise_value))
    table.add_row("+ Cash and equivalents", _format_money(b.cash_and_equivalents))
    table.add_row("− Financial debt", _format_money(b.financial_debt))
    if b.lease_liabilities != 0:
        table.add_row("− Lease liabilities", _format_money(b.lease_liabilities))
    if b.non_controlling_interests != 0:
        table.add_row("− NCI", _format_money(b.non_controlling_interests))
    if b.other_adjustments != 0:
        table.add_row("± Other adjustments", _format_money(b.other_adjustments))
    table.add_row("[bold]Equity value[/bold]", _format_money(b.equity_value))
    table.add_row("Shares outstanding", _format_money(b.shares_outstanding))
    table.add_row(
        "[bold]Target per share[/bold]", _format_money(b.target_per_share)
    )
    return table


def _one_sensitivity_table(grid: Any) -> Table:
    table = Table(
        title=(
            f"Sensitivity · {grid.scenario_label} "
            f"(target/share, {grid.axis_y} rows × {grid.axis_x} cols)"
        ),
        title_style="bold red",
    )
    table.add_column(f"{grid.axis_y} \\ {grid.axis_x}", justify="right")
    for x in grid.x_values:
        table.add_column(_format_pct(x), justify="right")
    for i, y in enumerate(grid.y_values):
        cells = [_format_pct(y)]
        for j, _ in enumerate(grid.x_values):
            v = grid.target_per_share[i][j]
            cells.append("—" if v == 0 else _format_money(v))
        table.add_row(*cells)
    return table


def _sensitivity_tables(snap: ValuationSnapshot) -> list[Table]:
    return [_one_sensitivity_table(g) for g in snap.sensitivities]


def _market_extras(snap: ValuationSnapshot, bundle: FichaBundle) -> Table | None:
    state = bundle.canonical_state
    if state is None:
        return None
    table = Table(
        show_header=False,
        title="Market snapshot",
        title_style="bold cyan",
    )
    table.add_column("Field", style="dim")
    table.add_column("Value", justify="right")
    m = snap.market
    table.add_row("Price", _format_money(m.price))
    table.add_row("Price date", m.price_date)
    table.add_row("Shares outstanding", _format_money(m.shares_outstanding))
    table.add_row("Market cap", _format_money(m.market_cap))
    table.add_row("Currency", str(m.currency.value))
    if m.wacc is not None:
        table.add_row("WACC", _format_pct(m.wacc))
    if state.analysis.nopat_bridge_by_period and m.market_cap and m.shares_outstanding:
        # EV/EBITDA (current) — use equity_value + net_debt proxy from IC.
        bridge = state.analysis.nopat_bridge_by_period[0]
        ic_list = state.analysis.invested_capital_by_period
        if ic_list and bridge.ebitda != 0:
            ic = ic_list[0]
            net_debt = ic.financial_liabilities - ic.financial_assets
            ev_current = m.market_cap + net_debt + ic.nci_claims
            table.add_row(
                "EV / EBITDA (current)",
                f"{ev_current / bridge.ebitda:.2f}×",
            )
    return table


# ----------------------------------------------------------------------
# Renderers
# ----------------------------------------------------------------------
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


def _render_detail(bundle: FichaBundle, scenario_filter: str | None = None) -> None:
    """Phase 1.5.9 — deep inspection view."""
    if not bundle.has_data and bundle.ficha is None:
        console.print(
            f"[red]No data for {bundle.ticker}.[/red] Run `pte process {bundle.ticker}` first."
        )
        return

    console.print(_identity_table(bundle))
    snap = bundle.valuation_snapshot
    if snap is not None:
        extras = _market_extras(snap, bundle)
        if extras is not None:
            console.print(extras)
        val_table = _valuation_table(bundle)
        if val_table is not None:
            console.print(val_table)

    for builder in (
        _economic_bs_table,
        _nopat_bridge_table,
        _sustainable_oi_reconciliation_table,
        _ratios_table,
        _adjustments_table,
    ):
        t = builder(bundle)
        if t is not None:
            console.print(t)

    # Phase 1.5.10 — Module D sub-item breakdowns + coverage.
    for sub_table in _sustainable_oi_derivation_tables(bundle):
        console.print(sub_table)
    coverage_table = _decomposition_coverage_table(bundle)
    if coverage_table is not None:
        console.print(coverage_table)

    sc_table = _scenarios_table(bundle)
    if sc_table is not None:
        console.print(sc_table)

    if snap is not None:
        for sc in snap.scenarios:
            if scenario_filter is not None and sc.label != scenario_filter:
                continue
            for builder in (
                _projection_table,
                _terminal_table,
                _ev_breakdown_table,
                _equity_bridge_table,
            ):
                t = builder(sc)
                if t is not None:
                    console.print(t)

        for sens_table in _sensitivity_tables(snap):
            console.print(sens_table)
        console.print(
            "\n[dim]* sustainable operating margin — excludes non-recurring "
            "items (other gains, grants, FV remeasurements, etc.). See the "
            "NOPAT bridge above for the full reconciliation.[/dim]"
        )

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
    detail: bool = typer.Option(
        False,
        "--detail",
        help=(
            "Render the full model: economic balance sheet, NOPAT bridge, "
            "per-scenario projection + EV bridge, sensitivity grid."
        ),
    ),
    scenario: str | None = typer.Option(
        None,
        "--scenario",
        help=(
            "Deep-dive a single scenario (bear | base | bull). Implies --detail."
        ),
    ),
) -> None:
    """Render the aggregate :class:`Ficha` view for ``ticker``."""
    bundle = FichaLoader().load(ticker)
    if as_json:
        _render_json(bundle)
    elif detail or scenario is not None:
        _render_detail(bundle, scenario_filter=scenario)
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
