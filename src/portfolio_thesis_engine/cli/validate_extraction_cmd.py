"""``pte validate-extraction`` — standalone extraction validator.

Runs :class:`ExtractionValidator` three tiers against a
``raw_extraction.yaml`` file without touching the pipeline or any
external API. Useful for Hugo's Claude.ai workflow: validate the YAML
locally before paying for a full ``pte process`` run.

Usage::

    pte validate-extraction path/to/raw_extraction.yaml [--profile P1]

Exit codes:

- **0** — all three tiers OK (or WARN/SKIP only).
- **1** — warn or completeness-FAIL tier surfaced issues.
- **2** — strict FAIL (accounting identities broken).
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from portfolio_thesis_engine.ingestion.base import IngestionError
from portfolio_thesis_engine.ingestion.raw_extraction_parser import parse_raw_extraction
from portfolio_thesis_engine.ingestion.raw_extraction_validator import (
    ExtractionValidator,
    ValidationReport,
)
from portfolio_thesis_engine.schemas.common import Profile

console = Console()

_STATUS_STYLE = {
    "OK": "[green]OK[/green]",
    "WARN": "[yellow]WARN[/yellow]",
    "FAIL": "[red]FAIL[/red]",
    "SKIP": "[dim]SKIP[/dim]",
}


def _render_report(report: ValidationReport) -> None:
    table = Table(
        show_header=True,
        header_style="bold magenta",
        title=f"Validation — {report.tier}",
    )
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Message", overflow="fold")
    for r in report.results:
        table.add_row(
            r.check_id,
            _STATUS_STYLE.get(r.status, r.status),
            r.message,
        )
    console.print(table)


def validate_extraction(
    path: str = typer.Argument(..., help="Path to raw_extraction.yaml."),
    profile: str = typer.Option(
        "P1",
        "--profile",
        help="Profile code for completeness checklist (P1/P2/P3a/P3b/P4/P5/P6). "
        "Default P1.",
    ),
) -> None:
    """Validate a raw_extraction.yaml without running the pipeline."""
    p = Path(path).expanduser()
    try:
        raw = parse_raw_extraction(p)
    except IngestionError as e:
        console.print(f"[red]Failed to parse {p}:[/red] {e}")
        raise typer.Exit(code=2) from e

    try:
        profile_enum = Profile(profile)
    except ValueError as e:
        console.print(f"[red]Unknown profile {profile!r}[/red]")
        raise typer.Exit(code=2) from e

    validator = ExtractionValidator()
    strict = validator.validate_strict(raw)
    warn = validator.validate_warn(raw)
    comp = validator.validate_completeness(raw, profile_enum)

    _render_report(strict)
    _render_report(warn)
    _render_report(comp)

    worst_checks = (strict.overall_status, warn.overall_status, comp.overall_status)
    console.print(
        f"\n[bold]Summary:[/bold] strict={_STATUS_STYLE.get(strict.overall_status)} "
        f"· warn={_STATUS_STYLE.get(warn.overall_status)} "
        f"· completeness={_STATUS_STYLE.get(comp.overall_status)}"
    )

    # Exit-code policy: strict FAIL → 2 (blocks pipeline); any warn/
    # completeness WARN/FAIL → 1 (surfaced but non-blocking); else 0.
    if strict.overall_status == "FAIL":
        raise typer.Exit(code=2)
    if "FAIL" in worst_checks or "WARN" in worst_checks:
        raise typer.Exit(code=1)


__all__ = ["validate_extraction"]
