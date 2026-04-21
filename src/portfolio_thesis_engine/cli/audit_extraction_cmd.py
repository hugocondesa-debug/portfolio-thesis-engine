"""``pte audit-extraction`` — validate the most recent raw_extraction for a ticker.

Wraps :func:`validate_extraction` by first resolving the
``raw_extraction.yaml`` path via the document repository (ingested
copy) or the ``~/data_inputs/{ticker}/raw_extraction.yaml`` default.

Usage::

    pte audit-extraction 1846.HK [--profile P1]

Exit codes match :command:`pte validate-extraction` (0 / 1 / 2).
"""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from portfolio_thesis_engine.cli.validate_extraction_cmd import validate_extraction
from portfolio_thesis_engine.storage.base import normalise_ticker
from portfolio_thesis_engine.storage.filesystem_repo import DocumentRepository

console = Console()


def _find_extraction_path(ticker: str) -> Path:
    """Same logic as :func:`_resolve_extraction_path` in ``process_cmd`` —
    checks the document repository first, then the default home-layout
    directory. Raises :class:`typer.BadParameter` when absent."""
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
        f"No raw_extraction.yaml found for {ticker}. Ingest it first "
        f"(pte ingest --extraction …) or place it at {default}."
    )


def audit_extraction(
    ticker: str = typer.Argument(..., help="Target ticker (e.g. 1846.HK)."),
    profile: str = typer.Option(
        "P1",
        "--profile",
        help="Profile code for completeness checklist. Default P1.",
    ),
) -> None:
    """Validate the most recent ingested extraction for ``ticker``."""
    try:
        path = _find_extraction_path(ticker)
    except typer.BadParameter as e:
        console.print(f"[red]{e}[/red]")
        raise typer.Exit(code=2) from e

    console.print(f"[dim]Auditing {path}[/dim]\n")
    validate_extraction(str(path), profile=profile)


__all__ = ["audit_extraction"]
