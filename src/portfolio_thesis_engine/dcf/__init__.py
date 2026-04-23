"""Phase 2 Sprint 4A-alpha — profile-based DCF valuation.

Parallel to the Phase-1 ``valuation/`` package; Sprint 4 adds profile
taxonomy, scenario-rich YAML input, a 3-stage P1 DCF engine, and
forecast-coherence warnings. Other profiles (P2 financial, P3 REIT,
P4 cyclical, P5 high-growth, P6 mature stable) are stubbed with
``NotImplementedError`` until Sprint 4A-beta / 4B / 4C.
"""

from portfolio_thesis_engine.dcf.profiles import (
    DCFProfile,
    ProfileHeuristic,
    infer_profile_from_industry,
    load_valuation_profile,
)
from portfolio_thesis_engine.dcf.schemas import (
    AssetBasedMethodologyConfig,
    DCFMethodologyConfig,
    DCFStageProjection,
    DCFStructure,
    DCFValuation,
    DCFValuationResult,
    ForecastWarning,
    MethodologyConfig,
    MultipleExitMethodologyConfig,
    Scenario,
    ScenarioDriverOverride,
    ScenarioSet,
    TerminalMultipleScenario,
    TransactionPrecedentMethodologyConfig,
    ValuationMethodology,
    ValuationProfile,
)

__all__ = [
    "AssetBasedMethodologyConfig",
    "DCFMethodologyConfig",
    "DCFProfile",
    "DCFStageProjection",
    "DCFStructure",
    "DCFValuation",
    "DCFValuationResult",
    "ForecastWarning",
    "MethodologyConfig",
    "MultipleExitMethodologyConfig",
    "ProfileHeuristic",
    "Scenario",
    "ScenarioDriverOverride",
    "ScenarioSet",
    "TerminalMultipleScenario",
    "TransactionPrecedentMethodologyConfig",
    "ValuationMethodology",
    "ValuationProfile",
    "infer_profile_from_industry",
    "load_valuation_profile",
]
