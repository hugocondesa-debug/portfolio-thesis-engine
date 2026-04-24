"""Sprint 4A-alpha.8 — cross-yaml validation helpers.

Non-blocking analyst-side checks that stitch the independently-loaded
analyst YAMLs (``scenarios.yaml``, ``leading_indicators.yaml``,
``capital_allocation.yaml``) together and surface dangling or unknown
references. Used by :class:`DCFOrchestrator.run` after the per-file
Pydantic validation passes.
"""

from portfolio_thesis_engine.validation.scenario_cross_reference import (
    expand_scenario_relevance,
    validate_scenario_cross_reference,
)

__all__ = [
    "expand_scenario_relevance",
    "validate_scenario_cross_reference",
]
