"""Unit tests for the Streamlit UI stub.

Uses Streamlit's own AppTest harness to render the script without binding
to a network port. A separate subprocess test is intentionally NOT in
this file — it takes 5+ seconds and is run manually on the VPS.
"""

from __future__ import annotations

from streamlit.testing.v1 import AppTest

from portfolio_thesis_engine import __version__

_APP_PATH = "src/portfolio_thesis_engine/ui/app.py"


class TestAppRenders:
    def test_no_exception_on_run(self) -> None:
        at = AppTest.from_file(_APP_PATH)
        at.run()
        # AppTest collects any st.exception() calls; should be empty.
        assert len(at.exception) == 0, [e.value for e in at.exception]

    def test_title_present(self) -> None:
        at = AppTest.from_file(_APP_PATH)
        at.run()
        assert len(at.title) == 1
        assert at.title[0].value == "Portfolio Thesis Engine"

    def test_phase1_placeholder_info(self) -> None:
        at = AppTest.from_file(_APP_PATH)
        at.run()
        assert len(at.info) == 1
        assert "Phase 1" in at.info[0].value

    def test_sidebar_header(self) -> None:
        at = AppTest.from_file(_APP_PATH)
        at.run()
        assert len(at.sidebar.header) == 1
        assert at.sidebar.header[0].value == "Portfolio Thesis Engine"

    def test_nav_radio_is_disabled(self) -> None:
        at = AppTest.from_file(_APP_PATH)
        at.run()
        nav = at.sidebar.radio[0]
        assert nav.disabled is True
        assert list(nav.options) == [
            "Dashboard",
            "Positions",
            "Watchlist",
            "Settings",
        ]

    def test_version_metric_matches_package_version(self) -> None:
        at = AppTest.from_file(_APP_PATH)
        at.run()
        version_metric = next(m for m in at.metric if m.label == "Version")
        assert version_metric.value == __version__
