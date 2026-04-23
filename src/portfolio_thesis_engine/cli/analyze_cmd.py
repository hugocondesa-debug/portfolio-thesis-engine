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
    attribute_roe_5way_change,
    attribute_roe_change,
    attribute_roic_change,
)
from portfolio_thesis_engine.analytical.historicals import HistoricalNormalizer
from portfolio_thesis_engine.capital import WACCGenerator
from portfolio_thesis_engine.capital.loaders import (
    build_generator_inputs_from_state,
)
from portfolio_thesis_engine.dcf.orchestrator import DCFOrchestrator
from portfolio_thesis_engine.dcf.schemas import DCFValuationResult
from portfolio_thesis_engine.schemas.cost_of_capital import WACCComputation
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


def _dupont_5way_table(ts: CompanyTimeSeries) -> Table | None:
    entries = [
        (r.period, r.dupont_5way) for r in ts.records if r.dupont_5way is not None
    ]
    if not entries:
        return None
    table = Table(
        title="DuPont 5-way ROE decomposition",
        title_style="bold blue",
    )
    table.add_column("Period")
    table.add_column("Tax burden", justify="right")
    table.add_column("Int burden", justify="right")
    table.add_column("Op margin", justify="right")
    table.add_column("Asset turn", justify="right")
    table.add_column("Leverage", justify="right")
    table.add_column("ROE (comp)", justify="right")
    table.add_column("ROE (rep)", justify="right")
    for period, d in entries:
        table.add_row(
            period,
            _fmt_ratio(d.tax_burden),
            _fmt_ratio(d.interest_burden),
            _fmt_pct(d.operating_margin),
            _fmt_ratio(d.asset_turnover),
            _fmt_ratio(d.financial_leverage),
            _fmt_pct(d.roe_computed),
            _fmt_pct(d.roe_reported),
        )
    return table


def _roe_5way_attribution_section(ts: CompanyTimeSeries) -> list[str]:
    annuals = _consecutive_annuals(ts)
    lines: list[str] = []
    if len(annuals) < 2:
        return lines
    any_shown = False
    for i in range(1, len(annuals)):
        a = annuals[i - 1]
        b = annuals[i]
        if a.dupont_5way is None or b.dupont_5way is None:
            continue
        attr = attribute_roe_5way_change(a.dupont_5way, b.dupont_5way)
        if attr is None:
            continue
        if not any_shown:
            lines.append("[bold blue]ROE attribution (DuPont 5-way)[/bold blue]")
            any_shown = True
        lines.append(
            f"  {a.period} → {b.period}: ΔROE {_fmt_bps(attr.roe_delta_bps)}"
        )
        lines.append(
            f"    Tax burden contribution:       {_fmt_bps(attr.tax_burden_contribution_bps)}"
        )
        lines.append(
            f"    Interest burden contribution:  {_fmt_bps(attr.interest_burden_contribution_bps)}"
        )
        lines.append(
            f"    Operating margin contribution: {_fmt_bps(attr.operating_margin_contribution_bps)}"
        )
        lines.append(
            f"    Asset turnover contribution:   {_fmt_bps(attr.asset_turnover_contribution_bps)}"
        )
        lines.append(
            f"    Leverage contribution:         {_fmt_bps(attr.financial_leverage_contribution_bps)}"
        )
        lines.append(
            f"    Cross residual:                {_fmt_bps(attr.cross_residual_bps)}"
        )
    return lines


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
    table.add_row("Revenue YoY growth (audited)", _fmt_pct(t.revenue_yoy_growth))
    if t.revenue_yoy_growth_preliminary is not None:
        label = f"Revenue YoY ({t.preliminary_signal_period or 'preliminary'})"
        table.add_row(label, _fmt_pct(t.revenue_yoy_growth_preliminary))
    table.add_row("Revenue CAGR (2Y)", _fmt_pct(t.revenue_cagr_2y))
    table.add_row("Revenue CAGR (3Y)", _fmt_pct(t.revenue_cagr_3y))
    table.add_row("Revenue CAGR (5Y)", _fmt_pct(t.revenue_cagr_5y))
    table.add_row("Revenue trajectory (audited)", t.revenue_trajectory)
    if t.revenue_trajectory_incl_preliminary != t.revenue_trajectory:
        table.add_row(
            "Revenue trajectory (incl. prelim)",
            t.revenue_trajectory_incl_preliminary,
        )
    table.add_row(
        "Operating margin Δ", _fmt_bps(t.operating_margin_delta_bps)
    )
    table.add_row("Margin trajectory", t.operating_margin_trajectory)
    table.add_row("ROIC Δ", _fmt_bps(t.roic_delta_bps))
    table.add_row("ROIC trajectory", t.roic_trajectory)
    table.add_row("ROIC spread trend", t.roic_spread_trend)
    # Sprint 2B Part C — capital intensity / CCC / CFO quality.
    if t.capex_revenue_ratio is not None:
        table.add_row("CapEx / Revenue", _fmt_pct(t.capex_revenue_ratio))
    if t.working_capital_intensity is not None:
        table.add_row(
            "Working capital intensity",
            _fmt_pct(t.working_capital_intensity),
        )
    if t.cfo_revenue_ratio is not None:
        table.add_row("CFO / Revenue", _fmt_pct(t.cfo_revenue_ratio))
    if t.cash_conversion_cycle is not None:
        table.add_row(
            "Cash conversion cycle",
            f"{t.cash_conversion_cycle:.0f} days",
        )
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


def _reverse_summary_section(
    ticker: str, dcf_result: DCFValuationResult | None
) -> list[str]:
    """Sprint 4A-alpha.4 Part E — compact market-implied assumptions
    block. Runs only when (a) DCF result is present, (b) market price
    is known, and (c) at least one solve converges. Silent otherwise
    so we never blow up the analyze command."""
    if dcf_result is None or not dcf_result.scenarios_run:
        return []
    if dcf_result.market_price is None or dcf_result.market_price == 0:
        return []
    try:
        from portfolio_thesis_engine.analytical.historicals import (
            HistoricalNormalizer,
        )
        from portfolio_thesis_engine.dcf.profiles import (
            load_valuation_profile,
        )
        from portfolio_thesis_engine.dcf.reverse import (
            ReverseDCFSolver,
            assess_plausibility,
        )
        from portfolio_thesis_engine.dcf.scenarios import load_scenarios

        scenario_set = load_scenarios(ticker)
        valuation_profile = load_valuation_profile(ticker)
        if scenario_set is None:
            return []
        base = next(
            (s for s in scenario_set.scenarios if s.name == "base"),
            scenario_set.scenarios[0] if scenario_set.scenarios else None,
        )
        if base is None:
            return []

        from portfolio_thesis_engine.dcf.orchestrator import DCFOrchestrator

        orch = DCFOrchestrator()
        state = orch._latest_canonical_state(ticker)  # noqa: SLF001
        if state is None:
            return []
        stage_1 = orch._stage_1_wacc(ticker, state)  # noqa: SLF001
        stage_3 = orch._stage_3_wacc(  # noqa: SLF001
            state, valuation_profile, stage_1
        )
        pi = orch._period_inputs(  # noqa: SLF001
            ticker=ticker,
            state=state,
            stage_1_wacc=stage_1,
            stage_3_wacc=stage_3,
            valuation_profile=valuation_profile,
        )
        peers = orch._load_peer_comparison(ticker)  # noqa: SLF001
        hist = HistoricalNormalizer().normalize(ticker).records

        solver = ReverseDCFSolver()
        target = dcf_result.market_price
        # Focus on the three drivers that typically converge for P1.
        drivers = ["operating_margin", "wacc", "capex_intensity"]
        implieds = [
            solver.solve(
                scenario=base,
                valuation_profile=valuation_profile,
                period_inputs=pi,
                base_drivers=scenario_set.base_drivers,
                peer_comparison=peers,
                solve_for=d,
                target_fv=target,
            )
            for d in drivers
        ]
        plausibilities = [
            assess_plausibility(i, historicals=hist, auto_wacc=stage_1)
            for i in implieds
        ]
    except Exception:
        return []

    lines = ["[bold cyan]Market-implied assumptions (reverse DCF)[/bold cyan]"]
    lines.append(
        f"  Market {target:,.2f} implies (vs base scenario):"
    )
    for implied, plaus in zip(implieds, plausibilities, strict=True):
        if implied.implied_value is None:
            continue
        gap_str = (
            f"{(implied.gap_vs_baseline * Decimal('10000')):+.0f} bps"
            if implied.gap_vs_baseline is not None
            else "—"
        )
        lines.append(
            f"    - {implied.display_name}: "
            f"{implied.implied_value * Decimal('100'):.2f}% "
            f"({gap_str}, [{plaus.plausibility}])"
        )
    low_count = sum(
        1 for p in plausibilities
        if p.plausibility in ("LOW", "VERY_LOW")
    )
    if low_count:
        lines.append(
            f"  {low_count} of {len(plausibilities)} converged drivers rated "
            "LOW or VERY_LOW plausibility vs company evidence."
        )
    lines.append(
        f"  See `pte reverse {ticker} --enumerate` for the full matrix."
    )
    return lines


def _dcf_summary_section(result: DCFValuationResult | None) -> list[str]:
    if result is None or not result.scenarios_run:
        return []
    lines = ["[bold cyan]Scenario-weighted DCF[/bold cyan]"]
    ev = result.expected_value_per_share
    if ev is not None:
        upside = (
            f" ({result.implied_upside_downside_pct:+.1f}% vs market)"
            if result.implied_upside_downside_pct is not None
            else ""
        )
        lines.append(f"  Expected value: {ev:,.2f}{upside}")
    base = next(
        (s for s in result.scenarios_run if s.scenario_name == "base"),
        result.scenarios_run[0],
    )
    lines.append(
        f"  Base scenario: {base.fair_value_per_share:,.2f} "
        f"({base.scenario_probability * 100:.0f}% probability)"
    )
    if result.p25_value_per_share is not None and result.p75_value_per_share is not None:
        lines.append(
            f"  P25-P75 range: {result.p25_value_per_share:,.2f} – "
            f"{result.p75_value_per_share:,.2f}"
        )
    warning_count = sum(
        1 for w in result.warnings if w.severity != "INFO"
    )
    if warning_count:
        lines.append(
            f"  Warnings: {warning_count} "
            f"(see `pte valuation {result.ticker}` for detail)"
        )
    lines.append(f"  See `pte valuation {result.ticker}` for full report.")
    return lines


def _wacc_section(wacc: WACCComputation | None) -> list[str]:
    if wacc is None:
        return []
    coe = wacc.cost_of_equity
    lines = ["[bold cyan]Cost of Capital (auto-generated)[/bold cyan]"]
    lines.append(
        f"  Currency regime: {coe.currency_regime}"
        + (
            f" (|Δinflation| {coe.inflation_differential_abs:.4f})"
            if coe.inflation_differential_abs is not None
            else ""
        )
    )
    lines.append(
        f"  Rf: {coe.risk_free_rate * 100:.2f}% ({coe.risk_free_source})"
    )
    lines.append(
        f"  Industry β: unlevered {coe.industry_unlevered_beta:.2f} "
        f"({coe.industry_key}) → levered {coe.levered_beta:.2f} "
        f"(D/E {coe.debt_to_equity:.2f}, t {coe.marginal_tax_rate:.2f})"
    )
    lines.append(
        f"  ERP {coe.mature_market_erp * 100:.2f}% + weighted CRP "
        f"{coe.weighted_crp * 100:.2f}%"
    )
    if coe.revenue_geography:
        geo_parts = [
            f"{country} {weight * 100:.0f}%"
            for country, weight in coe.revenue_geography.items()
        ]
        lines.append(f"    Geography: {', '.join(geo_parts)}")
    lines.append(f"  CoE: {coe.cost_of_equity_final * 100:.2f}%")
    cod = wacc.cost_of_debt
    if cod.is_applicable and cod.cost_of_debt_aftertax is not None:
        lines.append(
            f"  CoD: pretax {cod.cost_of_debt_pretax * 100:.2f}% "
            f"(synthetic {cod.synthetic_rating}) → after-tax "
            f"{cod.cost_of_debt_aftertax * 100:.2f}%"
        )
    else:
        lines.append(f"  CoD: N/A ({cod.rationale or 'not applicable'})")
    lines.append(
        f"  Weights: equity {wacc.equity_weight * 100:.1f}%, "
        f"debt {wacc.debt_weight * 100:.1f}%"
    )
    lines.append(
        f"  [bold]WACC: {wacc.wacc * 100:.2f}%[/bold]"
    )
    if wacc.manual_wacc is not None:
        lines.append(
            f"  Manual WACC: {wacc.manual_wacc * 100:.2f}% "
            f"(Δ {wacc.manual_vs_computed_bps:+d} bps vs auto)"
        )
    return lines


def _restatement_pattern_section(ts: CompanyTimeSeries) -> list[str]:
    patterns = ts.restatement_patterns
    if not patterns:
        return []
    lines = ["[bold red]Restatement patterns[/bold red]"]
    for p in patterns:
        lines.append(
            f"  {p.period_comparison}: {p.event_count} events, "
            f"{p.dominant_direction}, "
            f"{'systemic' if p.systemic_flag else 'one-off'} "
            f"→ {p.classification}"
        )
        if p.affected_metric_classes:
            lines.append(
                f"    Metric classes: {', '.join(p.affected_metric_classes)}"
            )
    return lines


def _restatement_narrative_section(ts: CompanyTimeSeries) -> list[str]:
    links = ts.restatement_narrative_links
    if not links:
        return []
    lines = ["[bold]Restatement ↔ narrative cross-references[/bold]"]
    for link in links:
        lines.append(
            f"  {link.restatement_period} restatement ↔ "
            f"{link.narrative_period} narrative ({link.relevance}): "
            f"{link.linked_theme}"
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
        source = (
            f" (from {s.earnings_quality_source_period})"
            if s.earnings_quality_source_period
            else ""
        )
        lines.append(
            f"  Earnings quality composite: {s.earnings_quality_score}/100{source}"
        )
    lines.append(f"  Balance sheet: {s.balance_sheet_strength}")
    if s.preliminary_caveat_bullets:
        lines.append("")
        lines.append("[bold]Preliminary caveats[/bold]")
        for b in s.preliminary_caveat_bullets:
            lines.append(f"  ⚠ {b}")
    if s.summary_bullets:
        lines.append("")
        lines.append("[bold]Summary[/bold]")
        for b in s.summary_bullets:
            lines.append(f"  • {b}")
    return lines


# ----------------------------------------------------------------------
# Markdown export
# ----------------------------------------------------------------------
def render_analytical_markdown(
    ts: CompanyTimeSeries,
    auto_wacc: WACCComputation | None = None,
    dcf_result: DCFValuationResult | None = None,
) -> str:
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

    # DuPont 5-way
    dupont5_rows = [r for r in ts.records if r.dupont_5way is not None]
    if dupont5_rows:
        lines.extend([
            "",
            "## DuPont 5-way ROE decomposition",
            "",
            "| Period | Tax burden | Int burden | Op margin % | Asset turn | Leverage | ROE computed | ROE reported |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ])
        for r in dupont5_rows:
            d = r.dupont_5way
            assert d is not None
            lines.append(
                f"| {r.period} | {_fmt_ratio(d.tax_burden)} | "
                f"{_fmt_ratio(d.interest_burden)} | "
                f"{_fmt_pct(d.operating_margin)} | "
                f"{_fmt_ratio(d.asset_turnover)} | "
                f"{_fmt_ratio(d.financial_leverage)} | "
                f"{_fmt_pct(d.roe_computed)} | "
                f"{_fmt_pct(d.roe_reported)} |"
            )
    # DuPont 5-way attribution
    roe5_attr_lines = _roe_5way_attribution_section(ts)
    if roe5_attr_lines:
        lines.extend(["", "### ROE 5-way attribution", ""])
        for raw in roe5_attr_lines:
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

    # Restatement events + patterns + narrative links
    if ts.restatement_events:
        lines.extend([
            "",
            f"## Restatement events ({len(ts.restatement_events)})",
            "",
            "| Period | Metric | Class | From | To | Δ% | Direction | Severity |",
            "|---|---|---|---:|---:|---:|---|---|",
        ])
        for e in ts.restatement_events:
            lines.append(
                f"| {e.period} | {e.metric} | {e.metric_class} | "
                f"{_fmt_money(e.source_a_value)} | "
                f"{_fmt_money(e.source_b_value)} | "
                f"{_fmt_pct(e.delta_pct)} | {e.direction or '—'} | "
                f"{e.severity} |"
            )
    if ts.restatement_patterns:
        lines.extend(["", "### Restatement patterns", ""])
        for p in ts.restatement_patterns:
            lines.append(
                f"- {p.period_comparison} — {p.event_count} events, "
                f"{p.dominant_direction}, "
                f"{'systemic' if p.systemic_flag else 'one-off'} "
                f"→ {p.classification} "
                f"(classes: {', '.join(p.affected_metric_classes) or 'n/a'})"
            )
    if ts.restatement_narrative_links:
        lines.extend(["", "### Restatement ↔ narrative links", ""])
        for link in ts.restatement_narrative_links:
            lines.append(
                f"- {link.restatement_period} ↔ {link.narrative_period} "
                f"({link.relevance}): {link.linked_theme}"
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

    # Sprint 3 — Cost of capital (auto-generated)
    if auto_wacc is not None:
        coe = auto_wacc.cost_of_equity
        lines.extend([
            "",
            "## Cost of Capital (auto-generated)",
            "",
            f"- Currency regime: {coe.currency_regime}",
            f"- Rf: {coe.risk_free_rate * 100:.2f}% ({coe.risk_free_source})",
            f"- Industry β (unlevered): {coe.industry_unlevered_beta:.2f} ({coe.industry_key})",
            f"- Levered β: {coe.levered_beta:.2f} (D/E {coe.debt_to_equity:.2f}, tax {coe.marginal_tax_rate:.2f})",
            f"- ERP + weighted CRP: {(coe.mature_market_erp + coe.weighted_crp) * 100:.2f}%",
            f"- CoE: {coe.cost_of_equity_final * 100:.2f}%",
        ])
        cod = auto_wacc.cost_of_debt
        if cod.is_applicable and cod.cost_of_debt_aftertax is not None:
            lines.append(
                f"- CoD (after-tax): {cod.cost_of_debt_aftertax * 100:.2f}% "
                f"(synthetic {cod.synthetic_rating})"
            )
        else:
            lines.append(f"- CoD: N/A — {cod.rationale}")
        lines.append(f"- **WACC: {auto_wacc.wacc * 100:.2f}%**")
        if auto_wacc.manual_wacc is not None:
            lines.append(
                f"- Manual WACC: {auto_wacc.manual_wacc * 100:.2f}% "
                f"(Δ {auto_wacc.manual_vs_computed_bps:+d} bps)"
            )

    # Sprint 4A-alpha — scenario-weighted DCF summary.
    if dcf_result is not None and dcf_result.scenarios_run:
        lines.extend([
            "",
            "## Scenario-weighted DCF",
            "",
            "| Scenario | Probability | FV / share |",
            "|---|---:|---:|",
        ])
        for v in dcf_result.scenarios_run:
            lines.append(
                f"| {v.scenario_name} | "
                f"{v.scenario_probability * 100:.0f}% | "
                f"{v.fair_value_per_share:,.2f} |"
            )
        if dcf_result.expected_value_per_share is not None:
            lines.append("")
            lines.append(
                f"**Expected value per share:** "
                f"{dcf_result.expected_value_per_share:,.2f}"
            )
        if dcf_result.implied_upside_downside_pct is not None:
            lines.append(
                f"**Implied upside/downside:** "
                f"{dcf_result.implied_upside_downside_pct:+.1f}%"
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
def _compute_dcf(ticker: str) -> DCFValuationResult | None:
    """Sprint 4A-alpha — best-effort DCF orchestration. Silent
    failure when scenarios.yaml or valuation_profile.yaml are absent."""
    try:
        return DCFOrchestrator().run(ticker)
    except Exception:
        return None


def _compute_auto_wacc(
    ticker: str, normalizer: HistoricalNormalizer
) -> WACCComputation | None:
    """Best-effort WACC auto-generation. Returns ``None`` on any
    failure (missing canonical state, unknown currency/industry); the
    CLI treats auto-WACC as an optional enhancement."""
    try:
        states = normalizer._load_all_states(ticker)  # noqa: SLF001
        if not states:
            return None
        state = states[-1]
        # Pull manual WACC from wacc_inputs.md when available for the
        # audit-trail comparison.
        from portfolio_thesis_engine.analytical.historicals import (
            _load_wacc_for_ticker,
        )

        manual_wacc = _load_wacc_for_ticker(ticker)
        manual_decimal = manual_wacc / Decimal("100") if manual_wacc is not None else None
        inputs = build_generator_inputs_from_state(
            ticker,
            state,
            manual_wacc=manual_decimal,
            marginal_tax_rate=Decimal("0.165"),
        )
        return WACCGenerator().generate(inputs)
    except Exception:
        return None


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
    auto_wacc = _compute_auto_wacc(ticker, normalizer)
    dcf_result = _compute_dcf(ticker)

    # 1. Periods
    console.print(_render_periods_table(ts))
    # 2. Economic BS evolution
    ebs = _economic_bs_table(ts)
    if ebs is not None:
        console.print(ebs)
    # 3. DuPont 3-way + 5-way
    dupont = _dupont_table(ts)
    if dupont is not None:
        console.print(dupont)
    dupont5 = _dupont_5way_table(ts)
    if dupont5 is not None:
        console.print(dupont5)
    # 4. ROIC
    roic = _roic_table(ts)
    if roic is not None:
        console.print(roic)
    # 4b. DuPont + ROIC period-over-period attribution
    for line in _roe_attribution_section(ts):
        console.print(line)
    for line in _roe_5way_attribution_section(ts):
        console.print(line)
    for line in _roic_attribution_section(ts):
        console.print(line)
    # 4c. Auto-generated WACC (Sprint 3)
    for line in _wacc_section(auto_wacc):
        console.print(line)
    # 4d. Scenario-weighted DCF summary (Sprint 4A-alpha)
    for line in _dcf_summary_section(dcf_result):
        console.print(line)
    # 4e. Market-implied assumptions summary (Sprint 4A-alpha.4)
    for line in _reverse_summary_section(ticker, dcf_result):
        console.print(line)
    # 5. Trends
    trends = _trends_table(ts)
    if trends is not None:
        console.print(trends)
    # 6. QoE
    qoe = _qoe_table(ts)
    if qoe is not None:
        console.print(qoe)
    # 7. Restatements + pattern analysis + narrative link
    restatements = _render_restatements(ts.restatement_events)
    if restatements is not None:
        console.print(restatements)
    else:
        console.print(
            "[dim]No restatement events detected (all compared values "
            "within per-metric materiality thresholds).[/dim]"
        )
    for line in _restatement_pattern_section(ts):
        console.print(line)
    for line in _restatement_narrative_section(ts):
        console.print(line)
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
        export.write_text(
            render_analytical_markdown(
                ts, auto_wacc=auto_wacc, dcf_result=dcf_result
            ),
            encoding="utf-8",
        )
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
