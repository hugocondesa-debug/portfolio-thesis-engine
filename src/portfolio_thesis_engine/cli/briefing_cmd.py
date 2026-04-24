"""Phase 2 Sprint 4A-alpha.5 Part D — ``pte briefing <ticker>`` CLI.

Orchestrates every analytical layer already produced by Sprint
1-4A-alpha.4 into a single markdown briefing for Claude.ai Project
consumption. Default output goes to ``/tmp/<ticker>_briefing_<purpose>.md``;
``--export PATH`` overrides, ``--output-stdout`` prints directly.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import typer
from rich.console import Console

from portfolio_thesis_engine.analytical.historicals import (
    HistoricalNormalizer,
)
from portfolio_thesis_engine.briefing import (
    AnalyticalBriefingGenerator,
    CostStructureAnalyzer,
    LeadingIndicatorsLoader,
)
from portfolio_thesis_engine.briefing.generator import BriefingInputs
from portfolio_thesis_engine.dcf.orchestrator import DCFOrchestrator
from portfolio_thesis_engine.dcf.profiles import load_valuation_profile
from portfolio_thesis_engine.dcf.reverse import (
    ReverseDCFReport,
    ReverseDCFSolver,
    assess_plausibility,
)
from portfolio_thesis_engine.dcf.scenarios import load_scenarios
from portfolio_thesis_engine.storage.base import normalise_ticker

console = Console()


def _build_inputs(ticker: str, include_reverse: bool) -> BriefingInputs:
    """Gather every optional analytical layer for ``ticker``."""
    try:
        ts = HistoricalNormalizer().normalize(ticker)
    except Exception:
        ts = None

    # Build cost structure from time-series + per-record canonical state.
    cost_structure = None
    if ts is not None and ts.records:
        states: dict[str, Any] = {}
        try:
            from portfolio_thesis_engine.storage.yaml_repo import (
                CompanyStateRepository,
            )

            repo = CompanyStateRepository()
            for record in ts.records:
                sid = record.source_canonical_state_id
                if sid not in states:
                    state = repo.get_version(ticker, sid)
                    if state is not None:
                        states[sid] = state
        except Exception:
            states = {}
        cost_structure = CostStructureAnalyzer().analyze(
            ticker=ticker,
            records=ts.records,
            states=states,
        )

    # Leading indicators + sector suggestions
    loader = LeadingIndicatorsLoader()
    indicators = loader.load_company(ticker)
    sector = indicators.sector_taxonomy if indicators is not None else ""
    sector_suggestions = loader.suggest_missing(indicators, sector) if sector else []

    # DCF + peer + WACC (best-effort, reuse the orchestrator internals)
    orch = DCFOrchestrator()
    dcf_result = None
    wacc_auto = None
    peer_comparison = None
    try:
        state = orch._latest_canonical_state(ticker)  # noqa: SLF001
        if state is not None:
            vp = load_valuation_profile(ticker)
            sset = load_scenarios(ticker)
            stage_1 = orch._stage_1_wacc(ticker, state)  # noqa: SLF001
            stage_3 = orch._stage_3_wacc(state, vp, stage_1)  # noqa: SLF001
            pi = orch._period_inputs(  # noqa: SLF001
                ticker=ticker, state=state,
                stage_1_wacc=stage_1, stage_3_wacc=stage_3,
                valuation_profile=vp,
            )
            peer_comparison = orch._load_peer_comparison(ticker)  # noqa: SLF001
            if sset is not None:
                from portfolio_thesis_engine.dcf.engine import ValuationEngine

                dcf_result = ValuationEngine().run(
                    valuation_profile=vp,
                    scenario_set=sset,
                    period_inputs=pi,
                    peer_comparison=peer_comparison,
                )
            # WACC computation (re-run to capture the full audit trail)
            from portfolio_thesis_engine.capital import WACCGenerator
            from portfolio_thesis_engine.capital.loaders import (
                build_generator_inputs_from_state,
            )

            wacc_inputs = build_generator_inputs_from_state(ticker, state)
            wacc_auto = WACCGenerator().generate(wacc_inputs)
    except Exception:
        pass

    # Reverse DCF (optional — costly, only when requested)
    reverse_report = None
    if include_reverse and dcf_result is not None and dcf_result.market_price:
        try:
            sset = load_scenarios(ticker)
            if sset is not None:
                base = next(
                    (s for s in sset.scenarios if s.name == "base"),
                    sset.scenarios[0] if sset.scenarios else None,
                )
                if base is not None:
                    solver = ReverseDCFSolver()
                    vp = load_valuation_profile(ticker)
                    state = orch._latest_canonical_state(ticker)  # noqa: SLF001
                    assert state is not None
                    stage_1 = orch._stage_1_wacc(ticker, state)  # noqa: SLF001
                    stage_3 = orch._stage_3_wacc(state, vp, stage_1)  # noqa: SLF001
                    pi = orch._period_inputs(  # noqa: SLF001
                        ticker=ticker, state=state,
                        stage_1_wacc=stage_1, stage_3_wacc=stage_3,
                        valuation_profile=vp,
                    )
                    implieds = solver.solve_all(
                        scenario=base,
                        valuation_profile=vp,
                        period_inputs=pi,
                        base_drivers=sset.base_drivers,
                        peer_comparison=peer_comparison,
                        target_fv=pi.market_price,
                    )
                    hist = ts.records if ts is not None else []
                    plausibilities = [
                        assess_plausibility(i, historicals=hist, auto_wacc=stage_1)
                        for i in implieds
                    ]
                    methodology = (
                        base.methodology.type
                        if hasattr(base.methodology, "type")
                        else "UNKNOWN"
                    )
                    reverse_report = ReverseDCFReport(
                        ticker=ticker,
                        scenario_name=base.name,
                        methodology=methodology,
                        market_price=pi.market_price,
                        forward_fv=(
                            dcf_result.scenarios_run[0].fair_value_per_share
                            if dcf_result.scenarios_run
                            else pi.market_price
                        ),
                        target_fv=pi.market_price,
                        implied_values=implieds,
                        plausibility=plausibilities,
                    )
        except Exception:
            pass

    return BriefingInputs(
        ticker=ticker,
        time_series=ts,
        cost_structure=cost_structure,
        leading_indicators=indicators,
        peer_comparison=peer_comparison,
        wacc_auto=wacc_auto,
        valuation_result=dcf_result,
        reverse_report=reverse_report,
        sector_suggestions=sector_suggestions,
    )


def _run_briefing(
    ticker: str,
    *,
    purpose: str,
    export: Path | None,
    output_stdout: bool,
    include_reverse: bool,
) -> None:
    inputs = _build_inputs(ticker, include_reverse)
    generator = AnalyticalBriefingGenerator(inputs)
    document = generator.generate(purpose=purpose)  # type: ignore[arg-type]

    if output_stdout:
        console.print(document)
        return

    out_path = export or (
        Path("/tmp")
        / f"{normalise_ticker(ticker)}_briefing_{purpose}.md"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(document, encoding="utf-8")
    console.print(
        f"[bold]Briefing generated[/bold]  "
        f"[dim]{len(document.splitlines())} lines, "
        f"{len(document)} characters[/dim]"
    )
    console.print(f"Written to: {out_path}")


def briefing(
    ticker: str = typer.Argument(..., help="Target ticker (e.g. 1846.HK)."),
    purpose: str = typer.Option(
        "full",
        "--purpose",
        help="capital_allocation | scenarios_generate | scenarios_revise | full",
    ),
    export: Path | None = typer.Option(
        None,
        "--export",
        help="Write briefing markdown to PATH (defaults to "
        "/tmp/<ticker>_briefing_<purpose>.md).",
    ),
    output_stdout: bool = typer.Option(
        False, "--output-stdout", help="Print briefing to terminal."
    ),
    include_reverse: bool = typer.Option(
        None,
        "--include-reverse-dcf/--no-reverse-dcf",
        help="Include reverse-DCF section in valuation detail "
        "(default: True for scenarios_revise + full).",
    ),
) -> None:
    """Generate the analytical briefing markdown for ``ticker``."""
    if purpose not in (
        "capital_allocation",
        "scenarios_generate",
        "scenarios_revise",
        "full",
    ):
        raise typer.BadParameter(
            f"Unknown purpose '{purpose}'. Choose from "
            "capital_allocation, scenarios_generate, scenarios_revise, full."
        )
    if include_reverse is None:
        include_reverse = purpose in ("scenarios_revise", "full")
    _run_briefing(
        ticker,
        purpose=purpose,
        export=export,
        output_stdout=output_stdout,
        include_reverse=include_reverse,
    )


__all__ = ["_run_briefing", "briefing"]
