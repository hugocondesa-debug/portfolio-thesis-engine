"""Typer entry point for the ``pte`` command installed via pyproject scripts."""

from __future__ import annotations

import typer

from portfolio_thesis_engine.cli.cross_check_cmd import cross_check
from portfolio_thesis_engine.cli.health_cmd import health_check
from portfolio_thesis_engine.cli.ingest_cmd import ingest
from portfolio_thesis_engine.cli.process_cmd import process
from portfolio_thesis_engine.cli.setup_cmd import setup
from portfolio_thesis_engine.cli.smoke_cmd import smoke_test

app = typer.Typer(
    name="pte",
    help="Portfolio Thesis Engine CLI",
    no_args_is_help=True,
    add_completion=False,
)

app.command("setup")(setup)
app.command("health-check")(health_check)
app.command("smoke-test")(smoke_test)
app.command("ingest")(ingest)
app.command("cross-check")(cross_check)
app.command("process")(process)


if __name__ == "__main__":  # pragma: no cover
    app()
