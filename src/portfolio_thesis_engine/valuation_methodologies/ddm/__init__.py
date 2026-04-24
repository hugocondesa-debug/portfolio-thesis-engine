"""Phase 2 Sprint 4B — Dividend Discount Model engine."""

from portfolio_thesis_engine.valuation_methodologies.ddm.dividend_stream_extractor import (
    compute_dividend_per_share,
    extract_dividend_stream,
)
from portfolio_thesis_engine.valuation_methodologies.ddm.engine import DDMEngine
from portfolio_thesis_engine.valuation_methodologies.ddm.schemas import (
    DDMProjection,
    DDMYear,
)

__all__ = [
    "DDMEngine",
    "DDMProjection",
    "DDMYear",
    "compute_dividend_per_share",
    "extract_dividend_stream",
]
