"""Streamlit Ficha page — read-only view of a processed ticker.

Top-level entry point is :func:`render`: it takes a :class:`FichaBundle`
and fans out to the five section renderers (identity, valuation,
scenarios, financials, guardrails). Each section is defensive: missing
data becomes a gray info note, not an exception.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import streamlit as st

from portfolio_thesis_engine.ficha import FichaBundle
from portfolio_thesis_engine.schemas.company import CanonicalCompanyState
from portfolio_thesis_engine.schemas.ficha import Ficha
from portfolio_thesis_engine.schemas.valuation import Scenario, ValuationSnapshot


# ----------------------------------------------------------------------
# Formatting helpers
# ----------------------------------------------------------------------
def _fmt_money(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, Decimal | int | float):
        return f"{value:,.2f}"
    return str(value)


def _fmt_pct(value: Any) -> str:
    if value is None:
        return "—"
    if isinstance(value, Decimal | int | float):
        return f"{value:.2f}%"
    return str(value)


# ----------------------------------------------------------------------
# Public entry point
# ----------------------------------------------------------------------
def render(bundle: FichaBundle) -> None:
    """Render the full Ficha page for ``bundle``."""
    render_identity(bundle)
    st.divider()
    render_valuation(bundle)
    st.divider()
    render_scenarios(bundle)
    st.divider()
    render_financials(bundle)
    st.divider()
    render_guardrails(bundle)
    st.divider()
    render_footer(bundle)


# ----------------------------------------------------------------------
# Sections
# ----------------------------------------------------------------------
def render_identity(bundle: FichaBundle) -> None:
    st.subheader("Identity")
    ficha = bundle.ficha
    state = bundle.canonical_state
    identity = None
    if ficha is not None:
        identity = ficha.identity
    elif state is not None:
        identity = state.identity
    if identity is None:
        st.info("No identity on record. Run `pte process` first.")
        return

    cols = st.columns(4)
    with cols[0]:
        st.metric("Ticker", identity.ticker)
        st.metric("Profile", identity.profile.value)
    with cols[1]:
        st.metric("Name", identity.name)
        st.metric("Currency", identity.reporting_currency.value)
    with cols[2]:
        st.metric("Exchange", identity.exchange)
        st.metric("Country", identity.country_domicile)
    with cols[3]:
        shares = identity.shares_outstanding
        st.metric(
            "Shares outstanding",
            _fmt_money(shares) if shares is not None else "—",
        )
        st.metric("Fiscal year end month", str(identity.fiscal_year_end_month))


def render_valuation(bundle: FichaBundle) -> None:
    st.subheader("Valuation")
    snap = bundle.valuation_snapshot
    if snap is None:
        st.info("No valuation snapshot yet.")
        return

    cols = st.columns(4)
    with cols[0]:
        st.metric("Market price", _fmt_money(snap.market.price))
    with cols[1]:
        st.metric("E[V] / share", _fmt_money(snap.weighted.expected_value))
    with cols[2]:
        st.metric("Upside vs market", _fmt_pct(snap.weighted.upside_pct))
    with cols[3]:
        st.metric("Asymmetry ratio", f"{snap.weighted.asymmetry_ratio:.2f}")

    st.caption(
        f"Fair value range: {_fmt_money(snap.weighted.fair_value_range_low)} — "
        f"{_fmt_money(snap.weighted.fair_value_range_high)} ({snap.market.currency.value})"
    )
    _render_football_field(snap)


def _render_football_field(snap: ValuationSnapshot) -> None:
    """Simple per-scenario bar chart (horizontal columns)."""
    scenarios = snap.scenarios
    if not scenarios:
        return
    st.caption("Football field — per-scenario targets vs market price")
    cols = st.columns(len(scenarios))
    for col, sc in zip(cols, scenarios, strict=False):
        with col:
            target = sc.targets.get("dcf_fcff_per_share")
            st.metric(
                sc.label.capitalize(),
                _fmt_money(target) if target is not None else "—",
                delta=_fmt_pct(sc.upside_pct),
            )


def render_scenarios(bundle: FichaBundle) -> None:
    st.subheader("Scenarios")
    snap = bundle.valuation_snapshot
    if snap is None or not snap.scenarios:
        st.info("No scenarios to display.")
        return

    tabs = st.tabs([sc.label.capitalize() for sc in snap.scenarios])
    for tab, sc in zip(tabs, snap.scenarios, strict=False):
        with tab:
            _render_scenario_detail(sc)


def _render_scenario_detail(sc: Scenario) -> None:
    st.markdown(f"_{sc.description}_")
    cols = st.columns(4)
    with cols[0]:
        st.metric("Probability", _fmt_pct(sc.probability))
    with cols[1]:
        st.metric("Revenue CAGR", _fmt_pct(sc.drivers.revenue_cagr))
    with cols[2]:
        st.metric("Terminal margin", _fmt_pct(sc.drivers.terminal_margin))
    with cols[3]:
        st.metric("Terminal growth", _fmt_pct(sc.drivers.terminal_growth))

    target = sc.targets.get("dcf_fcff_per_share")
    st.markdown(
        f"**Target / share:** {_fmt_money(target) if target is not None else '—'}  "
        f"· **Upside:** {_fmt_pct(sc.upside_pct)}  "
        f"· **IRR (3y):** {_fmt_pct(sc.irr_3y)}"
    )

    if sc.irr_decomposition:
        st.caption("IRR decomposition")
        dcols = st.columns(len(sc.irr_decomposition))
        for col, (label, val) in zip(dcols, sc.irr_decomposition.items(), strict=False):
            with col:
                st.metric(label.capitalize(), _fmt_pct(val))


def render_financials(bundle: FichaBundle) -> None:
    st.subheader("Financials")
    state = bundle.canonical_state
    if state is None or not state.reclassified_statements:
        st.info("No reclassified statements on record.")
        return
    rs = state.reclassified_statements[0]
    tabs = st.tabs(["Income Statement", "Balance Sheet", "Cash Flow", "Ratios"])
    with tabs[0]:
        _render_lines(rs.income_statement, ["Label", "Value"])
    with tabs[1]:
        _render_lines(rs.balance_sheet, ["Label", "Value", "Category"], include_category=True)
    with tabs[2]:
        _render_lines(rs.cash_flow, ["Label", "Value", "Category"], include_category=True)
    with tabs[3]:
        _render_ratios(state)


def _render_lines(lines: list[Any], columns: list[str], include_category: bool = False) -> None:
    if not lines:
        st.info("No lines recorded.")
        return
    rows: list[dict[str, Any]] = []
    for ln in lines:
        row = {"Label": ln.label, "Value": _fmt_money(ln.value)}
        if include_category and hasattr(ln, "category"):
            row["Category"] = ln.category
        rows.append(row)
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _render_ratios(state: CanonicalCompanyState) -> None:
    ratios_list = state.analysis.ratios_by_period
    if not ratios_list:
        st.info("No ratios computed.")
        return
    ratios = ratios_list[0]
    cols = st.columns(4)
    with cols[0]:
        st.metric("ROIC", _fmt_pct(ratios.roic))
    with cols[1]:
        st.metric("ROE", _fmt_pct(ratios.roe))
    with cols[2]:
        st.metric("Operating margin", _fmt_pct(ratios.operating_margin))
    with cols[3]:
        st.metric("EBITDA margin", _fmt_pct(ratios.ebitda_margin))
    cols2 = st.columns(4)
    with cols2[0]:
        nd_ebitda = ratios.net_debt_ebitda
        st.metric(
            "Net debt / EBITDA",
            f"{nd_ebitda:.2f}" if nd_ebitda is not None else "—",
        )
    with cols2[1]:
        st.metric("CapEx / Revenue", _fmt_pct(ratios.capex_revenue))
    # DSO/DPO/DIO deferred to Phase 2.


def render_guardrails(bundle: FichaBundle) -> None:
    st.subheader("Guardrails")
    state = bundle.canonical_state
    if state is None:
        st.info("No canonical state — guardrails not available.")
        return
    v = state.validation
    cols = st.columns(3)
    with cols[0]:
        st.metric("Confidence rating", v.confidence_rating)
    with cols[1]:
        st.metric("Universal checks", str(len(v.universal_checksums)))
    with cols[2]:
        st.metric("Profile checks", str(len(v.profile_specific_checksums)))
    if v.blocking_issues:
        st.error(f"Blocking issues ({len(v.blocking_issues)}):")
        for issue in v.blocking_issues:
            st.write(f"• {issue}")
    else:
        st.success("No blocking issues.")


def render_footer(bundle: FichaBundle) -> None:
    ficha = bundle.ficha
    state = bundle.canonical_state
    parts: list[str] = []
    if ficha is not None and ficha.snapshot_age_days is not None:
        tone = "⚠️" if ficha.is_stale else "✓"
        parts.append(
            f"{tone} Valuation age: {ficha.snapshot_age_days} days "
            f"({'STALE' if ficha.is_stale else 'fresh'})"
        )
    if state is not None:
        parts.append(f"Extraction id: `{state.extraction_id}`")
        parts.append(f"As of: {state.as_of_date}")
    if parts:
        st.caption("  ·  ".join(parts))


def empty_state(message: str) -> None:
    """Render the zero-tickers empty state."""
    st.info(message)


__all__ = [
    "empty_state",
    "render",
    "render_financials",
    "render_footer",
    "render_guardrails",
    "render_identity",
    "render_scenarios",
    "render_valuation",
]


# Retained for symmetry with Phase 0 stub — not used directly in tests.
_ = Ficha
