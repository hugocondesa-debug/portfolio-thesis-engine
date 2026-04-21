"""Cross-check gate — validates extracted values against FMP + yfinance.

Runs after section extraction but before the extraction modules.
Blocks the pipeline on FAIL so silent LLM errors don't propagate into
the canonical company state.
"""

from portfolio_thesis_engine.cross_check.base import (
    CrossCheckMetric,
    CrossCheckReport,
    CrossCheckStatus,
)
from portfolio_thesis_engine.cross_check.gate import CrossCheckGate
from portfolio_thesis_engine.cross_check.thresholds import (
    DEFAULT_METRIC_THRESHOLDS,
    DEFAULT_THRESHOLDS,
    load_thresholds,
)

__all__ = [
    "DEFAULT_METRIC_THRESHOLDS",
    "DEFAULT_THRESHOLDS",
    "CrossCheckGate",
    "CrossCheckMetric",
    "CrossCheckReport",
    "CrossCheckStatus",
    "load_thresholds",
]
