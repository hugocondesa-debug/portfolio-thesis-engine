"""EV → Equity → per-share conversion.

Subtracts claims senior to common equity from the enterprise value:

- **Net debt** = financial liabilities − financial assets (from
  :class:`InvestedCapital`, which already excludes lease liabilities
  from "financial liabilities" since Phase 1 treats them separately).
- **Preferred equity** — Phase 1 assumes ``0`` (the P1 industrial
  archetype has no preferred line on the schema). Passed through as
  an override parameter so Phase 2 / P2 banks can populate it.
- **Non-controlling interests** — read from
  :class:`InvestedCapital.nci_claims`.

Lease liabilities **stay inside** EV: the Sprint 7 FCFF construction
already counts lease additions as investment (Module C.3), so
subtracting them here would double-count. Documented and pinned by a
dedicated unit test.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from portfolio_thesis_engine.schemas.company import CanonicalCompanyState
from portfolio_thesis_engine.valuation.base import (
    DCFResult,
    EquityValue,
    ValuationEngine,
)


class EquityBridge(ValuationEngine):
    """Bridge from enterprise value to equity value per share."""

    def compute(
        self,
        dcf_result: DCFResult,
        canonical_state: CanonicalCompanyState,
        *,
        preferred_equity: Decimal | None = None,
    ) -> EquityValue:
        ev = dcf_result.enterprise_value

        ic_list = canonical_state.analysis.invested_capital_by_period
        if ic_list:
            ic = ic_list[0]
            net_debt = ic.financial_liabilities - ic.financial_assets
            nci = ic.nci_claims
        else:
            net_debt = Decimal("0")
            nci = Decimal("0")

        preferred = preferred_equity if preferred_equity is not None else Decimal("0")

        equity_value = ev - net_debt - preferred - nci
        shares = canonical_state.identity.shares_outstanding
        per_share: Decimal | None = None
        if shares is not None and shares != 0:
            per_share = equity_value / shares

        return EquityValue(
            enterprise_value=ev,
            net_debt=net_debt,
            preferred_equity=preferred,
            nci=nci,
            equity_value=equity_value,
            shares_outstanding=shares,
            per_share=per_share,
        )

    def describe(self) -> dict[str, Any]:
        return {"engine": "EquityBridge"}
