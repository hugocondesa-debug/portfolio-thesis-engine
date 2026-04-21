"""``pte process`` — run the end-to-end Phase 1.5 pipeline for one ticker.

Chain: ingestion check → WACC load → raw_extraction load → validate
extraction → cross-check → extraction engine → persist → guardrails
→ valuate → persist valuation → compose ficha.

Usage::

    pte process 1846.HK \\
      [--wacc-path /path/to/wacc_inputs.md] \\
      [--extraction-path /path/to/raw_extraction.yaml] \\
      [--force] \\
      [--skip-cross-check] \\
      [--force-cost-override]

Exit codes:

- **0** — pipeline finished with overall guardrail status PASS/WARN/SKIP.
- **1** — cross-check BLOCKED the pipeline (use ``--skip-cross-check``
  to bypass) or extraction strict validation FAILed.
- **2** — guardrails FAIL or any other :class:`PipelineError`.
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
    ExtractionValidationBlocked,
    PipelineError,
)
from portfolio_thesis_engine.schemas.common import GuardrailStatus, Profile
from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.storage.base import normalise_ticker
from portfolio_thesis_engine.storage.filesystem_repo import DocumentRepository
from portfolio_thesis_engine.storage.sqlite_repo import MetadataRepository
from portfolio_thesis_engine.storage.yaml_repo import CompanyStateRepository

console = Console()

_STATUS_STYLE = {
    "ok": "[green]ok[/green]",
    "skip": "[yellow]skip[/yellow]",
    "fail": "[red]fail[/red]",
}


# ----------------------------------------------------------------------
# Path resolution
# ----------------------------------------------------------------------
def _resolve_wacc_path(ticker: str, explicit: str | None) -> Path:
    """Find ``wacc_inputs.md`` — explicit path, ingested copy, or
    ``~/data_inputs/{ticker}/wacc_inputs.md`` fallback."""
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            raise typer.BadParameter(f"--wacc-path points to non-existent file: {p}")
        return p
    # 1. ingested copy
    repo = DocumentRepository()
    for candidate in repo.list_documents(ticker):
        if candidate.name == "wacc_inputs.md":
            return candidate
    # 2. default data_inputs layout
    default = Path.home() / "data_inputs" / normalise_ticker(ticker) / "wacc_inputs.md"
    if default.exists():
        return default
    raise typer.BadParameter(
        f"No wacc_inputs.md found for {ticker}. Ingest it first or pass --wacc-path "
        f"(checked: DocumentRepository, {default})."
    )


def _resolve_extraction_path(ticker: str, explicit: str | None) -> Path:
    """Find ``raw_extraction.yaml`` — explicit path, ingested copy, or
    ``~/data_inputs/{ticker}/raw_extraction.yaml`` fallback."""
    if explicit:
        p = Path(explicit).expanduser()
        if not p.exists():
            raise typer.BadParameter(
                f"--extraction-path points to non-existent file: {p}"
            )
        return p
    repo = DocumentRepository()
    for candidate in repo.list_documents(ticker):
        if candidate.name == "raw_extraction.yaml":
            return candidate
    default = (
        Path.home() / "data_inputs" / normalise_ticker(ticker) / "raw_extraction.yaml"
    )
    if default.exists():
        return default
    raise typer.BadParameter(
        f"No raw_extraction.yaml found for {ticker}. Ingest it first or pass "
        f"--extraction-path (checked: DocumentRepository, {default})."
    )


# ----------------------------------------------------------------------
# Build coordinator
# ----------------------------------------------------------------------
def _build_coordinator(ticker: str) -> PipelineCoordinator:
    """Wire the real service graph for production runs."""
    cost_tracker = CostTracker()
    llm_provider = AnthropicProvider()
    extraction_coordinator = ExtractionCoordinator(
        profile=Profile.P1_INDUSTRIAL,
        llm=llm_provider,
        cost_tracker=cost_tracker,
    )
    cross_check_gate = CrossCheckGate(FMPProvider(), YFinanceProvider())
    return PipelineCoordinator(
        document_repo=DocumentRepository(),
        metadata_repo=MetadataRepository(),
        cross_check_gate=cross_check_gate,
        extraction_coordinator=extraction_coordinator,
        state_repo=CompanyStateRepository(),
    )


# ----------------------------------------------------------------------
# Rendering
# ----------------------------------------------------------------------
def _render(outcome: PipelineOutcome) -> None:
    table = Table(
        show_header=True,
        header_style="bold magenta",
        title=f"Pipeline — {outcome.ticker}",
    )
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

    # Extraction validation summary (Sprint 2 addition).
    if outcome.extraction_validation_strict is not None:
        strict = outcome.extraction_validation_strict
        warn = outcome.extraction_validation_warn
        comp = outcome.extraction_validation_completeness
        console.print(
            f"\n[bold]Extraction validation:[/bold] "
            f"strict=[{'red' if strict.overall_status == 'FAIL' else 'green'}]"
            f"{strict.overall_status}[/] "
            f"· warn={warn.overall_status if warn else 'N/A'} "
            f"· completeness={comp.overall_status if comp else 'N/A'}"
        )
        if strict.fails:
            for fail in strict.fails:
                console.print(f"  [red]FAIL[/red] {fail.check_id}: {fail.message}")

    if outcome.guardrails is not None:
        gtable = Table(show_header=True, header_style="bold cyan", title="Guardrails")
        gtable.add_column("ID")
        gtable.add_column("Name", overflow="fold")
        gtable.add_column("Status")
        gtable.add_column("Message", overflow="fold")
        for gr in outcome.guardrails.results:
            gtable.add_row(gr.check_id, gr.name, gr.status.value, gr.message)
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


# ----------------------------------------------------------------------
# Command
# ----------------------------------------------------------------------
def process(
    ticker: str = typer.Argument(..., help="Target ticker (e.g. 1846.HK)."),
    wacc_path: str = typer.Option(
        "",
        "--wacc-path",
        help="Path to wacc_inputs.md. Defaults to ingested copy or "
        "~/data_inputs/{ticker}/wacc_inputs.md.",
    ),
    extraction_path: str = typer.Option(
        "",
        "--extraction-path",
        help="Path to raw_extraction.yaml. Defaults to ingested copy or "
        "~/data_inputs/{ticker}/raw_extraction.yaml.",
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
        help="Temporarily raise the per-company cost cap for this run "
        "(emergency only).",
    ),
) -> None:
    """Run the Phase 1.5 pipeline end-to-end for ``ticker``."""
    try:
        wacc_resolved = _resolve_wacc_path(ticker, wacc_path or None)
        extraction_resolved = _resolve_extraction_path(
            ticker, extraction_path or None
        )
    except typer.BadParameter as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=2) from e

    coord = _build_coordinator(ticker)

    async def _run() -> PipelineOutcome:
        return await coord.process(
            ticker,
            wacc_path=wacc_resolved,
            extraction_path=extraction_resolved,
            force=force,
            skip_cross_check=skip_cross_check,
            force_cost_override=force_cost_override,
        )

    try:
        outcome = asyncio.run(_run())
    except CrossCheckBlocked as e:
        console.print(f"[red]Cross-check blocked:[/red] {e}")
        raise typer.Exit(code=1) from e
    except ExtractionValidationBlocked as e:
        console.print(f"[red]Extraction validation blocked:[/red] {e}")
        raise typer.Exit(code=1) from e
    except PipelineError as e:
        console.print(f"[red]Pipeline error:[/red] {e}")
        raise typer.Exit(code=2) from e

    _render(outcome)

    if outcome.overall_guardrail_status == GuardrailStatus.FAIL:
        raise typer.Exit(code=2)


# Keep ``settings`` used so imports don't flag as unused — used in tests
# that monkey-patch ``settings.data_dir``.
_ = settings


# Re-export so callers / tests can see the shape.
__all__ = ["process"]
