"""Phase 1.5.10 — locate + load ``overrides.yaml`` for Module D.

Files live at::

    {portfolio_dir}/<ticker>/overrides.yaml

The ticker is normalised so ``1846.HK`` on disk matches the canonical
state's ticker. When the file doesn't exist, an empty override set is
returned so the classifier falls through to pure-regex behaviour.
"""

from __future__ import annotations

from pathlib import Path

from portfolio_thesis_engine.schemas.overrides import ModuleDOverrides
from portfolio_thesis_engine.shared.config import settings


def overrides_path_for(ticker: str, *, portfolio_dir: Path | None = None) -> Path:
    """Return the conventional path to ``overrides.yaml`` for a ticker."""
    base = portfolio_dir or settings.portfolio_dir
    safe = ticker.replace("/", "_")
    return base / safe / "overrides.yaml"


def load_overrides(
    ticker: str, *, portfolio_dir: Path | None = None
) -> ModuleDOverrides:
    """Load ``overrides.yaml`` for ``ticker``. When the file is absent
    or empty, return :meth:`ModuleDOverrides.empty`."""
    path = overrides_path_for(ticker, portfolio_dir=portfolio_dir)
    if not path.exists():
        return ModuleDOverrides.empty()
    content = path.read_text(encoding="utf-8")
    if not content.strip():
        return ModuleDOverrides.empty()
    return ModuleDOverrides.from_yaml(content)


__all__ = ["load_overrides", "overrides_path_for"]
