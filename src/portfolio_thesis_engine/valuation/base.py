"""Shared dataclasses + ABC + Protocol for the valuation engine.

Intermediate result objects — :class:`DCFResult`, :class:`EquityValue`,
:class:`IRRResult` — live here so sibling modules don't have to
import each other circularly. All three are frozen dataclasses: they're
value objects that individual engines *produce*, and the composer
reads.

Phase 1.5.9 split the engine surface in two:

- :class:`ValuationEngine` (ABC) — local-scope sub-engines (DCF, equity
  bridge, IRR decomposer) that implement ``describe()`` and compose into
  a full valuation. Preserved for backwards compat with existing code.
- :class:`TopLevelValuationEngine` (Protocol) — the per-profile dispatch
  target: FCFF for P1, DDM for P2 banks, NAV for P5 REITs, Embedded
  Value for P3a insurance, etc. Each returns a :class:`ValuationResult`
  with the full projection + terminal + EV breakdown + equity bridge.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from portfolio_thesis_engine.schemas.company import CanonicalCompanyState
    from portfolio_thesis_engine.schemas.valuation import (
        EquityBridgeDetail,
        EVBreakdown,
        MarketSnapshot,
        ProjectionYear,
        Scenario,
        SensitivityGrid,
        TerminalProjection,
    )


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
# Sub-engine ABC — purely cosmetic (we don't polymorphise) but documents
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


# ----------------------------------------------------------------------
# Phase 1.5.9 — ValuationResult + top-level Protocol
# ----------------------------------------------------------------------
@dataclass(frozen=True)
class ValuationResult:
    """Output of a top-level :class:`TopLevelValuationEngine.compute`.

    Carries everything needed to fully populate a
    :class:`~portfolio_thesis_engine.schemas.valuation.Scenario` with
    projection + terminal + EV breakdown + equity bridge + sensitivity
    grids. The dispatcher sits between the pipeline and engines so the
    per-profile engine swap is transparent to callers.
    """

    projection: list[ProjectionYear]
    terminal: TerminalProjection | None
    enterprise_value_breakdown: EVBreakdown
    equity_bridge: EquityBridgeDetail
    sensitivity_grids: list[SensitivityGrid]
    target_per_share: Decimal | None
    methodology: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class TopLevelValuationEngine(Protocol):
    """Phase 1.5.9 — per-profile top-level engine contract.

    Implementations: :class:`FCFFDCFEngine` (P1 industrials, implemented),
    :class:`DDMEngine` (P2 banks, stub), :class:`NAVEngine` (P5 REITs,
    stub), :class:`EmbeddedValueEngine` (P3a insurance, stub). A
    :class:`ValuationDispatcher` selects the right engine from
    :attr:`CompanyIdentity.profile`.
    """

    def compute(
        self,
        canonical_state: CanonicalCompanyState,
        scenario: Scenario,
        market: MarketSnapshot,
    ) -> ValuationResult:
        """Produce the full valuation artefact for ``scenario`` against
        the canonical state and current market snapshot."""

    def describe(self) -> dict[str, Any]:
        """Return engine metadata (method name, inputs, limitations)."""
