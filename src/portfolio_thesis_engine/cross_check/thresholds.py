"""Threshold configuration for the cross-check gate.

Defaults are sensible for a mid-cap industrial. Operators override via
``PTE_CROSS_CHECK_THRESHOLDS_JSON`` in ``.env``::

    PTE_CROSS_CHECK_THRESHOLDS_JSON='{
        "defaults": {"PASS": "0.03", "WARN": "0.12"},
        "per_metric": {"operating_income": {"PASS": "0.05", "WARN": "0.20"}}
    }'

Shape:

- ``defaults``: mapping with keys ``PASS``, ``WARN``, ``sources_disagree``.
  Any missing key falls back to the hard-coded default below.
- ``per_metric``: optional per-metric override, same shape as ``defaults``
  minus ``sources_disagree`` (which is always cross-source).

Thresholds are compared against ``max_delta_pct`` in fractional form,
e.g. ``0.02`` = 2 %.
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import TypedDict


class ThresholdLevels(TypedDict, total=False):
    PASS: Decimal
    WARN: Decimal
    sources_disagree: Decimal


# < PASS tolerance → PASS; between PASS and WARN → WARN; > WARN → FAIL.
DEFAULT_THRESHOLDS: ThresholdLevels = {
    "PASS": Decimal("0.02"),
    "WARN": Decimal("0.10"),
    "sources_disagree": Decimal("0.05"),
}


# Metric-specific overrides — classification differences and restated
# figures make these wider than defaults by design.
DEFAULT_METRIC_THRESHOLDS: dict[str, ThresholdLevels] = {
    # Operating income bundles/disclosure varies across sources. Give it
    # more slack.
    "operating_income": {
        "PASS": Decimal("0.05"),
        "WARN": Decimal("0.15"),
    },
    # Market cap is live and moves between the FMP and yfinance probes.
    "market_cap": {
        "PASS": Decimal("0.02"),
        "WARN": Decimal("0.05"),
    },
}


def _coerce_decimal(value: object) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def load_thresholds(
    override_json: str | None = None,
) -> tuple[ThresholdLevels, dict[str, ThresholdLevels]]:
    """Merge hard-coded defaults with any JSON override.

    Returns ``(defaults, per_metric)``. Invalid JSON silently falls back
    to defaults so a misconfigured environment variable doesn't block
    every pipeline run — thresholds are advisory.
    """
    defaults: ThresholdLevels = dict(DEFAULT_THRESHOLDS)  # type: ignore[assignment]
    per_metric: dict[str, ThresholdLevels] = {
        metric: dict(spec)  # type: ignore[misc]
        for metric, spec in DEFAULT_METRIC_THRESHOLDS.items()
    }

    if not override_json:
        return defaults, per_metric

    try:
        parsed = json.loads(override_json)
    except json.JSONDecodeError:
        return defaults, per_metric

    if not isinstance(parsed, dict):
        return defaults, per_metric

    for key, value in (parsed.get("defaults") or {}).items():
        coerced = _coerce_decimal(value)
        if coerced is not None and key in ("PASS", "WARN", "sources_disagree"):
            defaults[key] = coerced  # type: ignore[literal-required]

    for metric, spec in (parsed.get("per_metric") or {}).items():
        if not isinstance(spec, dict):
            continue
        existing = per_metric.get(metric, {})
        merged: ThresholdLevels = dict(existing)  # type: ignore[assignment]
        for key, value in spec.items():
            coerced = _coerce_decimal(value)
            if coerced is not None and key in ("PASS", "WARN"):
                merged[key] = coerced  # type: ignore[literal-required]
        if merged:
            per_metric[metric] = merged

    return defaults, per_metric


def thresholds_for(
    metric: str,
    defaults: ThresholdLevels,
    per_metric: dict[str, ThresholdLevels],
) -> ThresholdLevels:
    """Resolve the effective thresholds for ``metric``: per-metric override
    shadows defaults key-by-key."""
    result: ThresholdLevels = dict(defaults)  # type: ignore[assignment]
    override = per_metric.get(metric) or {}
    if "PASS" in override:
        result["PASS"] = override["PASS"]
    if "WARN" in override:
        result["WARN"] = override["WARN"]
    return result
