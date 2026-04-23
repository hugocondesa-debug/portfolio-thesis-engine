"""Phase 2 Sprint 3 — auto-generated cost-of-capital engine.

The :class:`WACCGenerator` composes a :class:`WACCComputation` from
static Damodaran tables plus a ticker's operational characteristics
(industry, revenue geography, capital structure). Runs alongside the
manual :class:`WACCInputs` path; the analytical layer can surface both.
"""

from portfolio_thesis_engine.capital.wacc_generator import (
    GeographyWeight,
    WACCGenerator,
    WACCGeneratorInputs,
)

__all__ = [
    "GeographyWeight",
    "WACCGenerator",
    "WACCGeneratorInputs",
]
