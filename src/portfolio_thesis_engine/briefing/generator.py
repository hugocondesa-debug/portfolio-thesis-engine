"""Phase 2 Sprint 4A-alpha.5 Part C — analytical briefing generator.

Orchestrates every analytical output the system produces (Sprint 1
historicals, Sprint 2A/2B analytics, Sprint 3 peers + cost of capital,
Sprint 4A-alpha DCF + reverse DCF, plus the Sprint 4A-alpha.5
cost-structure + leading-indicators analyses) into a single markdown
document for Claude.ai Project consumption.

Four purpose-specific emphases:

- ``capital_allocation``: BS evolution + cash flows + narrative, skips
  heavy valuation scenarios.
- ``scenarios_generate``: operational drivers + cost structure + peer
  positioning + leading indicators (no current scenarios).
- ``scenarios_revise``: full + current scenarios + reverse DCF.
- ``full``: every section.

Graceful degradation: any section whose upstream data is absent is
replaced by a one-line placeholder so the briefing always produces a
coherent document.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Literal

from portfolio_thesis_engine.briefing.cost_structure import (
    CostStructureAnalysis,
)
from portfolio_thesis_engine.briefing.leading_indicators import (
    LeadingIndicatorsSet,
)


BriefingPurpose = Literal[
    "capital_allocation",
    "scenarios_generate",
    "scenarios_revise",
    "full",
]


@dataclass
class BriefingInputs:
    """Holder for every optional data source the generator consumes.
    Keeps the :class:`AnalyticalBriefingGenerator` constructor signature
    manageable."""

    ticker: str
    time_series: Any | None = None  # CompanyTimeSeries from Sprint 2
    cost_structure: CostStructureAnalysis | None = None
    leading_indicators: LeadingIndicatorsSet | None = None
    peer_comparison: Any | None = None  # PeerComparison from Sprint 3
    wacc_auto: Any | None = None  # WACCComputation from Sprint 3
    valuation_result: Any | None = None  # DCFValuationResult from Sprint 4A-alpha
    reverse_report: Any | None = None  # ReverseDCFReport from Sprint 4A-alpha.4
    sector_suggestions: list[str] | None = None


class AnalyticalBriefingGenerator:
    def __init__(self, inputs: BriefingInputs) -> None:
        self.inputs = inputs

    # ------------------------------------------------------------------
    def generate(self, purpose: BriefingPurpose = "full") -> str:
        sections: list[str] = []
        sections.append(self._header(purpose))
        sections.append(self._section_1_historical_timeseries())
        sections.append(self._section_2_quality_of_earnings())
        sections.append(self._section_3_normalized_pnl())
        sections.append(self._section_4_economic_bs())
        sections.append(self._section_5_dupont_roic())
        sections.append(self._section_6_cost_structure_and_indicators())
        sections.append(self._section_7_trend_analysis())
        sections.append(self._section_8_narrative_timeline())
        if self.inputs.peer_comparison is not None:
            sections.append(self._section_9_peer_positioning())
        if self.inputs.wacc_auto is not None:
            sections.append(self._section_10_cost_of_capital())
        if (
            purpose in ("scenarios_revise", "full")
            and self.inputs.valuation_result is not None
        ):
            sections.append(self._section_11_valuation_scenarios())
        if (
            purpose != "capital_allocation"
            and self.inputs.leading_indicators is not None
        ):
            sections.append(self._section_12_leading_indicators_detail())
        sections.append(self._footer(purpose))
        return "\n\n".join(section for section in sections if section)

    # ------------------------------------------------------------------
    def _header(self, purpose: BriefingPurpose) -> str:
        return "\n".join([
            f"# {self.inputs.ticker} — Analytical briefing",
            "",
            f"_Generated: {datetime.now(UTC).isoformat(timespec='minutes')}_",
            f"_Purpose: **{purpose}**_",
            "",
            (
                "This document orchestrates the full analytical layer "
                "(Sprint 1-4A-alpha.4) into a single briefing for "
                "Claude.ai Project workflows. Section availability "
                "depends on which data layers have been populated for "
                "the ticker."
            ),
        ])

    # ------------------------------------------------------------------
    # Section 1 — Historical time-series
    # ------------------------------------------------------------------
    def _section_1_historical_timeseries(self) -> str:
        ts = self.inputs.time_series
        if ts is None or not getattr(ts, "records", None):
            return self._missing("1. Historical time-series", "CompanyTimeSeries")
        lines = [
            "## 1. Historical time-series",
            "",
            "| Period | End | Type | Audit | Revenue | Op Income | NOPAT | ROIC | Source |",
            "|---|---|---|---|---:|---:|---:|---:|---|",
        ]
        for r in ts.records:
            lines.append(
                f"| {r.period} | {r.period_end.isoformat()} | "
                f"{r.period_type.value} | {r.audit_status.value} | "
                f"{_fmt_money(r.revenue)} | {_fmt_money(r.operating_income)} | "
                f"{_fmt_money(r.nopat)} | {_fmt_pct_raw(r.roic_primary)} | "
                f"{getattr(r.source_document_type, 'value', str(r.source_document_type))} |"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 2 — Quality of earnings
    # ------------------------------------------------------------------
    def _section_2_quality_of_earnings(self) -> str:
        ts = self.inputs.time_series
        if ts is None:
            return self._missing("2. Quality of earnings", "CompanyTimeSeries")
        rows = [r for r in ts.records if r.quality_of_earnings is not None]
        if not rows:
            return self._missing("2. Quality of earnings", "QoE per-record data")
        lines = [
            "## 2. Quality of earnings",
            "",
            "| Period | Composite | Accruals | CFO/NI | AR/Rev | Non-rec | Audit | Flags |",
            "|---|---:|---:|---:|---:|---:|---:|---|",
        ]
        for r in rows:
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
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 3 — Normalized P&L
    # ------------------------------------------------------------------
    def _section_3_normalized_pnl(self) -> str:
        ts = self.inputs.time_series
        if ts is None:
            return self._missing("3. Normalized P&L", "CompanyTimeSeries")
        lines = [
            "## 3. Normalized P&L (sustainable OI view)",
            "",
            "| Period | Revenue | OI reported | OI sustainable | Non-recurring | Sustainable margin |",
            "|---|---:|---:|---:|---:|---:|",
        ]
        for r in ts.records:
            non_rec = (
                r.operating_income - r.sustainable_operating_income
                if r.operating_income is not None
                and r.sustainable_operating_income is not None
                else None
            )
            margin = r.operating_margin_sustainable
            lines.append(
                f"| {r.period} | {_fmt_money(r.revenue)} | "
                f"{_fmt_money(r.operating_income)} | "
                f"{_fmt_money(r.sustainable_operating_income)} | "
                f"{_fmt_money(non_rec)} | "
                f"{_fmt_pct_raw(margin)} |"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 4 — Economic balance sheet
    # ------------------------------------------------------------------
    def _section_4_economic_bs(self) -> str:
        ts = self.inputs.time_series
        if ts is None:
            return self._missing("4. Economic balance sheet", "CompanyTimeSeries")
        rows = [r for r in ts.records if r.economic_balance_sheet is not None]
        if not rows:
            return self._missing("4. Economic balance sheet", "EconomicBalanceSheet")
        lines = [
            "## 4. Economic balance sheet",
            "",
            "| Period | PPE net | ROU | Goodwill | WC | IC | Cash | Debt | NFP |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
        for r in rows:
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
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 5 — DuPont + ROIC
    # ------------------------------------------------------------------
    def _section_5_dupont_roic(self) -> str:
        ts = self.inputs.time_series
        if ts is None:
            return self._missing("5. DuPont + ROIC", "CompanyTimeSeries")
        dupont_rows = [r for r in ts.records if r.dupont_3way is not None]
        lines = ["## 5. DuPont + ROIC decomposition"]
        if dupont_rows:
            lines.extend([
                "",
                "### DuPont 3-way",
                "",
                "| Period | Net margin | Asset turn | Leverage | ROE computed | ROE reported |",
                "|---|---:|---:|---:|---:|---:|",
            ])
            for r in dupont_rows:
                d = r.dupont_3way
                assert d is not None
                lines.append(
                    f"| {r.period} | {_fmt_pct_raw(d.net_margin)} | "
                    f"{_fmt_ratio(d.asset_turnover)} | "
                    f"{_fmt_ratio(d.financial_leverage)} | "
                    f"{_fmt_pct_raw(d.roe_computed)} | {_fmt_pct_raw(d.roe_reported)} |"
                )
        roic_rows = [r for r in ts.records if r.roic_decomposition is not None]
        if roic_rows:
            lines.extend([
                "",
                "### ROIC decomposition (NOPAT margin × IC turnover)",
                "",
                "| Period | NOPAT margin | IC turnover | ROIC | WACC | Spread | Signal |",
                "|---|---:|---:|---:|---:|---:|---|",
            ])
            for r in roic_rows:
                d = r.roic_decomposition
                assert d is not None
                lines.append(
                    f"| {r.period} | {_fmt_pct_raw(d.nopat_margin)} | "
                    f"{_fmt_ratio(d.ic_turnover)} | "
                    f"{_fmt_pct_raw(d.roic_computed)} | "
                    f"{_fmt_pct_raw(d.wacc)} | "
                    f"{_fmt_bps_raw(d.spread_bps)} | "
                    f"{d.value_signal or '—'} |"
                )
        if not dupont_rows and not roic_rows:
            return self._missing("5. DuPont + ROIC", "DuPont / ROIC decomposition")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 6 — Cost structure + leading indicators headline
    # ------------------------------------------------------------------
    def _section_6_cost_structure_and_indicators(self) -> str:
        cs = self.inputs.cost_structure
        indicators = self.inputs.leading_indicators
        sector_suggestions = self.inputs.sector_suggestions or []
        lines = ["## 6. Cost structure + leading indicators (headline)"]
        if cs is None:
            lines.extend(["", "_Cost-structure analysis not generated for this ticker._"])
        else:
            if cs.cost_lines:
                lines.extend([
                    "",
                    "### 6.1 Cost-line weights (% of revenue)",
                    "",
                    "| Line | Sensitivity | "
                    + " | ".join(cs.periods_analyzed)
                    + " | Trend |",
                    "|---|---|" + "|".join(["---:"] * len(cs.periods_analyzed)) + "|---|",
                ])
                for cl in cs.cost_lines:
                    cells = [
                        _fmt_pct_decimal(cl.weights_by_period.get(p))
                        for p in cs.periods_analyzed
                    ]
                    lines.append(
                        f"| {cl.line_name} | {cl.inflation_sensitivity} | "
                        + " | ".join(cells)
                        + f" | {cl.trend} |"
                    )
            if cs.margin_bridges:
                lines.extend(["", "### 6.2 Margin bridges (period-over-period)", ""])
                for mb in cs.margin_bridges:
                    lines.append(
                        f"- **{mb.from_period} → {mb.to_period}**: "
                        f"{_fmt_pct_decimal(mb.starting_margin)} → "
                        f"{_fmt_pct_decimal(mb.ending_margin)} "
                        f"(Δ {mb.delta_bps:+d} bps)"
                    )
                    if mb.attribution_bps:
                        for line_name, contrib in sorted(
                            mb.attribution_bps.items(),
                            key=lambda x: abs(x[1]),
                            reverse=True,
                        ):
                            lines.append(
                                f"    - {line_name}: {contrib:+d} bps"
                            )
                        lines.append(f"    - residual: {mb.residual_bps:+d} bps")
            if cs.operating_leverage_estimate is not None:
                lines.extend(["", "### 6.3 Operating leverage"])
                lines.append(
                    f"- Variable cost slope (OpEx / ΔRevenue): "
                    f"{cs.operating_leverage_estimate:.3f}"
                )
                lines.append(
                    f"- Fixed cost proxy: {_fmt_money(cs.total_fixed_cost_proxy)}"
                )
            if cs.analysis_notes:
                lines.extend(["", "### 6.4 Notes"])
                for note in cs.analysis_notes:
                    lines.append(f"- {note}")
        # Indicators headline
        lines.extend(["", "### 6.5 Leading indicators — catalogue snapshot"])
        if indicators is None:
            lines.append(
                "_No `leading_indicators.yaml` for this ticker. "
                "Sprint 4A-alpha.5 ships a sector-default catalogue — "
                "suggested additions:_"
            )
            if sector_suggestions:
                for name in sector_suggestions:
                    lines.append(f"  - `{name}`")
            else:
                lines.append(
                    "  _(no sector match in catalogue; populate "
                    "`data/yamls/companies/<ticker>/leading_indicators.yaml` "
                    "manually)_"
                )
        else:
            lines.append(
                f"- {len(indicators.indicators)} indicators declared "
                f"(sector: `{indicators.sector_taxonomy}`)."
            )
            for ind in indicators.indicators:
                env = ind.current_environment
                env_str = (
                    f"{env.trend}/{env.direction}" if env is not None else "—"
                )
                lines.append(
                    f"  - **{ind.name}** ({ind.category}) — "
                    f"relevance {', '.join(ind.relevance) or '—'}; "
                    f"environment {env_str}; confidence {ind.confidence}."
                )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 7 — Trend analysis
    # ------------------------------------------------------------------
    def _section_7_trend_analysis(self) -> str:
        ts = self.inputs.time_series
        if ts is None or ts.trends is None:
            return self._missing("7. Trend analysis", "TrendAnalysis")
        t = ts.trends
        lines = [
            "## 7. Trend analysis",
            "",
            f"- Period: {t.period_start} → {t.period_end}",
            f"- Annuals available: {t.annuals_used_for_cagr}",
            f"- Revenue YoY (audited): {_fmt_pct_raw(t.revenue_yoy_growth)}",
            f"- Revenue YoY (preliminary): {_fmt_pct_raw(t.revenue_yoy_growth_preliminary)}",
            f"- Revenue CAGR 2Y / 3Y / 5Y: {_fmt_pct_raw(t.revenue_cagr_2y)} / "
            f"{_fmt_pct_raw(t.revenue_cagr_3y)} / {_fmt_pct_raw(t.revenue_cagr_5y)}",
            f"- Revenue trajectory (audited): {t.revenue_trajectory}",
            f"- Revenue trajectory (incl. preliminary): {t.revenue_trajectory_incl_preliminary}",
            f"- Operating margin Δ: {_fmt_bps_raw(t.operating_margin_delta_bps)}"
            f" ({t.operating_margin_trajectory})",
            f"- ROIC Δ: {_fmt_bps_raw(t.roic_delta_bps)} ({t.roic_trajectory})",
            f"- ROIC spread trend: {t.roic_spread_trend}",
            f"- CapEx/Revenue: {_fmt_pct_raw(t.capex_revenue_ratio)}",
            f"- WC intensity: {_fmt_pct_raw(t.working_capital_intensity)}",
            f"- CFO/Revenue: {_fmt_pct_raw(t.cfo_revenue_ratio)}",
            f"- Cash conversion cycle: "
            + (
                f"{t.cash_conversion_cycle:.0f} days"
                if t.cash_conversion_cycle is not None
                else "—"
            ),
        ]
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 8 — Narrative timeline
    # ------------------------------------------------------------------
    def _section_8_narrative_timeline(self) -> str:
        ts = self.inputs.time_series
        if ts is None or ts.narrative_timeline is None:
            return self._missing("8. Narrative timeline", "NarrativeTimeline")
        nt = ts.narrative_timeline
        lines = ["## 8. Narrative timeline"]
        for header, attr in (
            ("Themes", "themes_evolution"),
            ("Risks", "risks_evolution"),
            ("Guidance", "guidance_evolution"),
            ("Capital allocation", "capital_allocation_evolution"),
        ):
            occs = getattr(nt, attr, []) or []
            if not occs:
                continue
            lines.extend(["", f"### {header}"])
            for occ in occs:
                text = (
                    getattr(occ, "theme_text", None)
                    or getattr(occ, "risk_text", None)
                    or getattr(occ, "guidance_text", None)
                    or getattr(occ, "capital_allocation_text", None)
                    or ""
                )
                flag = "✓" if getattr(occ, "was_consistent", False) else "—"
                lines.append(
                    f"- [{', '.join(occ.periods_mentioned)}] {flag} {text}"
                )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 9 — Peer positioning
    # ------------------------------------------------------------------
    def _section_9_peer_positioning(self) -> str:
        pc = self.inputs.peer_comparison
        if pc is None:
            return ""
        lines = [
            "## 9. Peer positioning",
            "",
            "| Metric | Target | Peer median | Δ vs median |",
            "|---|---:|---:|---:|",
        ]
        target = pc.target_fundamentals
        for attr, label in (
            ("revenue_growth_3y_cagr", "Revenue growth 3Y"),
            ("operating_margin", "Operating margin"),
            ("roic", "ROIC"),
            ("net_margin", "Net margin"),
            ("ev_to_ebitda", "EV/EBITDA"),
        ):
            t_val = getattr(target, attr, None)
            median = pc.peer_median.get(attr)
            delta = pc.target_vs_median_bps.get(attr)
            lines.append(
                f"| {label} | "
                f"{_fmt_pct_raw(t_val) if attr != 'ev_to_ebitda' else _fmt_ratio(t_val)} | "
                f"{_fmt_pct_raw(median) if attr != 'ev_to_ebitda' else _fmt_ratio(median)} | "
                f"{_fmt_bps_raw(delta)} |"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 10 — Cost of capital
    # ------------------------------------------------------------------
    def _section_10_cost_of_capital(self) -> str:
        wacc = self.inputs.wacc_auto
        if wacc is None:
            return ""
        coe = wacc.cost_of_equity
        cod = wacc.cost_of_debt
        lines = [
            "## 10. Cost of capital (auto-generated, Sprint 3)",
            "",
            f"- Currency regime: {coe.currency_regime}",
            f"- Rf: {_fmt_pct_decimal(coe.risk_free_rate)} ({coe.risk_free_source})",
            f"- Industry β: unlevered {coe.industry_unlevered_beta:.2f} → "
            f"levered {coe.levered_beta:.2f}",
            f"- ERP + weighted CRP: "
            f"{_fmt_pct_decimal(coe.mature_market_erp + coe.weighted_crp)}",
            f"- CoE: {_fmt_pct_decimal(coe.cost_of_equity_final)}",
        ]
        if cod.is_applicable and cod.cost_of_debt_aftertax is not None:
            lines.append(
                f"- CoD (after-tax): "
                f"{_fmt_pct_decimal(cod.cost_of_debt_aftertax)} "
                f"({cod.synthetic_rating})"
            )
        else:
            lines.append(f"- CoD: N/A — {cod.rationale}")
        lines.append(f"- **WACC: {_fmt_pct_decimal(wacc.wacc)}**")
        if wacc.manual_wacc is not None:
            lines.append(
                f"- Manual reference: {_fmt_pct_decimal(wacc.manual_wacc)} "
                f"(Δ {wacc.manual_vs_computed_bps:+d} bps)"
            )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 11 — Valuation scenarios (scenarios_revise + full)
    # ------------------------------------------------------------------
    def _section_11_valuation_scenarios(self) -> str:
        vr = self.inputs.valuation_result
        rr = self.inputs.reverse_report
        if vr is None or not vr.scenarios_run:
            return ""
        lines = [
            "## 11. Valuation scenarios",
            "",
            f"- Stage-1 WACC {_fmt_pct_decimal(vr.stage_1_wacc)} → "
            f"Stage-3 WACC {_fmt_pct_decimal(vr.stage_3_wacc)}",
            (
                f"- Expected value: {_fmt_money(vr.expected_value_per_share)}"
                + (
                    f" ({vr.implied_upside_downside_pct:+.1f}% vs market)"
                    if vr.implied_upside_downside_pct is not None
                    else ""
                )
            ),
            "",
            "| Scenario | Probability | Methodology | FV/share |",
            "|---|---:|---|---:|",
        ]
        for v in vr.scenarios_run:
            lines.append(
                f"| {v.scenario_name} | "
                f"{v.scenario_probability * Decimal('100'):.0f}% | "
                f"{v.methodology_used.value} | "
                f"{_fmt_money(v.fair_value_per_share)} |"
            )
        if rr is not None and rr.implied_values:
            lines.extend([
                "",
                "### Reverse DCF — market-implied assumptions",
                "",
                "| Driver | Baseline | Implied | Gap | Plausibility |",
                "|---|---:|---:|---:|---|",
            ])
            for implied, plaus in zip(rr.implied_values, rr.plausibility, strict=True):
                impl_str = (
                    _fmt_pct_decimal(implied.implied_value)
                    if implied.implied_value is not None
                    else f"— ({implied.convergence})"
                )
                gap_str = (
                    f"{implied.gap_vs_baseline * Decimal('10000'):+.0f} bps"
                    if implied.gap_vs_baseline is not None
                    else "—"
                )
                lines.append(
                    f"| {implied.display_name} | "
                    f"{_fmt_pct_decimal(implied.baseline_value)} | "
                    f"{impl_str} | {gap_str} | {plaus.plausibility} |"
                )
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Section 12 — Leading indicators detail
    # ------------------------------------------------------------------
    def _section_12_leading_indicators_detail(self) -> str:
        indicators = self.inputs.leading_indicators
        if indicators is None or not indicators.indicators:
            return ""
        lines = ["## 12. Leading indicators — detail"]
        for ind in indicators.indicators:
            lines.extend(["", f"### {ind.name}"])
            lines.append(f"- Category: {ind.category}")
            lines.append(f"- Relevance: {', '.join(ind.relevance) or '—'}")
            lines.append(
                f"- Data source: {ind.data_source.type}"
                + (f" (`{ind.data_source.series_id}`)" if ind.data_source.series_id else "")
            )
            if ind.current_value is not None:
                lines.append(f"- Current value: {ind.current_value}")
            sens = ind.sensitivity
            if sens.elasticity:
                lines.append(f"- Elasticity: {sens.elasticity}")
            if sens.absolute_impact_per_percent:
                lines.append(
                    f"- Absolute impact / %: {sens.absolute_impact_per_percent}"
                )
            if sens.interpretation:
                lines.append(f"- Interpretation: {sens.interpretation}")
            env = ind.current_environment
            if env is not None:
                lines.append(
                    f"- Environment: {env.trend} ({env.direction}, "
                    f"volatility {env.recent_volatility})"
                )
            if ind.scenario_relevance:
                lines.append(
                    f"- Scenario relevance: {', '.join(ind.scenario_relevance)}"
                )
            lines.append(f"- Confidence: {ind.confidence}")
        return "\n".join(lines)

    # ------------------------------------------------------------------
    # Footer
    # ------------------------------------------------------------------
    def _footer(self, purpose: BriefingPurpose) -> str:
        instructions = {
            "capital_allocation": (
                "Primary input for generating `capital_allocation.yaml` "
                "(capital allocation priorities + history)."
            ),
            "scenarios_generate": (
                "Primary input for first-time generation of "
                "`scenarios.yaml`. Pair with the scenarios-schema "
                "reference doc before uploading to Claude.ai."
            ),
            "scenarios_revise": (
                "Use as context when revising an existing "
                "`scenarios.yaml`. Reverse DCF section highlights "
                "what the current scenarios miss relative to market."
            ),
            "full": (
                "Comprehensive briefing covering every analytical "
                "layer. Use for broad portfolio reviews."
            ),
        }
        return "\n".join([
            "## Claude.ai workflow",
            "",
            instructions.get(purpose, "") or "",
            "",
            "Generation order for a new ticker:",
            "1. `leading_indicators.yaml` (using the schema reference doc)",
            "2. `capital_allocation.yaml`",
            "3. `scenarios.yaml`",
            "",
            "Upload this briefing together with:",
            "- `raw_extraction*.yaml` for the latest reporting period",
            "- `capital_allocation_schema.md`, `scenarios_schema.md`, "
            "  `leading_indicators_schema_reference.md`",
        ])

    # ------------------------------------------------------------------
    def _missing(self, title: str, dependency: str) -> str:
        return "\n".join([
            f"## {title}",
            "",
            f"_Missing input: {dependency} not available for "
            f"{self.inputs.ticker}._",
        ])


# ----------------------------------------------------------------------
# Formatting helpers
# ----------------------------------------------------------------------
def _fmt_money(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, Decimal):
        return f"{value:,.0f}"
    return str(value)


def _fmt_pct_raw(value: Any) -> str:
    """Format a value that's already a percentage (e.g. 16.18 → 16.18 %)."""
    if value is None:
        return "—"
    return f"{value:.2f}%"


def _fmt_pct_decimal(value: Any) -> str:
    """Format a decimal fraction (e.g. 0.162 → 16.20 %)."""
    if value is None:
        return "—"
    return f"{value * Decimal('100'):.2f}%"


def _fmt_ratio(value: Any) -> str:
    if value is None:
        return "—"
    return f"{value:.2f}×"


def _fmt_bps_raw(value: Any) -> str:
    """Format a value that's already in bps (e.g. 103 → +103 bps)."""
    if value is None:
        return "—"
    return f"{value:+.0f} bps"


__all__ = ["AnalyticalBriefingGenerator", "BriefingInputs", "BriefingPurpose"]
