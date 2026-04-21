"""Valuation engine — DCF 3-scenario + equity bridge + IRR + composer.

Public surface:

- :class:`FCFFDCFEngine` — projects FCFF, computes terminal value and EV.
- :class:`EquityBridge` — EV → Equity → per-share.
- :class:`IRRDecomposer` — decomposes target-price IRR into fundamental
  growth vs multiple re-rating.
- :class:`ScenarioComposer` — runs Bear/Base/Bull from
  :class:`WACCInputs` and assembles :class:`Scenario` objects.
- :class:`ValuationComposer` — combines scenarios + market snapshot
  into the final :class:`ValuationSnapshot`.
"""

from portfolio_thesis_engine.valuation.base import (
    DCFResult,
    EquityValue,
    IRRResult,
    ValuationEngine,
)
from portfolio_thesis_engine.valuation.composer import ValuationComposer
from portfolio_thesis_engine.valuation.dcf import FCFFDCFEngine
from portfolio_thesis_engine.valuation.equity_bridge import EquityBridge
from portfolio_thesis_engine.valuation.irr import IRRDecomposer
from portfolio_thesis_engine.valuation.scenarios import ScenarioComposer

__all__ = [
    "DCFResult",
    "EquityBridge",
    "EquityValue",
    "FCFFDCFEngine",
    "IRRDecomposer",
    "IRRResult",
    "ScenarioComposer",
    "ValuationComposer",
    "ValuationEngine",
]
