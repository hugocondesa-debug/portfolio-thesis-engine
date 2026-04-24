"""Typer entry point for the ``pte`` command installed via pyproject scripts."""

from __future__ import annotations

import typer

from portfolio_thesis_engine.cli.analyze_cmd import analyze
from portfolio_thesis_engine.cli.audit_extraction_cmd import audit_extraction
from portfolio_thesis_engine.cli.briefing_cmd import briefing
from portfolio_thesis_engine.cli.cross_check_cmd import cross_check
from portfolio_thesis_engine.cli.forecast_cmd import forecast
from portfolio_thesis_engine.cli.generate_overrides_cmd import generate_overrides
from portfolio_thesis_engine.cli.health_cmd import health_check
from portfolio_thesis_engine.cli.historicals_cmd import historicals
from portfolio_thesis_engine.cli.ingest_cmd import ingest
from portfolio_thesis_engine.cli.peers_cmd import peers
from portfolio_thesis_engine.cli.process_cmd import process
from portfolio_thesis_engine.cli.reverse_cmd import reverse
from portfolio_thesis_engine.cli.setup_cmd import setup
from portfolio_thesis_engine.cli.show_cmd import show
from portfolio_thesis_engine.cli.smoke_cmd import smoke_test
from portfolio_thesis_engine.cli.validate_extraction_cmd import validate_extraction
from portfolio_thesis_engine.cli.valuation_cmd import valuation

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
app.command("show")(show)
app.command("validate-extraction")(validate_extraction)
app.command("audit-extraction")(audit_extraction)
app.command("generate-overrides")(generate_overrides)
app.command("historicals")(historicals)
app.command("analyze")(analyze)
app.command("peers")(peers)
app.command("valuation")(valuation)
app.command("reverse")(reverse)
app.command("briefing")(briefing)
app.command("forecast")(forecast)


if __name__ == "__main__":  # pragma: no cover
    app()
