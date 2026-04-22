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
from portfolio_thesis_engine.ficha.composer import FichaComposer
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
from portfolio_thesis_engine.storage.yaml_repo import (
    CompanyRepository,
    CompanyStateRepository,
    ValuationRepository,
)
from portfolio_thesis_engine.valuation.composer import ValuationComposer
from portfolio_thesis_engine.valuation.dcf import FCFFDCFEngine
from portfolio_thesis_engine.valuation.scenarios import ScenarioComposer

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
# Phase 1.5.11 — multi-extraction base-period selection
# ----------------------------------------------------------------------
_BASE_PERIOD_AUTO = "AUTO"
_BASE_PERIOD_LATEST_AUDITED = "LATEST-AUDITED"


def _candidate_extraction_files(ticker: str) -> list[Path]:
    """Return every ``raw_extraction*.yaml`` file we can find for a
    ticker, across the DocumentRepository + the ``~/data_inputs`` layout.
    Sorted by mtime descending so "latest" ordering is easy."""
    import re

    seen: set[Path] = set()
    pattern = re.compile(r"^raw_extraction.*\.yaml$", re.IGNORECASE)
    for path in DocumentRepository().list_documents(ticker):
        if pattern.match(path.name):
            seen.add(path)
    base = Path.home() / "data_inputs" / normalise_ticker(ticker)
    if base.exists():
        for path in base.glob("raw_extraction*.yaml"):
            seen.add(path)
    return sorted(seen, key=lambda p: p.stat().st_mtime, reverse=True)


def _peek_audit_metadata(path: Path) -> tuple[str, str, str]:
    """Cheap YAML peek: return ``(audit_status, document_type, period)``
    without parsing the whole extraction. Falls back to ``"audited"`` /
    ``"unknown"`` / ``""`` when any field is missing."""
    import yaml

    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return "audited", "unknown", ""
    metadata = raw.get("metadata") or {}
    audit = str(metadata.get("audit_status") or "audited").lower()
    doc_type = str(metadata.get("document_type") or "unknown")
    # primary_period label — first entry in fiscal_periods list.
    fps = metadata.get("fiscal_periods") or []
    period = ""
    if fps and isinstance(fps, list) and isinstance(fps[0], dict):
        period = str(fps[0].get("period") or "")
    return audit, doc_type, period


def _select_extraction_by_base_period(
    ticker: str,
    explicit: str | None,
    base_period: str,
) -> Path:
    """Phase 1.5.11 — pick the right ``raw_extraction*.yaml`` for the
    requested ``--base-period``.

    Values:

    - ``AUTO`` (default): first candidate by mtime; warn if it's unaudited.
    - ``LATEST-AUDITED``: skip unaudited entries, pick the first audited.
    - ``<period>`` (e.g. ``FY2024`` or ``FY2025-preliminary``): exact
      match on the extraction's primary period label or file stem.

    Falls back to :func:`_resolve_extraction_path` behaviour when no
    multiple candidates exist — keeps backward compat with the
    single-file layout.
    """
    if explicit:
        return _resolve_extraction_path(ticker, explicit)

    candidates = _candidate_extraction_files(ticker)
    if not candidates:
        return _resolve_extraction_path(ticker, None)
    if len(candidates) == 1:
        return candidates[0]

    metadata = [(p, *_peek_audit_metadata(p)) for p in candidates]

    if base_period == _BASE_PERIOD_AUTO:
        chosen = metadata[0]
        if chosen[1] == "unaudited":
            console.print(
                f"[yellow]AUTO selected an unaudited extraction "
                f"({chosen[0].name}).[/yellow] Pass "
                "--base-period LATEST-AUDITED to skip preliminary sources."
            )
        return chosen[0]

    if base_period == _BASE_PERIOD_LATEST_AUDITED:
        for path, audit, _doc, _period in metadata:
            if audit == "audited":
                return path
        raise typer.BadParameter(
            f"No audited extraction found for {ticker} "
            f"(checked {len(metadata)} candidate file(s))."
        )

    # Explicit period label — match on primary period OR filename stem.
    target = base_period.lower()
    for path, _audit, _doc, period in metadata:
        if period.lower() == target or target in path.stem.lower():
            return path
    raise typer.BadParameter(
        f"--base-period {base_period!r} did not match any extraction for "
        f"{ticker}. Candidates: "
        + ", ".join(f"{p.name} (period={per}, audit={aud})"
                    for p, aud, _doc, per in metadata)
    )


# ----------------------------------------------------------------------
# Build coordinator
# ----------------------------------------------------------------------
def _build_coordinator(ticker: str) -> PipelineCoordinator:
    """Wire the real service graph for production runs.

    Phase 1.5.6: wires all eleven pipeline stages by default —
    ingestion / WACC / extraction / cross-check / canonical /
    persist / guardrails / valuation / persist-valuation / ficha.
    Earlier coordinators left stages 9-11 to SKIP.
    """
    _ = ticker  # unused — PipelineCoordinator takes ticker per-call
    cost_tracker = CostTracker()
    llm_provider = AnthropicProvider()
    extraction_coordinator = ExtractionCoordinator(
        profile=Profile.P1_INDUSTRIAL,
        llm=llm_provider,
        cost_tracker=cost_tracker,
    )
    fmp = FMPProvider()
    cross_check_gate = CrossCheckGate(fmp, YFinanceProvider())
    return PipelineCoordinator(
        document_repo=DocumentRepository(),
        metadata_repo=MetadataRepository(),
        cross_check_gate=cross_check_gate,
        extraction_coordinator=extraction_coordinator,
        state_repo=CompanyStateRepository(),
        # Phase 1.5.6: stages 9-11 wired by default.
        valuation_composer=ValuationComposer(),
        scenario_composer=ScenarioComposer(dcf_engine=FCFFDCFEngine(n_years=5)),
        valuation_repo=ValuationRepository(),
        market_data_provider=fmp,
        ficha_composer=FichaComposer(),
        company_repo=CompanyRepository(),
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
    base_period: str = typer.Option(
        _BASE_PERIOD_AUTO,
        "--base-period",
        help=(
            "Which extraction to process when multiple exist for the "
            "ticker. AUTO (default): most recent by mtime (warns if "
            "unaudited). LATEST-AUDITED: most recent audited, skipping "
            "preliminary sources. Or pass an explicit label like "
            "'FY2024' / 'FY2025-preliminary' to match a specific file."
        ),
    ),
) -> None:
    """Run the Phase 1.5 pipeline end-to-end for ``ticker``."""
    try:
        wacc_resolved = _resolve_wacc_path(ticker, wacc_path or None)
        extraction_resolved = _select_extraction_by_base_period(
            ticker,
            extraction_path or None,
            base_period or _BASE_PERIOD_AUTO,
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
