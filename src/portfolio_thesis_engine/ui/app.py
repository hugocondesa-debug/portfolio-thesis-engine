"""Streamlit UI — Phase 0 placeholder.

Run with::

    uv run streamlit run src/portfolio_thesis_engine/ui/app.py

Phase 1 will implement the actual dashboards; this script exists so the
systemd unit has something to serve and so Tailscale / browser access
can be smoke-tested end-to-end.
"""

from __future__ import annotations

import streamlit as st

from portfolio_thesis_engine import __version__

st.set_page_config(
    page_title="Portfolio Thesis Engine",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="expanded",
)

# --- Sidebar -----------------------------------------------------------------
with st.sidebar:
    st.header("Portfolio Thesis Engine")
    st.caption(f"v{__version__} · Phase 0")
    st.divider()
    st.markdown("**Navigation**")
    # Section stubs — disabled in Phase 0, wired in Phase 1.
    st.radio(
        "Section",
        options=("Dashboard", "Positions", "Watchlist", "Settings"),
        index=0,
        label_visibility="collapsed",
        disabled=True,
        key="nav_section",
    )
    st.divider()
    st.caption("Phase 1 will enable navigation.")

# --- Main panel --------------------------------------------------------------
st.title("Portfolio Thesis Engine")
st.info(
    "**Phase 1 — UI coming soon.** "
    "This is a placeholder serving the Streamlit process for systemd / Tailscale "
    "smoke-testing. All CLI functionality is available via `pte` (setup, "
    "health-check, smoke-test)."
)

cols = st.columns(3)
with cols[0]:
    st.metric("Version", __version__)
with cols[1]:
    st.metric("Phase", "0")
with cols[2]:
    st.metric("Status", "Scaffolding complete")

st.divider()
st.caption(
    "Portfolio Thesis Engine · Semi-automated portfolio management · "
    f"v{__version__}"
)
