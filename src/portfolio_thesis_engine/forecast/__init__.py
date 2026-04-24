"""Phase 2 Sprint 4A-beta — three-statement forecast + iterative solver.

Produces per-scenario 5-year projections of Income Statement, Balance
Sheet, Cash Flow, and forward ratios (PER, FCF yield, ROIC, WACC) by
consuming ``scenarios.yaml`` drivers and ``capital_allocation.yaml``
policies. A pure-Python fixed-point solver converges the cash balance
constraint (CF Δcash ≡ BS cash roll).
"""

from portfolio_thesis_engine.forecast.orchestrator import (
    ForecastOrchestrator,
    persist_forecast,
)
from portfolio_thesis_engine.forecast.schemas import (
    BalanceSheetYear,
    CashFlowYear,
    ForecastResult,
    ForwardRatiosYear,
    IncomeStatementYear,
    ThreeStatementProjection,
)

__all__ = [
    "BalanceSheetYear",
    "CashFlowYear",
    "ForecastOrchestrator",
    "ForecastResult",
    "ForwardRatiosYear",
    "IncomeStatementYear",
    "ThreeStatementProjection",
    "persist_forecast",
]
