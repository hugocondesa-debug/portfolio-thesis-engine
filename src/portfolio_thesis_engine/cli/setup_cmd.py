"""``pte setup`` — idempotent initialisation of the data tree.

Creates the directory layout every other module expects. Safe to re-run —
missing directories are created, existing ones are left alone. Validates
Python version and warns (does not fail) if ``.env`` is missing.
"""

from __future__ import annotations

import sys
from pathlib import Path

from rich.console import Console

from portfolio_thesis_engine.shared.config import settings

console = Console()

# Directories created under settings.data_dir. Nested entries are created
# top-down automatically by ``Path.mkdir(parents=True)``.
_DATA_SUBDIRS: tuple[str, ...] = (
    "yamls/companies",
    "yamls/portfolio/positions",
    "yamls/market_contexts",
    "yamls/library",
    "documents",
)


def _ensure_dir(path: Path) -> bool:
    """Create ``path`` if absent. Returns True if it was newly created."""
    if path.exists():
        return False
    path.mkdir(parents=True, exist_ok=True)
    return True


def _touch_gitkeep(directory: Path) -> bool:
    """Create a ``.gitkeep`` file if the directory is empty. Returns True
    if the file was newly created."""
    if not directory.is_dir():
        return False
    # Skip if directory already has non-hidden content worth committing
    if any(not child.name.startswith(".") for child in directory.iterdir()):
        return False
    gitkeep = directory / ".gitkeep"
    if gitkeep.exists():
        return False
    gitkeep.touch()
    return True


def setup() -> None:
    """Initialise data tree and validate prerequisites."""
    console.print("[bold]Portfolio Thesis Engine — setup[/bold]\n")

    py_ok = sys.version_info >= (3, 12)
    py_version = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    if py_ok:
        console.print(f"[green]✓[/green] Python {py_version} OK")
    else:
        console.print(f"[red]✗[/red] Python {py_version} too old; 3.12+ required")
        raise SystemExit(1)

    repo_root = Path.cwd()
    env_file = repo_root / ".env"
    if env_file.exists():
        console.print("[green]✓[/green] .env present")
    else:
        console.print("[yellow]![/yellow] .env not found — copy .env.example and fill in API keys")

    data_dir: Path = settings.data_dir
    backup_dir: Path = settings.backup_dir

    created_dirs: list[str] = []
    created_gitkeeps: list[str] = []

    for root in (data_dir, backup_dir):
        if _ensure_dir(root):
            created_dirs.append(str(root))

    for sub in _DATA_SUBDIRS:
        target = data_dir / sub
        if _ensure_dir(target):
            created_dirs.append(str(target))
        if _touch_gitkeep(target):
            created_gitkeeps.append(str(target / ".gitkeep"))

    # Top-level data_dir should carry a .gitkeep if empty (so git preserves
    # it); same for backup/.
    for top in (data_dir, backup_dir):
        if _touch_gitkeep(top):
            created_gitkeeps.append(str(top / ".gitkeep"))

    if created_dirs:
        console.print("\n[bold]Directories created:[/bold]")
        for d in created_dirs:
            console.print(f"  [green]+[/green] {d}")
    else:
        console.print("\n[dim]All directories already present.[/dim]")

    if created_gitkeeps:
        console.print("\n[bold].gitkeep files created:[/bold]")
        for g in created_gitkeeps:
            console.print(f"  [green]+[/green] {g}")

    console.print("\n[bold green]Setup complete.[/bold green]")
