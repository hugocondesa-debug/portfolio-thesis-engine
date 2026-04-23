"""Phase 2 Sprint 2A — Economic Balance Sheet schema.

Analytical reclassification of an IFRS balance sheet into an economic
view: operating items (part of invested capital), financial items
(net financial position), non-operating items, and equity.

Convention enforced per Sprint 2A design decisions:

- **IFRS 16 leases**: OPERATING treatment. ROU assets + lease liabilities
  flow through invested capital rather than net financial position.
  Aligns with McKinsey / Mauboussin and Module C Phase 1.5.3 FCFF
  treatment.
- **Goodwill**: included in invested capital when the canonical state
  doesn't provide a non-operating segmentation.
"""

from __future__ import annotations

from decimal import Decimal

from portfolio_thesis_engine.schemas.base import BaseSchema


class EconomicBalanceSheet(BaseSchema):
    """Reclassified BS in economic form.

    All fields are optional — preliminary / investor-presentation
    extractions may omit the balance sheet entirely, in which case
    :meth:`EconomicBSBuilder.build` returns ``None`` and this record
    never populates.
    """

    period: str
    currency: str

    # ── Operating (flows into invested capital) ────────────────────
    operating_ppe_net: Decimal | None = None
    rou_assets: Decimal | None = None
    operating_intangibles: Decimal | None = None
    goodwill: Decimal | None = None
    accounts_receivable: Decimal | None = None
    inventory: Decimal | None = None
    accounts_payable: Decimal | None = None
    operating_provisions: Decimal | None = None
    operating_deferred_tax_net: Decimal | None = None

    working_capital: Decimal | None = None
    invested_capital: Decimal | None = None

    # ── Financial (net financial position) ────────────────────────
    cash_and_equivalents: Decimal | None = None
    short_term_investments: Decimal | None = None
    financial_debt: Decimal | None = None
    lease_liabilities: Decimal | None = None  # OPERATING, NOT in NFP
    net_financial_position: Decimal | None = None

    # ── Non-operating ─────────────────────────────────────────────
    equity_investments: Decimal | None = None
    associates_jvs: Decimal | None = None
    investment_property: Decimal | None = None
    non_operating_provisions: Decimal | None = None

    # ── Equity ────────────────────────────────────────────────────
    equity_parent: Decimal | None = None
    nci: Decimal | None = None
    total_equity: Decimal | None = None

    # ── Reconciliation ────────────────────────────────────────────
    cross_check_residual: Decimal | None = None
