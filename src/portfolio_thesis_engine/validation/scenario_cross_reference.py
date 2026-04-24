"""Runtime cross-validation between indicators and scenarios.

Generic buckets expand to the full set of scenarios that resolve to
that bucket (via explicit ``Scenario.bucket`` or name inference);
specific names pass through if they exist in the scenario set. Unknown
names are dropped from the expansion but surfaced as warnings by
:func:`validate_scenario_cross_reference` so the analyst can audit.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from portfolio_thesis_engine.schemas.scenario_bucket import (
    ScenarioBucket,
    infer_bucket_from_name,
)

if TYPE_CHECKING:
    from portfolio_thesis_engine.briefing.leading_indicators import (
        LeadingIndicatorsSet,
    )
    from portfolio_thesis_engine.dcf.schemas import Scenario, ScenarioSet


_VALID_BUCKETS = {b.value for b in ScenarioBucket}


def _resolve_scenario_bucket(scenario: "Scenario") -> ScenarioBucket:
    """Return the bucket for a scenario — explicit ``bucket`` field
    wins, else inferred from ``name`` via
    :func:`infer_bucket_from_name`."""
    explicit = getattr(scenario, "bucket", None)
    if explicit is not None:
        return explicit
    return infer_bucket_from_name(scenario.name)


def expand_scenario_relevance(
    relevance: list[str],
    scenario_set: "ScenarioSet",
) -> list[str]:
    """Expand generic buckets + pass-through specific names.

    - A bucket value (e.g. ``"BULL"``) expands to **all** scenarios in
      ``scenario_set`` whose resolved bucket matches.
    - A specific name is kept only if a scenario with that exact
      ``name`` exists in ``scenario_set`` (unknown names are silently
      dropped; use :func:`validate_scenario_cross_reference` to surface
      them as warnings).

    Returns a **sorted, deduplicated** list of scenario names.
    """
    expanded: set[str] = set()
    for item in relevance:
        ref = str(item)
        if ref in _VALID_BUCKETS:
            target_bucket = ScenarioBucket(ref)
            for scenario in scenario_set.scenarios:
                if _resolve_scenario_bucket(scenario) is target_bucket:
                    expanded.add(scenario.name)
            continue
        if any(s.name == ref for s in scenario_set.scenarios):
            expanded.add(ref)
    return sorted(expanded)


def validate_scenario_cross_reference(
    leading_indicators: "LeadingIndicatorsSet | None",
    scenario_set: "ScenarioSet",
    capital_allocation: object | None = None,
) -> list[str]:
    """Return warnings for ``scenario_relevance`` entries that are
    neither bucket values nor known scenario names.

    Non-blocking — warnings are intended for analyst review. Generic
    buckets always resolve; unknown specific names (including typos or
    scenarios that were dropped) produce one warning each. ``capital
    _allocation`` is accepted for forward-compat but is a no-op today
    (the current schema carries no ``scenario_relevance`` fields).
    """
    warnings: list[str] = []
    valid_names = {s.name for s in scenario_set.scenarios}

    if leading_indicators is not None:
        for indicator in leading_indicators.indicators:
            for ref in indicator.scenario_relevance or []:
                ref_str = str(ref)
                if ref_str in _VALID_BUCKETS:
                    continue
                if ref_str not in valid_names:
                    warnings.append(
                        f"leading_indicator '{indicator.name}' references "
                        f"unknown scenario '{ref_str}' "
                        "(not a bucket, not in scenarios.yaml)"
                    )

    _ = capital_allocation  # reserved — no relevance fields today.
    return warnings


__all__ = [
    "expand_scenario_relevance",
    "validate_scenario_cross_reference",
]
