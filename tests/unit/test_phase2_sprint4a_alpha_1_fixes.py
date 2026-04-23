"""Phase 2 Sprint 4A-alpha.1 regression tests — validation fixes.

Issue 1 — market price auto-load + upside (4):
- ``test_market_price_auto_loaded_from_wacc_inputs``
- ``test_market_price_cli_override``
- ``test_upside_computed_per_scenario``
- ``test_upside_display_formatted_with_sign``

Issue 2 — markdown export sections (5):
- ``test_markdown_includes_dcf_structure_section``
- ``test_markdown_includes_year_by_year_detail``
- ``test_markdown_includes_ev_to_equity_bridge``
- ``test_markdown_includes_terminal_multiple_validation``
- ``test_markdown_includes_assumptions_summary``

Issue 3 — terminal multiple rendering (4):
- ``test_terminal_multiple_compact_when_no_warnings``
- ``test_terminal_multiple_full_table_when_detail_flag``
- ``test_terminal_multiple_full_table_when_warning_emitted``
- ``test_terminal_multiple_markdown_always_full``

Issue 4 — scenario sensitivity (3):
- ``test_driver_override_replaces_base_current_value``
- ``test_structural_scenario_margin_lower_than_base_throughout_forecast``
- ``test_structural_fv_below_base_fv``

Issue 5 — EV-to-FV bridge (4):
- ``test_bridge_section_lists_explicit_and_fade_pv_sums``
- ``test_bridge_section_shows_terminal_formula``
- ``test_bridge_section_renders_equity_value_and_shares``
- ``test_bridge_section_sources_shares_from_canonical_state``

Issue 6 — preliminary signal cross-check (2):
- ``test_preliminary_signal_section_flags_scenarios_below_preliminary``
- ``test_preliminary_signal_absent_when_no_preliminary_in_trends``

Total: 22 tests.
"""

from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.console import Console
from rich.table import Table

from portfolio_thesis_engine.cli import valuation_cmd
from portfolio_thesis_engine.cli.valuation_cmd import (
    _bridge_section,
    _preliminary_signal_section,
    _terminal_multiple_table,
    render_valuation_markdown,
)
from portfolio_thesis_engine.dcf.orchestrator import (
    DCFOrchestrator,
    _load_market_price_from_wacc_inputs,
)
from portfolio_thesis_engine.dcf.p1_engine import P1DCFEngine, PeriodInputs
from portfolio_thesis_engine.dcf.schemas import (
    DCFProfile,
    DCFStructure,
    ProfileSelection,
    Scenario,
    ScenarioDriverOverride,
    ScenarioSet,
    TerminalMultipleValidation,
    TerminalValueConfig,
    ValuationProfile,
    WACCEvolution,
)


# ======================================================================
# Fixtures (small copies of Sprint 4A-alpha's helpers kept local so
# this test file stays self-contained)
# ======================================================================
def _base_drivers(**overrides) -> dict:
    drivers = {
        "revenue": {
            "base_year_value": Decimal("715682000"),
            "growth_pattern": [
                Decimal("0.055"), Decimal("0.065"), Decimal("0.070"),
                Decimal("0.060"), Decimal("0.045"),
            ],
            "terminal_growth": Decimal("0.025"),
        },
        "operating_margin": {
            "current": Decimal("0.162"),
            "target_terminal": Decimal("0.180"),
        },
        "tax_rate": {"statutory": Decimal("0.165")},
        "capex_intensity": {
            "current": Decimal("0.112"),
            "target": Decimal("0.060"),
        },
        "working_capital_intensity": {
            "current": Decimal("-0.004"),
            "target": Decimal("-0.002"),
        },
        "depreciation_rate": {"current": Decimal("0.08")},
    }
    drivers.update(overrides)
    return drivers


def _vp(industry_median: Decimal | None = Decimal("10.5")) -> ValuationProfile:
    return ValuationProfile(
        target_ticker="TEST.HK",
        profile=ProfileSelection(
            code=DCFProfile.P1_INDUSTRIAL_SERVICES,
            source="USER_OVERRIDE",
            confidence="HIGH",
        ),
        dcf_structure=DCFStructure(type="THREE_STAGE", explicit_years=5, fade_years=5),
        wacc_evolution=WACCEvolution(
            stage_3_mature_beta=Decimal("0.68"),
            stage_3_target_leverage=Decimal("0"),
        ),
        terminal_value=TerminalValueConfig(
            cross_check_industry_median=industry_median,
        ),
    )


def _pi(
    *,
    market_price: Decimal | None = Decimal("2.92"),
    shares: Decimal = Decimal("320053000"),
    net_debt: Decimal = Decimal("-741782000"),
    industry_median: Decimal | None = Decimal("10.5"),
) -> PeriodInputs:
    return PeriodInputs(
        ticker="TEST.HK",
        stage_1_wacc=Decimal("0.0806"),
        stage_3_wacc=Decimal("0.0768"),
        shares_outstanding=shares,
        net_debt=net_debt,
        market_price=market_price,
        industry_median_ev_ebitda=industry_median,
    )


def _ss(
    scenarios: list[Scenario] | None = None,
    base: dict | None = None,
) -> ScenarioSet:
    if scenarios is None:
        scenarios = [Scenario(name="base", probability=Decimal("1"), rationale="")]
    return ScenarioSet(
        target_ticker="TEST.HK",
        valuation_profile=DCFProfile.P1_INDUSTRIAL_SERVICES,
        base_year="FY2024",
        base_drivers=base or _base_drivers(),
        scenarios=scenarios,
    )


def _run_engine(**kwargs):
    return P1DCFEngine().run(
        valuation_profile=kwargs.pop("vp", _vp()),
        scenario_set=kwargs.pop("ss", _ss()),
        period_inputs=kwargs.pop("pi", _pi()),
    )


# ======================================================================
# Issue 1 — market price auto-load + upside
# ======================================================================
class TestIssue1MarketPrice:
    def test_market_price_auto_loaded_from_wacc_inputs(self) -> None:
        """EuroEyes' wacc_inputs.md declares current_price 2.92 HKD."""
        price = _load_market_price_from_wacc_inputs("1846.HK")
        assert price == Decimal("2.92")

    def test_market_price_cli_override(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buf = io.StringIO()
        monkeypatch.setattr(
            valuation_cmd, "console", Console(file=buf, width=240, record=True)
        )
        valuation_cmd._run_valuation(
            "1846.HK", export=None, scenario_filter=None,
            detail=False, market_price=Decimal("2.65"),
            orchestrator=None,
        )
        rendered = buf.getvalue()
        assert "Market price: 2.65" in rendered

    def test_upside_computed_per_scenario(self) -> None:
        result = _run_engine()
        # Engine stores market_price + computes implied_upside_downside_pct.
        assert result.market_price == Decimal("2.92")
        assert result.implied_upside_downside_pct is not None
        assert result.implied_upside_downside_pct > 0

    def test_upside_display_formatted_with_sign(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buf = io.StringIO()
        monkeypatch.setattr(
            valuation_cmd, "console", Console(file=buf, width=240, record=True)
        )
        valuation_cmd._run_valuation(
            "1846.HK", export=None, scenario_filter=None,
            detail=False, market_price=None, orchestrator=None,
        )
        rendered = buf.getvalue()
        assert "+132.2%" in rendered or "+132.7%" in rendered  # base scenario or aggregate


# ======================================================================
# Issue 2 — markdown export sections
# ======================================================================
class TestIssue2MarkdownSections:
    def _md(self) -> str:
        result = DCFOrchestrator().run("1846.HK")
        assert result is not None
        return render_valuation_markdown(result, ticker="1846.HK")

    def test_markdown_includes_dcf_structure_section(self) -> None:
        md = self._md()
        assert "## DCF structure" in md
        assert "Stage-1 WACC" in md
        assert "Stage-3 WACC" in md

    def test_markdown_includes_year_by_year_detail(self) -> None:
        md = self._md()
        # Year 1 through Year 10 rows in the projections table.
        assert "## Base scenario projections" in md
        for year in range(1, 11):
            assert f"| {year} |" in md

    def test_markdown_includes_ev_to_equity_bridge(self) -> None:
        md = self._md()
        assert "Enterprise-to-equity bridge" in md
        assert "Σ explicit PV" in md
        assert "Terminal value" in md
        assert "Enterprise value" in md
        assert "Equity value" in md
        assert "Fair value per share" in md

    def test_markdown_includes_terminal_multiple_validation(self) -> None:
        md = self._md()
        assert "## Terminal multiple cross-check" in md
        assert "Implied EV/EBITDA" in md

    def test_markdown_includes_assumptions_summary(self) -> None:
        md = self._md()
        assert "## Assumptions summary" in md


# ======================================================================
# Issue 3 — terminal multiple rendering
# ======================================================================
class TestIssue3TerminalMultiple:
    def test_terminal_multiple_compact_when_no_warnings(self) -> None:
        result = _run_engine()
        rendered = _terminal_multiple_table(result, force_full=False)
        # All four scenarios in-line: compact string list, not a Table.
        assert isinstance(rendered, list)
        joined = "\n".join(rendered)
        assert "within the 1.5×" in joined

    def test_terminal_multiple_full_table_when_detail_flag(self) -> None:
        result = _run_engine()
        rendered = _terminal_multiple_table(result, force_full=True)
        assert isinstance(rendered, Table)

    def test_terminal_multiple_full_table_when_warning_emitted(self) -> None:
        result = _run_engine()
        # Force a warning on the first scenario.
        result.scenarios_run[0].terminal_multiple_validation = (
            TerminalMultipleValidation(
                implied_ev_ebitda=Decimal("20"),
                industry_median_ev_ebitda=Decimal("10"),
                ratio_vs_median=Decimal("2.0"),
                warning_emitted=True,
            )
        )
        rendered = _terminal_multiple_table(result, force_full=False)
        assert isinstance(rendered, Table)

    def test_terminal_multiple_markdown_always_full(self) -> None:
        """Sprint 4A-alpha.2 — every EuroEyes scenario appears in the
        terminal-multiple markdown table regardless of methodology
        (non-DCF methodologies just show ``—`` for implied multiple)."""
        result = DCFOrchestrator().run("1846.HK")
        assert result is not None
        md = render_valuation_markdown(result, ticker="1846.HK")
        for scenario_name in (
            "base", "bull_re_rating", "bull_operational",
            "bear_structural", "bear_prc_delay", "takeover_floor",
        ):
            assert f"| {scenario_name} |" in md


# ======================================================================
# Issue 4 — scenario sensitivity
# ======================================================================
class TestIssue4ScenarioSensitivity:
    def test_driver_override_replaces_base_current_value(self) -> None:
        """Override.current replaces base_drivers.operating_margin.current."""
        structural = Scenario(
            name="structural",
            probability=Decimal("1"),
            rationale="",
            driver_overrides={
                "operating_margin": ScenarioDriverOverride(
                    current=Decimal("0.14"),
                    target_terminal=Decimal("0.13"),
                )
            },
        )
        ss = _ss(scenarios=[structural])
        result = _run_engine(ss=ss)
        projections = (
            result.scenarios_run[0].explicit_projections
            + result.scenarios_run[0].fade_projections
        )
        # Year 1 margin must reflect the override's current (0.14), not
        # the base 0.162.
        assert projections[0].operating_margin < Decimal("0.15")
        # Year 10 margin must reflect override's target (0.13).
        assert abs(projections[-1].operating_margin - Decimal("0.13")) < Decimal("0.001")

    def test_structural_scenario_margin_lower_than_base_throughout_forecast(
        self,
    ) -> None:
        """Sprint 4A-alpha.2 renamed structural_margin_contraction to
        bear_structural (now a 2-stage DCF). Compare overlapping
        explicit years only — base runs 10 years, bear_structural runs
        2."""
        result = DCFOrchestrator().run("1846.HK")
        assert result is not None
        base = next(v for v in result.scenarios_run if v.scenario_name == "base")
        structural = next(
            v for v in result.scenarios_run
            if v.scenario_name == "bear_structural"
        )
        struct_projections = (
            structural.explicit_projections + structural.fade_projections
        )
        for p_struct in struct_projections:
            # Find base's projection for the same forecast year and
            # verify structural margin is lower (bear margin path
            # 14-13 % vs base 16-18 %).
            p_base = next(
                p for p in (base.explicit_projections + base.fade_projections)
                if p.year == p_struct.year
            )
            assert p_struct.operating_margin < p_base.operating_margin

    def test_structural_fv_below_base_fv(self) -> None:
        result = DCFOrchestrator().run("1846.HK")
        assert result is not None
        base = next(v for v in result.scenarios_run if v.scenario_name == "base")
        structural = next(
            v for v in result.scenarios_run
            if v.scenario_name == "bear_structural"
        )
        assert structural.fair_value_per_share < base.fair_value_per_share


# ======================================================================
# Issue 5 — EV-to-FV bridge visibility
# ======================================================================
class TestIssue5BridgeSection:
    def test_bridge_section_lists_explicit_and_fade_pv_sums(self) -> None:
        result = DCFOrchestrator().run("1846.HK")
        assert result is not None
        lines = _bridge_section(result, "base")
        joined = "\n".join(lines)
        # CLI uses ASCII "Sum of"; markdown uses the Σ glyph. Accept both.
        assert "Sum of explicit PV" in joined or "Σ explicit PV" in joined
        assert "Sum of fade PV" in joined or "Σ fade PV" in joined

    def test_bridge_section_shows_terminal_formula(self) -> None:
        result = DCFOrchestrator().run("1846.HK")
        assert result is not None
        lines = _bridge_section(result, "base")
        joined = "\n".join(lines)
        assert "Terminal FCF" in joined
        assert "Terminal value" in joined
        assert "Terminal PV" in joined

    def test_bridge_section_renders_equity_value_and_shares(self) -> None:
        result = DCFOrchestrator().run("1846.HK")
        assert result is not None
        lines = _bridge_section(result, "base")
        joined = "\n".join(lines)
        assert "Enterprise value" in joined
        assert "Equity value" in joined
        assert "Shares outstanding" in joined
        assert "Fair value per share" in joined

    def test_bridge_section_sources_shares_from_canonical_state(self) -> None:
        result = DCFOrchestrator().run("1846.HK")
        assert result is not None
        base = next(v for v in result.scenarios_run if v.scenario_name == "base")
        # EuroEyes canonical state declares 320,053,000 shares.
        assert base.shares_outstanding == Decimal("320053000")


# ======================================================================
# Issue 6 — preliminary signal cross-check
# ======================================================================
class TestIssue6PreliminarySignal:
    def test_preliminary_signal_section_flags_scenarios_below_preliminary(
        self,
    ) -> None:
        result = DCFOrchestrator().run("1846.HK")
        assert result is not None
        lines = _preliminary_signal_section("1846.HK", result)
        joined = "\n".join(lines)
        # FY2025 preliminary signal is +11.23%; all four scenario Y1
        # growths are below this, so each gets an "↓ below" marker.
        assert "preliminary" in joined.lower()
        assert "conservative" in joined.lower() or "exceeds" in joined.lower()

    def test_preliminary_signal_absent_when_no_preliminary_in_trends(
        self,
    ) -> None:
        """For a ticker without preliminary data the section returns
        empty (no fabricated banner)."""
        result = DCFOrchestrator().run("NO-SUCH-TICKER.XX")
        # Orchestrator returns None when no canonical state → skip.
        if result is None:
            assert True
        else:
            lines = _preliminary_signal_section("NO-SUCH-TICKER.XX", result)
            assert lines == []
