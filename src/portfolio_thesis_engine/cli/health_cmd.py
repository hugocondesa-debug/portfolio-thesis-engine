"""``pte health-check`` — render a Rich status table for every component."""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from portfolio_thesis_engine.shared.config import settings

console = Console()


def _tailscale_status() -> tuple[str, str]:
    """Best-effort tailscale probe. Non-fatal if the CLI is missing."""
    if shutil.which("tailscale") is None:
        return ("OPTIONAL", "tailscale CLI not installed")
    try:
        result = subprocess.run(  # noqa: S603
            ["tailscale", "status", "--json"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        return ("WARN", f"tailscale probe failed: {e}")
    if result.returncode == 0:
        return ("OK", "online")
    # Non-zero usually means "logged out"; surface the stderr tail.
    tail = (result.stderr or result.stdout).strip().splitlines()
    hint = tail[-1] if tail else f"exit {result.returncode}"
    return ("WARN", hint)


def _row(name: str, status: str, detail: str) -> tuple[str, str, str]:
    colour = {
        "OK": "[green]OK[/green]",
        "WARN": "[yellow]WARN[/yellow]",
        "MISSING": "[red]MISSING[/red]",
        "FAIL": "[red]FAIL[/red]",
        "OPTIONAL": "[dim]—[/dim]",
    }.get(status, status)
    return (name, colour, detail)


def health_check() -> None:
    """Render a status table and exit with 1 if any required component fails."""
    console.print("[bold]Portfolio Thesis Engine — Health Check[/bold]\n")

    table = Table(show_header=True, header_style="bold magenta")
    table.add_column("Component")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")

    exit_fail = False

    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    py_ok = sys.version_info >= (3, 12)
    table.add_row(
        *_row(
            "Python",
            "OK" if py_ok else "FAIL",
            f"{py_version} (requires 3.12+)",
        )
    )
    if not py_ok:
        exit_fail = True

    for key_name in ("anthropic_api_key", "openai_api_key", "fmp_api_key"):
        has_key = bool(settings.secret(key_name))
        table.add_row(
            *_row(
                key_name.upper(),
                "OK" if has_key else "MISSING",
                "configured" if has_key else "set in .env to enable real API calls",
            )
        )

    data_dir: Path = settings.data_dir
    table.add_row(
        *_row(
            "Data directory",
            "OK" if data_dir.exists() else "WARN",
            str(data_dir) + ("" if data_dir.exists() else " (run 'pte setup')"),
        )
    )

    backup_dir: Path = settings.backup_dir
    table.add_row(
        *_row(
            "Backup directory",
            "OK" if backup_dir.exists() else "WARN",
            str(backup_dir) + ("" if backup_dir.exists() else " (run 'pte setup')"),
        )
    )

    duckdb_path = data_dir / "timeseries.duckdb"
    table.add_row(
        *_row(
            "DuckDB (timeseries)",
            "OK" if duckdb_path.exists() else "OPTIONAL",
            str(duckdb_path) + ("" if duckdb_path.exists() else " (created on first use)"),
        )
    )

    sqlite_path = data_dir / "metadata.sqlite"
    table.add_row(
        *_row(
            "SQLite (metadata)",
            "OK" if sqlite_path.exists() else "OPTIONAL",
            str(sqlite_path) + ("" if sqlite_path.exists() else " (created on first use)"),
        )
    )

    ts_status, ts_detail = _tailscale_status()
    table.add_row(*_row("Tailscale", ts_status, ts_detail))

    console.print(table)

    if exit_fail:
        console.print("\n[red]Health check failed — see components above.[/red]")
        raise SystemExit(1)

    console.print("\n[green]All required components OK.[/green]")
