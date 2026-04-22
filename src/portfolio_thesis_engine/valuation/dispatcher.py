"""Phase 1.5.9 — :class:`ValuationDispatcher` + per-profile engine stubs.

The framework architecture (Concern 4) acknowledges that FCFF is
appropriate for P1 industrials only; other profiles need different
valuation frameworks:

- **P2 Banks** — :class:`DDMEngine` (dividend discount or residual
  income — equity stream, not FCFF).
- **P5 REITs** — :class:`NAVEngine` (net asset value at market prices).
- **P3a Insurance** — :class:`EmbeddedValueEngine` (embedded + new
  business value).

Stubs raise :class:`NotImplementedError` with the target Phase / Sprint
embedded in the message so the analyst sees a clean call-site error.
:class:`ValuationDispatcher.select_engine` routes by
:attr:`CompanyIdentity.profile`.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from portfolio_thesis_engine.schemas.common import Profile
from portfolio_thesis_engine.schemas.company import CanonicalCompanyState
from portfolio_thesis_engine.schemas.valuation import (
    MarketSnapshot,
    Scenario,
)
from portfolio_thesis_engine.valuation.base import (
    TopLevelValuationEngine,
    ValuationResult,
)


# ----------------------------------------------------------------------
# Stubs for Phase 2 engines
# ----------------------------------------------------------------------
class _UnimplementedEngine:
    """Base for stub engines — shared ``compute`` that raises with a
    targeted error message."""

    _method: str = ""
    _profile: str = ""
    _target_sprint: str = ""

    def compute(
        self,
        canonical_state: CanonicalCompanyState,
        scenario: Scenario,
        market: MarketSnapshot,
    ) -> ValuationResult:
        raise NotImplementedError(
            f"{self._method} engine for profile {self._profile} is a "
            f"Phase 1.5.9 stub — implementation scheduled for "
            f"{self._target_sprint}."
        )

    def describe(self) -> dict[str, Any]:
        return {
            "engine": type(self).__name__,
            "method": self._method,
            "profile": self._profile,
            "implemented": False,
            "target_sprint": self._target_sprint,
        }


class DDMEngine(_UnimplementedEngine):
    """P2 banks — dividend discount or residual income."""

    _method = "DDM"
    _profile = "P2_BANKS"
    _target_sprint = "Phase 2 Sprint 6"


class NAVEngine(_UnimplementedEngine):
    """P3b REITs — net-asset-value at market prices."""

    _method = "NAV"
    _profile = "P3B_REITS"
    _target_sprint = "Phase 2 Sprint TBD"


class EmbeddedValueEngine(_UnimplementedEngine):
    """P3a insurance — embedded value + new business value."""

    _method = "Embedded Value"
    _profile = "P3A_INSURANCE"
    _target_sprint = "Phase 2 Sprint TBD"


# ----------------------------------------------------------------------
# Dispatcher
# ----------------------------------------------------------------------
class ValuationDispatcher:
    """Select the right :class:`TopLevelValuationEngine` for the
    canonical state's profile.

    P1 industrials (the only implemented profile in Phase 1.5.9) route
    to :class:`FCFFDCFEngine`; Phase 2 profiles route to their stubs
    and raise :class:`NotImplementedError` if the pipeline actually
    tries to value them.
    """

    def __init__(
        self,
        fcff_engine: TopLevelValuationEngine | None = None,
        p2_engine: TopLevelValuationEngine | None = None,
        p3a_engine: TopLevelValuationEngine | None = None,
        p3b_engine: TopLevelValuationEngine | None = None,
    ) -> None:
        # Late import to avoid a circular with :mod:`valuation.dcf`.
        from portfolio_thesis_engine.valuation.dcf import FCFFDCFEngine

        self._fcff = fcff_engine or FCFFDCFEngine()
        self._p2 = p2_engine or DDMEngine()
        self._p3a = p3a_engine or EmbeddedValueEngine()
        self._p3b = p3b_engine or NAVEngine()

    def select_engine(
        self, canonical_state: CanonicalCompanyState
    ) -> TopLevelValuationEngine:
        return self.select_engine_for_profile(canonical_state.identity.profile)

    def select_engine_for_profile(
        self, profile: Profile
    ) -> TopLevelValuationEngine:
        if profile == Profile.P1_INDUSTRIAL:
            return self._fcff
        if profile == Profile.P2_BANKS:
            return self._p2
        if profile == Profile.P3A_INSURANCE:
            return self._p3a
        if profile == Profile.P3B_REITS:
            return self._p3b
        # P4 resources, P5 pre-revenue, P6 holdings — Phase 2 engines
        # not yet stubbed. Route to FCFF with a caveat in describe().
        return self._fcff

    def describe(self) -> dict[str, Any]:
        return {
            "dispatcher": "ValuationDispatcher",
            "P1_INDUSTRIAL": self._fcff.describe(),
            "P2_BANKS": self._p2.describe(),
            "P3A_INSURANCE": self._p3a.describe(),
            "P3B_REITS": self._p3b.describe(),
        }


__all__ = [
    "DDMEngine",
    "EmbeddedValueEngine",
    "NAVEngine",
    "ValuationDispatcher",
]
