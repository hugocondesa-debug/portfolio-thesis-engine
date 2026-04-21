"""Streamlit UI — Phase 1 Ficha viewer.

Run with::

    uv run streamlit run src/portfolio_thesis_engine/ui/app.py

Reads the three YAML repositories (:class:`CompanyRepository`,
:class:`CompanyStateRepository`, :class:`ValuationRepository`) via
:class:`FichaLoader` and renders a read-only dashboard for the
processed ticker.

Sprint 10 ships the main Ficha page only. Phase 2 will add
Positions / Watchlist / Settings — the sidebar has stubs for them,
disabled for now so the navigation contract is visible.
"""

from __future__ import annotations

import streamlit as st

from portfolio_thesis_engine import __version__
from portfolio_thesis_engine.ficha import FichaLoader
from portfolio_thesis_engine.ui.pages import ficha_view

st.set_page_config(
    page_title="Portfolio Thesis Engine",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)


def _loader() -> FichaLoader:
    """Construct a fresh loader per render. The loader itself is
    cheap (just three repo objects with lazy disk access)."""
    return FichaLoader()


# --- Sidebar -----------------------------------------------------------------
with st.sidebar:
    st.header("Portfolio Thesis Engine")
    st.caption(f"v{__version__} · Phase 1")
    st.divider()
    st.markdown("**Navigation**")
    st.radio(
        "Section",
        options=("Ficha", "Positions", "Watchlist", "Settings"),
        index=0,
        label_visibility="collapsed",
        disabled=True,
        key="nav_section",
        help="Positions / Watchlist / Settings wire in Phase 2.",
    )
    st.divider()
    st.caption("Ficha is the only active view in Phase 1.")


# --- Main panel --------------------------------------------------------------
st.title("Portfolio Thesis Engine")

loader = _loader()
tickers = loader.list_tickers()

if not tickers:
    ficha_view.empty_state(
        "No companies processed yet. Run `pte process <ticker>` first "
        "to populate the repositories."
    )
else:
    selected = st.selectbox(
        "Ticker",
        options=tickers,
        index=0,
        key="ticker_select",
    )
    bundle = loader.load(selected)
    ficha_view.render(bundle)


st.divider()
st.caption(
    f"Portfolio Thesis Engine · Semi-automated portfolio management · v{__version__}"
)
