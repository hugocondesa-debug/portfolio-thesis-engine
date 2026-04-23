"""Phase 2 Sprint 4A-alpha Part B — scenarios YAML loader.

Converts ``data/yamls/companies/<ticker>/scenarios.yaml`` into a
:class:`ScenarioSet`. The YAML schema supports unlimited scenarios,
each with sparse driver overrides on top of a common ``base_drivers``
block. Probability sums are validated in the schema.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from portfolio_thesis_engine.dcf.schemas import ScenarioSet
from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.storage.base import normalise_ticker


def _yaml_path(ticker: str) -> Path:
    return (
        settings.data_dir
        / "yamls"
        / "companies"
        / normalise_ticker(ticker)
        / "scenarios.yaml"
    )


def load_scenarios(ticker: str) -> ScenarioSet | None:
    """Return the parsed :class:`ScenarioSet` or ``None`` when no
    scenarios.yaml exists for the ticker."""
    path = _yaml_path(ticker)
    if not path.exists():
        return None
    with path.open() as fh:
        payload = yaml.safe_load(fh) or {}
    return ScenarioSet.model_validate(payload)


__all__ = ["load_scenarios"]
