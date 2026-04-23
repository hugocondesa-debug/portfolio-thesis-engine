"""Phase 2 Sprint 4A-alpha.4 regression tests — reverse DCF solver.

Solver (6):
- ``test_reverse_solver_finds_operating_margin_that_reproduces_fv``
- ``test_reverse_solver_finds_wacc``
- ``test_reverse_solver_finds_capex_intensity``
- ``test_reverse_solver_reports_no_convergence_when_target_unreachable``
- ``test_implied_value_gap_computation_matches_implied_minus_baseline``
- ``test_solve_all_returns_one_result_per_driver``

Plausibility (3):
- ``test_plausibility_operating_margin_within_historical_high``
- ``test_plausibility_operating_margin_below_half_floor_very_low``
- ``test_plausibility_wacc_risk_premium_bands``

CLI + integration (4):
- ``test_pte_reverse_cli_single_driver``
- ``test_pte_reverse_cli_enumerate``
- ``test_pte_reverse_cli_markdown_export``
- ``test_pte_analyze_embeds_market_implied_section``

Total: 13 tests.
"""

from __future__ import annotations

import io
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from portfolio_thesis_engine.cli import analyze_cmd, reverse_cmd
from portfolio_thesis_engine.dcf.engine import ValuationEngine
from portfolio_thesis_engine.dcf.orchestrator import DCFOrchestrator
from portfolio_thesis_engine.dcf.p1_engine import PeriodInputs
from portfolio_thesis_engine.dcf.profiles import load_valuation_profile
from portfolio_thesis_engine.dcf.reverse import (
    ImpliedValue,
    ReverseDCFSolver,
    assess_plausibility,
)
from portfolio_thesis_engine.dcf.scenarios import load_scenarios
from portfolio_thesis_engine.dcf.schemas import (
    DCFMethodologyConfig,
    DCFProfile,
    DCFStructure,
    ProfileSelection,
    Scenario,
    ScenarioSet,
    TerminalMethod,
    TerminalValueConfig,
    ValuationProfile,
    WACCEvolution,
)


# ======================================================================
# Fixtures
# ======================================================================
def _base_drivers() -> dict:
    return {
        "revenue": {
            "base_year_value": Decimal("1000"),
            "growth_pattern": [Decimal("0.05")] * 5,
            "terminal_growth": Decimal("0.025"),
        },
        "operating_margin": {
            "current": Decimal("0.20"),
            "target_terminal": Decimal("0.20"),
        },
        "tax_rate": {"statutory": Decimal("0.20")},
        "capex_intensity": {
            "current": Decimal("0.06"),
            "target": Decimal("0.06"),
        },
        "working_capital_intensity": {
            "current": Decimal("0"),
            "target": Decimal("0"),
        },
        "depreciation_rate": {"current": Decimal("0.08")},
    }


def _vp() -> ValuationProfile:
    return ValuationProfile(
        target_ticker="T",
        profile=ProfileSelection(
            code=DCFProfile.P1_INDUSTRIAL_SERVICES,
            source="USER_OVERRIDE",
            confidence="HIGH",
        ),
        dcf_structure=DCFStructure(type="THREE_STAGE", explicit_years=5, fade_years=5),
        wacc_evolution=WACCEvolution(
            stage_3_mature_beta=Decimal("0.7"),
            stage_3_target_leverage=Decimal("0"),
        ),
        terminal_value=TerminalValueConfig(
            cross_check_industry_median=Decimal("10"),
        ),
    )


def _pi(market: Decimal = Decimal("5")) -> PeriodInputs:
    return PeriodInputs(
        ticker="T",
        stage_1_wacc=Decimal("0.08"),
        stage_3_wacc=Decimal("0.07"),
        shares_outstanding=Decimal("100"),
        market_price=market,
        industry_median_ev_ebitda=Decimal("10"),
    )


def _scenario() -> Scenario:
    return Scenario(
        name="base",
        probability=Decimal("1"),
        rationale="",
        methodology=DCFMethodologyConfig(
            type="DCF_3_STAGE",
            terminal_method=TerminalMethod.GORDON_GROWTH,
            terminal_growth=Decimal("0.025"),
        ),
    )


def _forward_fv() -> Decimal:
    """Run the forward engine once on the fixture setup so tests can
    compare reverse-solved FV against the un-modified baseline."""
    result = ValuationEngine().run(
        valuation_profile=_vp(),
        scenario_set=ScenarioSet(
            target_ticker="T",
            valuation_profile=DCFProfile.P1_INDUSTRIAL_SERVICES,
            base_year="FY2024",
            base_drivers=_base_drivers(),
            scenarios=[_scenario()],
        ),
        period_inputs=_pi(),
    )
    return result.scenarios_run[0].fair_value_per_share


# ======================================================================
# Solver
# ======================================================================
class TestSolver:
    def test_reverse_solver_finds_operating_margin_that_reproduces_fv(
        self,
    ) -> None:
        baseline_fv = _forward_fv()
        # Pick a target below baseline → solver should find a lower
        # margin that produces that FV.
        target = baseline_fv * Decimal("0.5")
        implied = ReverseDCFSolver().solve(
            scenario=_scenario(),
            valuation_profile=_vp(),
            period_inputs=_pi(market=target),
            base_drivers=_base_drivers(),
            peer_comparison=None,
            solve_for="operating_margin",
            target_fv=target,
        )
        assert implied.convergence == "CONVERGED"
        assert implied.implied_value is not None
        assert implied.implied_value < implied.baseline_value

    def test_reverse_solver_finds_wacc(self) -> None:
        target = _forward_fv() * Decimal("0.6")
        implied = ReverseDCFSolver().solve(
            scenario=_scenario(),
            valuation_profile=_vp(),
            period_inputs=_pi(market=target),
            base_drivers=_base_drivers(),
            peer_comparison=None,
            solve_for="wacc",
            target_fv=target,
        )
        assert implied.convergence == "CONVERGED"
        # Lower target FV → higher required WACC.
        assert implied.implied_value is not None
        assert implied.implied_value > implied.baseline_value

    def test_reverse_solver_finds_capex_intensity(self) -> None:
        target = _forward_fv() * Decimal("0.8")
        implied = ReverseDCFSolver().solve(
            scenario=_scenario(),
            valuation_profile=_vp(),
            period_inputs=_pi(market=target),
            base_drivers=_base_drivers(),
            peer_comparison=None,
            solve_for="capex_intensity",
            target_fv=target,
        )
        assert implied.convergence == "CONVERGED"
        assert implied.implied_value is not None

    def test_reverse_solver_reports_no_convergence_when_target_unreachable(
        self,
    ) -> None:
        # Target 100x baseline → operating_margin bracket can't reach it.
        target = _forward_fv() * Decimal("100")
        implied = ReverseDCFSolver().solve(
            scenario=_scenario(),
            valuation_profile=_vp(),
            period_inputs=_pi(market=target),
            base_drivers=_base_drivers(),
            peer_comparison=None,
            solve_for="operating_margin",
            target_fv=target,
        )
        assert implied.convergence == "NO_ROOT_IN_BRACKET"
        assert implied.implied_value is None

    def test_implied_value_gap_computation_matches_implied_minus_baseline(
        self,
    ) -> None:
        target = _forward_fv() * Decimal("0.5")
        implied = ReverseDCFSolver().solve(
            scenario=_scenario(),
            valuation_profile=_vp(),
            period_inputs=_pi(market=target),
            base_drivers=_base_drivers(),
            peer_comparison=None,
            solve_for="operating_margin",
            target_fv=target,
        )
        assert implied.gap_vs_baseline == implied.implied_value - implied.baseline_value

    def test_solve_all_returns_one_result_per_driver(self) -> None:
        target = _forward_fv() * Decimal("0.6")
        solver = ReverseDCFSolver()
        results = solver.solve_all(
            scenario=_scenario(),
            valuation_profile=_vp(),
            period_inputs=_pi(market=target),
            base_drivers=_base_drivers(),
            peer_comparison=None,
            target_fv=target,
        )
        assert len(results) == len(solver.SUPPORTED_DRIVERS)
        assert {r.solve_for for r in results} == set(solver.SUPPORTED_DRIVERS)


# ======================================================================
# Plausibility
# ======================================================================
class TestPlausibility:
    def _record(self, op_margin_pct: Decimal, audit: str = "audited"):
        from types import SimpleNamespace

        # Historical op margin is stored as percentage per Phase 2.
        audit_status = SimpleNamespace(value=audit)
        return SimpleNamespace(
            operating_margin_reported=op_margin_pct,
            audit_status=audit_status,
            capex_revenue_ratio=None,
        )

    def test_plausibility_operating_margin_within_historical_high(self) -> None:
        historicals = [
            self._record(Decimal("18")),
            self._record(Decimal("20")),
            self._record(Decimal("22")),
        ]
        # Implied 0.19 (=19 %) is within [0.18, 0.22] range → HIGH.
        implied = ImpliedValue(
            solve_for="operating_margin",
            display_name="Operating margin (terminal)",
            implied_value=Decimal("0.19"),
            baseline_value=Decimal("0.20"),
            gap_vs_baseline=Decimal("-0.01"),
            target_fv=Decimal("5"),
        )
        plaus = assess_plausibility(implied, historicals=historicals)
        assert plaus.plausibility == "HIGH"

    def test_plausibility_operating_margin_below_half_floor_very_low(
        self,
    ) -> None:
        historicals = [
            self._record(Decimal("18")),
            self._record(Decimal("20")),
        ]
        # Implied 0.05 (=5 %) < 0.5 × 0.18 floor → VERY_LOW.
        implied = ImpliedValue(
            solve_for="operating_margin",
            display_name="Operating margin",
            implied_value=Decimal("0.05"),
            baseline_value=Decimal("0.20"),
            gap_vs_baseline=Decimal("-0.15"),
            target_fv=Decimal("2"),
        )
        plaus = assess_plausibility(implied, historicals=historicals)
        assert plaus.plausibility == "VERY_LOW"

    def test_plausibility_wacc_risk_premium_bands(self) -> None:
        # +150 bps → HIGH; +300 bps → MODERATE; +500 bps → LOW; +800 bps → VERY_LOW
        auto = Decimal("0.08")
        cases = [
            (Decimal("0.095"), "HIGH"),
            (Decimal("0.110"), "MODERATE"),
            (Decimal("0.130"), "LOW"),
            (Decimal("0.165"), "VERY_LOW"),
        ]
        for implied_val, expected in cases:
            implied = ImpliedValue(
                solve_for="wacc",
                display_name="WACC (stage 1)",
                implied_value=implied_val,
                baseline_value=auto,
                gap_vs_baseline=implied_val - auto,
                target_fv=Decimal("5"),
            )
            plaus = assess_plausibility(implied, historicals=[], auto_wacc=auto)
            assert plaus.plausibility == expected, (
                f"WACC {implied_val} expected {expected}, got "
                f"{plaus.plausibility}"
            )


# ======================================================================
# CLI + integration
# ======================================================================
class TestCLI:
    def test_pte_reverse_cli_single_driver(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buf = io.StringIO()
        monkeypatch.setattr(
            reverse_cmd, "console", Console(file=buf, width=240, record=True)
        )
        reverse_cmd._run_reverse(
            "1846.HK",
            solve_for="operating_margin",
            enumerate_all=False,
            scenario_name="base",
            target_price=None,
            export=None,
        )
        rendered = buf.getvalue()
        assert "Reverse DCF" in rendered
        assert "Operating margin" in rendered

    def test_pte_reverse_cli_enumerate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        buf = io.StringIO()
        monkeypatch.setattr(
            reverse_cmd, "console", Console(file=buf, width=240, record=True)
        )
        reverse_cmd._run_reverse(
            "1846.HK",
            solve_for=None,
            enumerate_all=True,
            scenario_name="base",
            target_price=None,
            export=None,
        )
        rendered = buf.getvalue()
        # Table renders header row + all five supported drivers.
        assert "implied values" in rendered.lower()
        for driver_display in (
            "Operating margin",
            "Terminal growth",
            "WACC",
            "Revenue growth",
            "Capex intensity",
        ):
            assert driver_display in rendered

    def test_pte_reverse_cli_markdown_export(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        buf = io.StringIO()
        monkeypatch.setattr(
            reverse_cmd, "console", Console(file=buf, width=240)
        )
        out = tmp_path / "reverse.md"
        reverse_cmd._run_reverse(
            "1846.HK",
            solve_for=None,
            enumerate_all=True,
            scenario_name="base",
            target_price=None,
            export=out,
        )
        md = out.read_text()
        assert "# 1846.HK — Reverse DCF Analysis" in md
        assert "## Single-driver implied values" in md
        assert "## Evidence + rationale" in md
        assert "## Conclusion" in md

    def test_pte_analyze_embeds_market_implied_section(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from portfolio_thesis_engine.analytical.historicals import (
            HistoricalNormalizer,
        )

        buf = io.StringIO()
        monkeypatch.setattr(
            analyze_cmd, "console", Console(file=buf, width=240, record=True)
        )
        analyze_cmd._run_analyze(
            "1846.HK", export=None, normalizer=HistoricalNormalizer()
        )
        rendered = buf.getvalue()
        assert "Market-implied assumptions" in rendered
