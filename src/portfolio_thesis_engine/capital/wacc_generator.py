"""Phase 2 Sprint 3 — :class:`WACCGenerator`.

Composes a :class:`WACCComputation` following Damodaran's framework:

1. **Currency regime detection** — DEVELOPED when the listing currency's
   inflation differential vs USD is under 3 pp. HIGH_INFLATION pushes
   CAPM into USD space, converts back using Fisher (differential
   inflation) at the end.
2. **Bottom-up levered beta** — industry unlevered β from the
   Damodaran table × ``(1 + (1 − t) × D/E)``.
3. **Weighted CRP** — revenue geography weights × country CRP; falls
   back to listing-country CRP when no geography is supplied.
4. **Cost of debt** — interest-coverage → synthetic rating → spread.
   Zero-debt companies short-circuit with ``is_applicable = False``.
5. **WACC** — ``E/V × CoE + D/V × CoD_aftertax``.

The narrative audit trail is assembled inline so the CLI can print a
single ready-to-read paragraph per run.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from portfolio_thesis_engine.reference import DamodaranReference
from portfolio_thesis_engine.schemas.cost_of_capital import (
    CostOfDebtInputs,
    CostOfEquityInputs,
    WACCComputation,
)


_INFLATION_DIFFERENTIAL_THRESHOLD = Decimal("0.03")  # 3 pp
_BPS = Decimal("10000")


@dataclass
class GeographyWeight:
    """One revenue-geography weight entry used to aggregate the CRP."""

    country: str
    weight: Decimal  # 0-1; must sum to 1 across the list


@dataclass
class WACCGeneratorInputs:
    """All the per-ticker inputs that can't be read from Damodaran
    tables — industry slug, domicile, capital structure, and optional
    revenue geography. Leave ``revenue_geography`` empty to fall back
    to pure listing-country CRP."""

    target_ticker: str
    listing_currency: str
    country_domicile: str
    industry_key: str
    debt_to_equity: Decimal = Decimal("0")
    marginal_tax_rate: Decimal = Decimal("0.25")
    revenue_geography: list[GeographyWeight] = field(default_factory=list)

    ebit: Decimal | None = None
    interest_expense: Decimal | None = None

    equity_market_value: Decimal | None = None
    debt_book_value: Decimal = Decimal("0")

    manual_wacc: Decimal | None = None  # For audit comparison


class WACCGenerator:
    def __init__(
        self, reference: DamodaranReference | None = None
    ) -> None:
        self.reference = reference or DamodaranReference()

    # ------------------------------------------------------------------
    def generate(self, inputs: WACCGeneratorInputs) -> WACCComputation:
        coe = self._build_coe(inputs)
        cod = self._build_cod(inputs, coe.risk_free_rate)
        equity_weight, debt_weight = self._capital_weights(inputs)
        wacc = (equity_weight * coe.cost_of_equity_final) + (
            debt_weight
            * (cod.cost_of_debt_aftertax if cod.is_applicable else Decimal("0"))
        )

        manual_delta_bps = None
        if inputs.manual_wacc is not None:
            manual_delta_bps = int(
                ((wacc - inputs.manual_wacc) * _BPS).to_integral_value()
            )

        narrative = self._build_narrative(coe, cod, equity_weight, debt_weight, wacc)

        return WACCComputation(
            target_ticker=inputs.target_ticker,
            base_currency=inputs.listing_currency,
            cost_of_equity=coe,
            cost_of_debt=cod,
            equity_market_value=inputs.equity_market_value,
            debt_book_value=inputs.debt_book_value,
            total_value=(
                (inputs.equity_market_value or Decimal("0"))
                + inputs.debt_book_value
            ) or None,
            equity_weight=equity_weight,
            debt_weight=debt_weight,
            wacc=wacc,
            wacc_audit_narrative=narrative,
            manual_wacc=inputs.manual_wacc,
            manual_vs_computed_bps=manual_delta_bps,
        )

    # ------------------------------------------------------------------
    # Cost of equity
    # ------------------------------------------------------------------
    def _build_coe(
        self, inputs: WACCGeneratorInputs
    ) -> CostOfEquityInputs:
        currency = inputs.listing_currency
        rf = self.reference.risk_free_rate(currency)
        if rf is None:
            raise ValueError(
                f"No risk-free rate tabulated for currency '{currency}'"
            )
        rf_source = f"damodaran_rf_table::{currency}"

        unlevered = self.reference.industry_unlevered_beta(inputs.industry_key)
        if unlevered is None:
            raise ValueError(
                f"No industry beta tabulated for '{inputs.industry_key}'"
            )
        levered = unlevered * (
            Decimal("1")
            + (Decimal("1") - inputs.marginal_tax_rate) * inputs.debt_to_equity
        )

        mature_erp = self.reference.mature_market_erp()

        # CRP — weighted by revenue geography when provided; fallback to
        # the listing country.
        geography_weights: dict[str, Decimal] = {}
        country_crp: dict[str, Decimal] = {}
        if inputs.revenue_geography:
            total_weight = sum(
                (g.weight for g in inputs.revenue_geography),
                start=Decimal("0"),
            )
            if abs(total_weight - Decimal("1")) > Decimal("0.01"):
                raise ValueError(
                    f"revenue_geography weights sum to {total_weight}; "
                    "expected 1.00 ± 0.01"
                )
            weighted_crp = Decimal("0")
            for entry in inputs.revenue_geography:
                crp = self.reference.country_crp(entry.country) or Decimal("0")
                geography_weights[entry.country] = entry.weight
                country_crp[entry.country] = crp
                weighted_crp += entry.weight * crp
        else:
            crp = self.reference.country_crp(inputs.country_domicile) or Decimal("0")
            geography_weights[inputs.country_domicile] = Decimal("1")
            country_crp[inputs.country_domicile] = crp
            weighted_crp = crp

        inflation_local = self.reference.inflation_rate(currency)
        inflation_us = self.reference.inflation_rate("USD") or Decimal("0.024")

        differential = None
        regime = "DEVELOPED"
        requires_conversion = False
        if inflation_local is not None:
            differential = abs(inflation_local - inflation_us)
            if differential >= _INFLATION_DIFFERENTIAL_THRESHOLD:
                regime = "HIGH_INFLATION"
                requires_conversion = True

        # DEVELOPED path: CoE = Rf + β × (ERP + CRP)
        coe_base = rf + levered * (mature_erp + weighted_crp)

        if requires_conversion and inflation_local is not None:
            rf_us = self.reference.risk_free_rate("USD") or Decimal("0.04")
            coe_usd = rf_us + levered * (mature_erp + weighted_crp)
            # Fisher: (1 + r_local) = (1 + r_usd) × (1 + π_local) / (1 + π_us)
            coe_final = (
                (Decimal("1") + coe_usd)
                * (Decimal("1") + inflation_local)
                / (Decimal("1") + inflation_us)
            ) - Decimal("1")
        else:
            coe_final = coe_base

        return CostOfEquityInputs(
            target_ticker=inputs.target_ticker,
            listing_currency=currency,
            risk_free_rate=rf,
            risk_free_source=rf_source,
            industry_key=inputs.industry_key,
            industry_unlevered_beta=unlevered,
            debt_to_equity=inputs.debt_to_equity,
            marginal_tax_rate=inputs.marginal_tax_rate,
            levered_beta=levered,
            mature_market_erp=mature_erp,
            revenue_geography=geography_weights,
            country_crp=country_crp,
            weighted_crp=weighted_crp,
            inflation_local=inflation_local,
            inflation_us=inflation_us,
            inflation_differential_abs=differential,
            currency_regime=regime,  # type: ignore[arg-type]
            requires_usd_conversion=requires_conversion,
            cost_of_equity_base=coe_base,
            cost_of_equity_final=coe_final,
        )

    # ------------------------------------------------------------------
    # Cost of debt
    # ------------------------------------------------------------------
    def _build_cod(
        self, inputs: WACCGeneratorInputs, rf: Decimal
    ) -> CostOfDebtInputs:
        if inputs.debt_to_equity == 0 and inputs.debt_book_value == 0:
            return CostOfDebtInputs(
                target_ticker=inputs.target_ticker,
                listing_currency=inputs.listing_currency,
                risk_free_rate=rf,
                ebit=inputs.ebit,
                interest_expense=inputs.interest_expense,
                marginal_tax_rate=inputs.marginal_tax_rate,
                is_applicable=False,
                rationale=(
                    "Zero financial debt in capital structure — CoD not "
                    "applicable; WACC reduces to cost of equity."
                ),
            )
        if inputs.ebit is None or inputs.interest_expense in (None, Decimal("0")):
            return CostOfDebtInputs(
                target_ticker=inputs.target_ticker,
                listing_currency=inputs.listing_currency,
                risk_free_rate=rf,
                ebit=inputs.ebit,
                interest_expense=inputs.interest_expense,
                marginal_tax_rate=inputs.marginal_tax_rate,
                is_applicable=False,
                rationale=(
                    "Interest coverage not computable (EBIT or interest "
                    "expense missing) — CoD fallback skipped."
                ),
            )
        coverage = inputs.ebit / abs(inputs.interest_expense)
        rating, spread = self.reference.synthetic_rating_for_coverage(coverage)
        cod_pretax = rf + spread
        cod_aftertax = cod_pretax * (Decimal("1") - inputs.marginal_tax_rate)
        return CostOfDebtInputs(
            target_ticker=inputs.target_ticker,
            listing_currency=inputs.listing_currency,
            risk_free_rate=rf,
            ebit=inputs.ebit,
            interest_expense=inputs.interest_expense,
            interest_coverage_ratio=coverage,
            synthetic_rating=rating,
            rating_spread=spread,
            cost_of_debt_pretax=cod_pretax,
            marginal_tax_rate=inputs.marginal_tax_rate,
            cost_of_debt_aftertax=cod_aftertax,
            is_applicable=True,
            rationale=(
                f"Interest coverage {coverage:.2f}× → synthetic "
                f"{rating} rating (+{spread * 10000:.0f} bps)."
            ),
        )

    # ------------------------------------------------------------------
    def _capital_weights(
        self, inputs: WACCGeneratorInputs
    ) -> tuple[Decimal, Decimal]:
        e = inputs.equity_market_value
        d = inputs.debt_book_value
        if e is None:
            # Fall back to D/E ratio for weights when market cap absent.
            if inputs.debt_to_equity == 0:
                return Decimal("1"), Decimal("0")
            total = Decimal("1") + inputs.debt_to_equity
            return Decimal("1") / total, inputs.debt_to_equity / total
        total = e + d
        if total == 0:
            return Decimal("1"), Decimal("0")
        return e / total, d / total

    # ------------------------------------------------------------------
    def _build_narrative(
        self,
        coe: CostOfEquityInputs,
        cod: CostOfDebtInputs,
        equity_weight: Decimal,
        debt_weight: Decimal,
        wacc: Decimal,
    ) -> str:
        parts = [
            f"Currency regime: {coe.currency_regime}.",
            f"Rf {coe.risk_free_rate:.4f} ({coe.risk_free_source}).",
            (
                f"Bottom-up β: unlevered {coe.industry_unlevered_beta:.2f} "
                f"× (1 + (1 − {coe.marginal_tax_rate:.2f}) × "
                f"{coe.debt_to_equity:.2f}) = levered {coe.levered_beta:.2f}."
            ),
            (
                f"ERP {coe.mature_market_erp:.4f} + weighted CRP "
                f"{coe.weighted_crp:.4f} = total equity premium "
                f"{coe.mature_market_erp + coe.weighted_crp:.4f}."
            ),
            f"CoE = {coe.cost_of_equity_final:.4f}.",
        ]
        if cod.is_applicable and cod.cost_of_debt_aftertax is not None:
            parts.append(
                f"CoD pretax {cod.cost_of_debt_pretax:.4f} → after-tax "
                f"{cod.cost_of_debt_aftertax:.4f} ({cod.synthetic_rating})."
            )
        else:
            parts.append("CoD: not applicable (zero financial debt).")
        parts.append(
            f"Weights: equity {equity_weight:.2f}, debt {debt_weight:.2f} "
            f"→ WACC = {wacc:.4f}."
        )
        return " ".join(parts)


__all__ = ["GeographyWeight", "WACCGenerator", "WACCGeneratorInputs"]
