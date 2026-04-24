"""Phase 2 Sprint 4A-beta — Cash Flow derivation.

Builds one ``CashFlowYear`` from IS + BS inputs following the indirect
method:

- CFO = NI + D&A − ΔWC
- CFI = −capex − M&A deployment
- CFF = −dividends − buybacks + (debt_issued − debt_repaid) − after-tax interest
- Δcash = CFO + CFI + CFF + fx_effect (enforced by the schema validator)
"""

from __future__ import annotations

from decimal import Decimal

from portfolio_thesis_engine.forecast.schemas import CashFlowYear


def _as_outflow(value: Decimal) -> Decimal:
    """Return a non-positive outflow representation.

    Callers may pass either positive magnitudes (``capex = 10_000``) or
    pre-signed values (``capex = -10_000``). Normalize to CFI/CFF sign
    convention where outflows are negative.
    """
    return -value if value > 0 else value


def derive_cash_flow(
    *,
    net_income: Decimal,
    da: Decimal,
    wc_change: Decimal,
    capex: Decimal,
    ma_deployment: Decimal,
    dividends_paid: Decimal,
    buybacks_executed: Decimal,
    debt_issued: Decimal,
    debt_repaid: Decimal,
    net_interest: Decimal,
    tax_rate: Decimal,
    year: int,
    fx_effect: Decimal = Decimal("0"),
) -> CashFlowYear:
    """Derive a single-year cash flow record from the upstream inputs."""
    cfo = net_income + da - wc_change

    capex_signed = _as_outflow(capex)
    ma_signed = _as_outflow(ma_deployment)
    cfi = capex_signed + ma_signed

    dividends_signed = _as_outflow(dividends_paid)
    buybacks_signed = _as_outflow(buybacks_executed)
    debt_net = debt_issued - debt_repaid
    after_tax_interest = net_interest * (Decimal("1") - tax_rate)

    cff = dividends_signed + buybacks_signed + debt_net - after_tax_interest

    net_change_cash = cfo + cfi + cff + fx_effect

    return CashFlowYear(
        year=year,
        cfo=cfo,
        cfi=cfi,
        cff=cff,
        capex=capex_signed,
        ma_deployment=ma_signed,
        dividends_paid=dividends_signed,
        buybacks_executed=buybacks_signed,
        debt_issued=debt_issued,
        debt_repaid=debt_repaid,
        net_interest=after_tax_interest,
        fx_effect=fx_effect,
        net_change_cash=net_change_cash,
    )


__all__ = ["derive_cash_flow"]
