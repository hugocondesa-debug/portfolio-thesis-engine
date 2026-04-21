"""``pte process`` — run the end-to-end Phase 1 pipeline for one ticker.

Chain: ingestion check → WACC load → section extraction → cross-check
gate → extraction engine → persist → guardrails.

Usage::

    pte process 1846.HK \\
      [--wacc-path /path/to/wacc_inputs.md] \\
      [--force] \\
      [--skip-cross-check] \\
      [--force-cost-override]

Exit codes:

- **0** — pipeline finished with overall guardrail status PASS/WARN/SKIP.
- **1** — cross-check BLOCKED the pipeline (use ``--skip-cross-check``
  to bypass, not recommended).
- **2** — guardrails FAIL or any stage raised :class:`PipelineError`.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from portfolio_thesis_engine.cross_check.gate import CrossCheckGate
from portfolio_thesis_engine.extraction.coordinator import ExtractionCoordinator
from portfolio_thesis_engine.llm.anthropic_provider import AnthropicProvider
from portfolio_thesis_engine.llm.cost_tracker import CostTracker
from portfolio_thesis_engine.market_data.fmp_provider import FMPProvider
from portfolio_thesis_engine.market_data.yfinance_provider import YFinanceProvider
from portfolio_thesis_engine.pipeline import PipelineCoordinator, PipelineOutcome
from portfolio_thesis_engine.pipeline.coordinator import (
    CrossCheckBlocked,
    PipelineError,
)
from portfolio_thesis_engine.schemas.common import GuardrailStatus, Profile
from portfolio_thesis_engine.section_extractor.p1_extractor import P1IndustrialExtractor
from portfolio_thesis_engine.storage.filesystem_repo import DocumentRepository
from portfolio_thesis_engine.storage.sqlite_repo import MetadataRepository
from portfolio_thesis_engine.storage.yaml_repo import CompanyStateRepository

console = Console()

_STATUS_STYLE = {
    "ok": "[green]ok[/green]",
    "skip": "[yellow]skip[/yellow]",
    "fail": "[red]fail[/red]",
}


def _resolve_wacc_path(ticker: str, explicit: str | None) -> Path:
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            raise typer.BadParameter(f"--wacc-path points to non-existent file: {p}")
        return p
    # Default layout: documents/{ticker}/wacc_inputs/wacc_inputs.md
    repo = DocumentRepository()
    for candidate in repo.list_documents(ticker):
        if candidate.name == "wacc_inputs.md":
            return candidate
    raise typer.BadParameter(
        f"No wacc_inputs.md found under the document repository for {ticker}. "
        "Either ingest it or pass --wacc-path."
    )


def _build_coordinator(ticker: str) -> PipelineCoordinator:
    cost_tracker = CostTracker()
    llm_provider = AnthropicProvider()
    section_extractor = P1IndustrialExtractor(llm=llm_provider, cost_tracker=cost_tracker)
    extraction_coordinator = ExtractionCoordinator(
        profile=Profile.P1_INDUSTRIAL,
        llm=llm_provider,
        cost_tracker=cost_tracker,
    )
    cross_check_gate = CrossCheckGate(FMPProvider(), YFinanceProvider())
    return PipelineCoordinator(
        document_repo=DocumentRepository(),
        metadata_repo=MetadataRepository(),
        section_extractor=section_extractor,
        cross_check_gate=cross_check_gate,
        extraction_coordinator=extraction_coordinator,
        state_repo=CompanyStateRepository(),
    )


def _render(outcome: PipelineOutcome) -> None:
    table = Table(show_header=True, header_style="bold magenta", title=f"Pipeline — {outcome.ticker}")
    table.add_column("Stage", overflow="fold")
    table.add_column("Status")
    table.add_column("Duration (ms)", justify="right")
    table.add_column("Message", overflow="fold")
    for stage in outcome.stages:
        table.add_row(
            stage.stage.value,
            _STATUS_STYLE.get(stage.status, stage.status),
            str(stage.duration_ms),
            stage.message,
        )
    console.print(table)

    if outcome.guardrails is not None:
        gtable = Table(show_header=True, header_style="bold cyan", title="Guardrails")
        gtable.add_column("ID")
        gtable.add_column("Name", overflow="fold")
        gtable.add_column("Status")
        gtable.add_column("Message", overflow="fold")
        for r in outcome.guardrails.results:
            gtable.add_row(r.check_id, r.name, r.status.value, r.message)
        console.print(gtable)
        console.print(
            f"\n[bold]Overall:[/bold] {outcome.guardrails.overall.value}  —  "
            f"{outcome.guardrails.total} checks"
        )
    if outcome.canonical_state is not None:
        console.print(
            f"[dim]canonical_state id: {outcome.canonical_state.extraction_id}[/dim]"
        )
    if outcome.log_path is not None:
        console.print(f"[dim]run log: {outcome.log_path}[/dim]")


def process(
    ticker: str = typer.Argument(..., help="Target ticker (e.g. 1846.HK)."),
    wacc_path: str = typer.Option(
        "",
        "--wacc-path",
        help="Path to wacc_inputs.md. Defaults to the ingested copy under the document repo.",
    ),
    force: bool = typer.Option(
        False,
        "--force",
        help="Bypass cached-stage checks; always re-run every stage.",
    ),
    skip_cross_check: bool = typer.Option(
        False,
        "--skip-cross-check",
        help="Bypass the cross-check gate (noisy, not recommended).",
    ),
    force_cost_override: bool = typer.Option(
        False,
        "--force-cost-override",
        help="Temporarily raise the per-company cost cap for this run (emergency only).",
    ),
) -> None:
    """Run the Phase 1 pipeline end-to-end for ``ticker``."""
    try:
        wacc_resolved = _resolve_wacc_path(ticker, wacc_path or None)
    except typer.BadParameter as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=2) from e

    coord = _build_coordinator(ticker)

    async def _run() -> PipelineOutcome:
        return await coord.process(
            ticker,
            wacc_path=wacc_resolved,
            force=force,
            skip_cross_check=skip_cross_check,
            force_cost_override=force_cost_override,
        )

    try:
        outcome = asyncio.run(_run())
    except CrossCheckBlocked as e:
        console.print(f"[red]Cross-check blocked:[/red] {e}")
        raise typer.Exit(code=1) from e
    except PipelineError as e:
        console.print(f"[red]Pipeline error:[/red] {e}")
        raise typer.Exit(code=2) from e

    _render(outcome)

    if outcome.overall_guardrail_status == GuardrailStatus.FAIL:
        raise typer.Exit(code=2)


# Re-export so callers / tests can see the shape.
__all__ = ["process"]
