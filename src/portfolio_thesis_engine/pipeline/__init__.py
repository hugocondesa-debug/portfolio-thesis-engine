"""End-to-end pipeline orchestration.

The :class:`PipelineCoordinator` chains ingestion → section extraction
→ cross-check gate → extraction engine → canonical state persistence
→ guardrails under a single ``process(ticker)`` entry point.
"""

from portfolio_thesis_engine.pipeline.coordinator import (
    PipelineCoordinator,
    PipelineOutcome,
    PipelineStage,
    StageOutcome,
)

__all__ = [
    "PipelineCoordinator",
    "PipelineOutcome",
    "PipelineStage",
    "StageOutcome",
]
