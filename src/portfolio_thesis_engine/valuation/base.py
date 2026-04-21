"""Shared dataclasses + ABC for the valuation engine.

Intermediate result objects — :class:`DCFResult`, :class:`EquityValue`,
:class:`IRRResult` — live here so sibling modules don't have to
import each other circularly. All three are frozen dataclasses: they're
value objects that individual engines *produce*, and the composer
reads.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class DCFResult:
    """Output of :meth:`FCFFDCFEngine.compute_target`."""

    enterprise_value: Decimal
    pv_explicit: Decimal
    pv_terminal: Decimal
    terminal_value: Decimal
    wacc_used: Decimal  # percent, e.g. 8.5 = 8.5 %
    implied_g: Decimal  # percent, terminal growth
    projected_fcff: tuple[Decimal, ...] = ()
    n_years: int = 0
    # Optional: per-year projection intermediates (revenue, margin, capex,
    # WC change, FCFF) for auditability. Dict-of-dicts keyed by year index.
    projection_detail: dict[int, dict[str, Decimal]] = field(default_factory=dict)


@dataclass(frozen=True)
class EquityValue:
    """Output of :meth:`EquityBridge.compute`.

    ``per_share`` is ``None`` when ``shares_outstanding`` is missing on
    the canonical state.
    """

    enterprise_value: Decimal
    net_debt: Decimal
    preferred_equity: Decimal
    nci: Decimal
    equity_value: Decimal
    shares_outstanding: Decimal | None
    per_share: Decimal | None


@dataclass(frozen=True)
class IRRResult:
    """Output of :meth:`IRRDecomposer.decompose`.

    All figures are annualised decimals, e.g. ``Decimal('0.12')`` = 12 %.
    Phase 1 keeps ``dividend_yield_p_a`` at zero; Phase 2 pulls it from
    the CF statement's dividends line once the extractor splits them.
    """

    total_p_a: Decimal
    fundamental_p_a: Decimal  # BV / earnings growth contribution
    rerating_p_a: Decimal
    dividend_yield_p_a: Decimal
    horizon_years: int


# ----------------------------------------------------------------------
# Engine ABC — purely cosmetic (we don't polymorphise) but documents
# the contract: engines consume some value-object input and emit one.
# ----------------------------------------------------------------------
class ValuationEngine(ABC):
    """Base class for valuation sub-engines.

    Subclasses describe what they compute in their docstring; the ABC
    doesn't enforce a specific method signature because DCF / equity /
    IRR each take different inputs.
    """

    @abstractmethod
    def describe(self) -> dict[str, Any]:
        """Return a brief description of the engine's configuration —
        used by the composer for audit metadata."""
