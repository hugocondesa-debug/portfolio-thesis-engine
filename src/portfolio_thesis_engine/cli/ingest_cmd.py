"""``pte ingest`` — register documents for a ticker.

Usage::

    pte ingest --ticker 1846.HK \\
      --files path/to/annual_report_2024.md,path/to/interim_h1_2025.md,path/to/wacc_inputs.md \\
      [--mode bulk_markdown|pre_extracted] \\
      [--profile P1]

Default mode is ``bulk_markdown``. ``pre_extracted`` raises
``NotImplementedError`` (Phase 2 feature).
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from portfolio_thesis_engine.ingestion.base import IngestionError
from portfolio_thesis_engine.ingestion.coordinator import IngestionCoordinator
from portfolio_thesis_engine.storage.filesystem_repo import DocumentRepository
from portfolio_thesis_engine.storage.sqlite_repo import MetadataRepository

console = Console()


def _split_files(files_arg: str) -> list[Path]:
    """Parse a comma-separated list of file paths. Trims whitespace."""
    parts = [p.strip() for p in files_arg.split(",") if p.strip()]
    return [Path(p).expanduser() for p in parts]


def ingest(
    ticker: str = typer.Option(..., "--ticker", "-t", help="Target ticker (e.g. 1846.HK)."),
    files: str = typer.Option(
        "",
        "--files",
        "-f",
        help="Comma-separated list of file paths to ingest.",
    ),
    extraction: str = typer.Option(
        "",
        "--extraction",
        "-e",
        help=(
            "Shortcut: path to raw_extraction.yaml. Added to --files "
            "automatically and stored under doc_type='raw_extraction'."
        ),
    ),
    mode: str = typer.Option(
        "bulk_markdown",
        "--mode",
        "-m",
        help="Ingestion mode: 'bulk_markdown' (default) or 'pre_extracted' (Phase 2).",
    ),
    profile: str = typer.Option(
        "P1",
        "--profile",
        help="Company profile to register (P1/P2/…). Default P1.",
    ),
) -> None:
    """Ingest one or more document files under ``ticker``.

    Phase 1.5: ``--extraction <path>`` is a convenience for the
    analyst workflow — pass it alongside (or instead of) ``--files``
    and the raw_extraction.yaml is registered with the ingestion
    coordinator. Downstream ``pte process`` picks it up automatically.
    """
    console.print(f"[bold]Ingesting {ticker}[/bold] via mode [cyan]{mode}[/cyan]\n")

    paths = _split_files(files) if files else []
    if extraction:
        paths.append(Path(extraction).expanduser())
    if not paths:
        console.print(
            "[red]No files provided. Pass --files and/or --extraction.[/red]"
        )
        raise typer.Exit(code=1)

    doc_repo = DocumentRepository()
    meta_repo = MetadataRepository()
    coord = IngestionCoordinator(doc_repo, meta_repo)

    try:
        result = coord.ingest(ticker=ticker, files=paths, mode=mode, profile=profile)
    except IngestionError as e:
        console.print(f"[red]Ingestion failed:[/red] {e}")
        raise typer.Exit(code=1) from e
    except NotImplementedError as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=2) from e

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Doc ID", overflow="fold")
    table.add_column("Type")
    table.add_column("Report date")
    table.add_column("Size (KB)", justify="right")
    table.add_column("Hash (prefix)")

    for d in result.documents:
        size_kb = d.metadata.get("size_bytes", 0) / 1024
        table.add_row(
            d.doc_id,
            d.doc_type,
            d.report_date or "—",
            f"{size_kb:,.1f}",
            d.content_hash[:12],
        )
    console.print(table)

    if result.errors:
        console.print("\n[yellow]Warnings:[/yellow]")
        for warning in result.errors:
            console.print(f"  • {warning}")

    console.print(
        f"\n[green]Ingested {len(result.documents)} document(s) for {result.ticker}.[/green]"
    )
