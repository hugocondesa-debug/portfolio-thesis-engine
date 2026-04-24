"""Phase 2 Sprint 4A-alpha.5 — briefing orchestration.

Bundles cost-structure analysis (Part A), leading-indicators framework
(Part B), and analytical briefing generator (Part C) that orchestrates
the full Sprint 1-4A-alpha.4 output into a single markdown document
for Claude.ai Project consumption.
"""

from portfolio_thesis_engine.briefing.cost_structure import (
    CostLineEvolution,
    CostStructureAnalysis,
    CostStructureAnalyzer,
    MarginBridge,
)
from portfolio_thesis_engine.briefing.generator import (
    AnalyticalBriefingGenerator,
    BriefingPurpose,
)
from portfolio_thesis_engine.briefing.leading_indicators import (
    IndicatorDataSource,
    IndicatorEnvironment,
    IndicatorSensitivity,
    LeadingIndicator,
    LeadingIndicatorsLoader,
    LeadingIndicatorsSet,
)

__all__ = [
    "AnalyticalBriefingGenerator",
    "BriefingPurpose",
    "CostLineEvolution",
    "CostStructureAnalysis",
    "CostStructureAnalyzer",
    "IndicatorDataSource",
    "IndicatorEnvironment",
    "IndicatorSensitivity",
    "LeadingIndicator",
    "LeadingIndicatorsLoader",
    "LeadingIndicatorsSet",
    "MarginBridge",
]
