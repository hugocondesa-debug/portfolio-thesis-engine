"""FCFF DCF engine — three-scenario, mid-year-discounted.

Projection walk (per year ``i`` in ``1..N``):

1. **Revenue(i) = Revenue(i-1) × (1 + revenue_cagr)** where
   ``revenue_cagr`` is the scenario driver for the explicit period.
2. **Operating margin(i)** linearly interpolates from the base-year
   margin to ``terminal_operating_margin`` over ``N`` years. This
   lets the model capture margin mean-reversion without asking the
   analyst for a per-year margin curve.
3. **EBITDA(i) = Revenue(i) × margin(i)**. (Phase 1 treats operating
   margin as the EBITDA margin; when the extractor splits D from A,
   Phase 2 can use EBITA here instead.)
4. **Operating taxes(i) = EBITDA(i) × operating_tax_rate**, where the
   rate comes from the Canonical state's Module A.1 adjustment (or
   its `NOPATBridge.operating_taxes / ebitda` ratio as fallback).
5. **NOPAT(i) = EBITDA(i) − Operating taxes(i)**. (Strictly EBITDA−
   taxes is *not* NOPAT — true NOPAT = EBIT−taxes. For Phase 1 we
   accept EBITDA-based NOPAT as the cash-flow proxy: the CapEx line
   below already handles reinvestment.)
6. **Reinvestment(i) = CapEx(i) + ΔWC(i) − D&A(i)**.
   - CapEx: base-year CapEx / Revenue ratio held constant and applied
     to projected revenue.
   - ΔWC: assumed 0 % of revenue change (conservative; Phase 2 wires
     the DSO/DPO/DIO from ratios).
   - D&A: held at the base-year D&A / Revenue ratio.
7. **FCFF(i) = NOPAT(i) − Reinvestment(i)**.

Terminal:

- **FCFF_{N+1} = FCFF_N × (1 + g_terminal)**
- **TV = FCFF_{N+1} / (WACC − g_terminal)**

Discounting uses the **mid-year convention**: year ``i`` (1-indexed)
discounts at exponent ``i − 0.5``; TV discounts at ``N``. The
convention reflects that FCFF accrues through the year rather than
arriving in a single year-end lump.
"""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

from portfolio_thesis_engine.schemas.company import CanonicalCompanyState
from portfolio_thesis_engine.schemas.valuation import Scenario
from portfolio_thesis_engine.valuation.base import DCFResult, ValuationEngine

_ONE = Decimal("1")
_HUNDRED = Decimal("100")

# Phase 1.5.8 — label patterns for base-year lookups. Matches the same
# regex conventions used by the validator, AnalysisDeriver, and the
# pipeline coordinator's cross-check helpers.
_REVENUE_LABEL = re.compile(
    r"^revenue$|^total revenue$|^sales$|^turnover$", re.IGNORECASE
)
_OPERATING_INCOME_LABEL = re.compile(
    r"^operating (profit|income)$|^profit from operations",
    re.IGNORECASE,
)
_CAPEX_LABEL = re.compile(
    r"purchas[ae]s? of (property|plant|equipment|intangib)|"
    r"capital expenditure|additions? to (property|ppe|intangib)",
    re.IGNORECASE,
)


class FCFFDCFEngine(ValuationEngine):
    """Three-scenario FCFF DCF with mid-year discounting."""

    def __init__(self, n_years: int = 10) -> None:
        if n_years < 1 or n_years > 25:
            raise ValueError(f"n_years must be in [1, 25], got {n_years}")
        self.n_years = n_years

    # ------------------------------------------------------------------
    # Public
    # ------------------------------------------------------------------
    def compute_target(
        self,
        scenario: Scenario,
        wacc_pct: Decimal,
        canonical_state: CanonicalCompanyState,
    ) -> DCFResult:
        """Project, terminal-value, discount. Returns :class:`DCFResult`."""
        projected, projection_detail = self.project_fcff(scenario, canonical_state)
        terminal = self.compute_terminal(projected[-1], scenario, wacc_pct)
        pv_explicit, pv_terminal = self.compute_ev(projected, terminal, wacc_pct)

        return DCFResult(
            enterprise_value=pv_explicit + pv_terminal,
            pv_explicit=pv_explicit,
            pv_terminal=pv_terminal,
            terminal_value=terminal,
            wacc_used=wacc_pct,
            implied_g=scenario.drivers.terminal_growth or Decimal("0"),
            projected_fcff=tuple(projected),
            n_years=self.n_years,
            projection_detail=projection_detail,
        )

    # ------------------------------------------------------------------
    def project_fcff(
        self,
        scenario: Scenario,
        canonical_state: CanonicalCompanyState,
    ) -> tuple[list[Decimal], dict[int, dict[str, Decimal]]]:
        """Return ``(list[FCFF per year], detail by year)``."""
        base = self._extract_base_year(canonical_state)

        cagr = self._pct_to_fraction(scenario.drivers.revenue_cagr)
        terminal_margin = self._pct_to_fraction(scenario.drivers.terminal_margin)
        tax_rate = base["operating_tax_rate_fraction"]

        base_margin = base["base_operating_margin_fraction"]
        capex_ratio = base["capex_to_revenue_fraction"]
        da_ratio = base["da_to_revenue_fraction"]

        projected: list[Decimal] = []
        detail: dict[int, dict[str, Decimal]] = {}
        revenue_prev = base["base_revenue"]

        for i in range(1, self.n_years + 1):
            revenue = revenue_prev * (_ONE + cagr)
            # Linear interpolation from base_margin to terminal_margin
            # over ``n_years`` — year 1 is the first step.
            interp = Decimal(i) / Decimal(self.n_years)
            margin = base_margin + (terminal_margin - base_margin) * interp

            ebitda = revenue * margin
            taxes = ebitda * tax_rate
            nopat = ebitda - taxes

            capex = revenue * capex_ratio
            d_and_a = revenue * da_ratio
            # Working-capital change: Phase 1 assumption is that
            # incremental WC is negligible; leaves the fraction at 0.
            # Phase 2 pulls DSO/DPO/DIO from KeyRatios to refine.
            wc_change = Decimal("0")
            reinvestment = capex + wc_change - d_and_a

            fcff = nopat - reinvestment
            projected.append(fcff)
            detail[i] = {
                "revenue": revenue,
                "margin": margin,
                "ebitda": ebitda,
                "taxes": taxes,
                "nopat": nopat,
                "capex": capex,
                "d_and_a": d_and_a,
                "wc_change": wc_change,
                "reinvestment": reinvestment,
                "fcff": fcff,
            }
            revenue_prev = revenue

        return projected, detail

    # ------------------------------------------------------------------
    def compute_terminal(
        self,
        fcff_last_year: Decimal,
        scenario: Scenario,
        wacc_pct: Decimal,
    ) -> Decimal:
        """Gordon-growth TV at year N.

        ``TV = FCFF_{N+1} / (WACC − g)`` where g = ``terminal_growth``.
        Raises :class:`ValueError` if ``WACC ≤ g`` — Gordon is
        mathematically undefined in that regime.
        """
        g_frac = self._pct_to_fraction(scenario.drivers.terminal_growth)
        wacc_frac = wacc_pct / _HUNDRED
        if wacc_frac <= g_frac:
            raise ValueError(
                f"Terminal WACC ({wacc_pct}%) must exceed terminal growth "
                f"({scenario.drivers.terminal_growth}%) for Gordon growth."
            )
        fcff_next = fcff_last_year * (_ONE + g_frac)
        return fcff_next / (wacc_frac - g_frac)

    # ------------------------------------------------------------------
    def compute_ev(
        self,
        projected_fcff: list[Decimal],
        terminal_value: Decimal,
        wacc_pct: Decimal,
    ) -> tuple[Decimal, Decimal]:
        """Return ``(pv_explicit, pv_terminal)`` with mid-year discounting.

        Year ``i`` (1-indexed) discounts at exponent ``i − 0.5``; the
        terminal value discounts at ``N`` (year-end convention, since
        TV itself represents a perpetuity starting at year ``N+1``).
        """
        wacc_frac = wacc_pct / _HUNDRED
        one_plus = _ONE + wacc_frac

        pv_explicit = Decimal("0")
        for i, fcff in enumerate(projected_fcff, start=1):
            # Decimal ** non-integer power is not supported directly;
            # use log-based pow on float for the fractional exponent,
            # then cast back. Precision loss is negligible for DCF.
            exponent = Decimal(i) - Decimal("0.5")
            discount = Decimal(str(float(one_plus) ** float(exponent)))
            pv_explicit += fcff / discount

        n = len(projected_fcff)
        discount_tv = Decimal(str(float(one_plus) ** n))
        pv_terminal = terminal_value / discount_tv

        return pv_explicit, pv_terminal

    # ------------------------------------------------------------------
    # Inputs
    # ------------------------------------------------------------------
    def _extract_base_year(
        self, canonical_state: CanonicalCompanyState
    ) -> dict[str, Decimal]:
        """Pull the base-year revenue, margin, capex/revenue, D&A/revenue,
        and operating tax rate off the canonical state.

        Phase 1.5.8: label lookups use **regex patterns** instead of
        exact-string / Phase-1 category matches. Previous code read
        category=="capex" (Phase-1 convention) and label=="Operating
        income" (US-GAAP style); the Phase-1.5.3 coordinator passes
        categories from sections ("investing"/"operating"/etc.) and
        IFRS filings report "Operating profit", "Purchases of property
        plant and equipment" etc. The exact-string lookups silently
        returned 0, collapsing CapEx to 0 and margin to 0 → FCFF
        inflated by the full D&A addback → EV multiplied 3-4×.

        Falls back to ``0`` for ratios when denominators are missing so
        the engine never divides-by-zero. An all-zero base produces an
        all-zero projection, which the composer surfaces as a WARN.
        """
        rs_list = canonical_state.reclassified_statements
        if not rs_list:
            raise ValueError(
                "DCF requires at least one period on "
                "canonical_state.reclassified_statements"
            )
        rs = rs_list[0]

        # Revenue.
        revenue = _sum_by_regex(rs.income_statement, _REVENUE_LABEL)

        # Operating income / profit.
        operating_income = _sum_by_regex(
            rs.income_statement, _OPERATING_INCOME_LABEL
        )
        base_margin = _safe_frac(operating_income, revenue)

        # CapEx — CF line whose label matches the purchase-of-PPE
        # pattern. Absolute value since CF reports outflows as
        # negative.
        capex = abs(_sum_by_regex(rs.cash_flow, _CAPEX_LABEL))
        capex_ratio = _safe_frac(capex, revenue)

        # D&A: the NOPAT bridge carries EBITDA = operating_income +
        # |D&A|. Backing out D&A from that is equivalent to reading
        # the PP&E and Intangibles notes the AnalysisDeriver already
        # walked in Phase 1.5.6.
        bridge_list = canonical_state.analysis.nopat_bridge_by_period
        if bridge_list:
            bridge = bridge_list[0]
            da_absolute = bridge.ebitda - operating_income
            if da_absolute < 0:
                da_absolute = Decimal("0")
            da_ratio = _safe_frac(da_absolute, revenue)
        else:
            da_ratio = Decimal("0")

        # Operating tax rate: prefer A.1 adjustment, otherwise bridge ratio.
        tax_rate = _operating_tax_rate(canonical_state)

        return {
            "base_revenue": revenue,
            "base_operating_margin_fraction": base_margin,
            "capex_to_revenue_fraction": capex_ratio,
            "da_to_revenue_fraction": da_ratio,
            "operating_tax_rate_fraction": tax_rate,
        }

    # ------------------------------------------------------------------
    def _pct_to_fraction(self, value: Decimal | None) -> Decimal:
        """Convert an optional percentage driver to a decimal fraction."""
        if value is None:
            return Decimal("0")
        return value / _HUNDRED

    # ------------------------------------------------------------------
    def describe(self) -> dict[str, Any]:
        return {"engine": "FCFFDCFEngine", "n_years": self.n_years}


# ----------------------------------------------------------------------
# Helpers (module-level so unit tests can import them directly)
# ----------------------------------------------------------------------
def _sum_by_label(lines, label_lower_match: str) -> Decimal:  # type: ignore[no-untyped-def]
    target = label_lower_match.strip().lower()
    total = Decimal("0")
    for ln in lines:
        if ln.label.strip().lower() == target:
            total += ln.value
    return total


def _sum_by_regex(  # type: ignore[no-untyped-def]
    lines, pattern: re.Pattern[str]
) -> Decimal:
    """Phase 1.5.8: sum line values whose label matches ``pattern``."""
    total = Decimal("0")
    for ln in lines:
        if pattern.search(ln.label):
            total += ln.value
    return total


def _sum_by_category(lines, category: str) -> Decimal:  # type: ignore[no-untyped-def]
    return sum((ln.value for ln in lines if ln.category == category), start=Decimal("0"))


def _safe_frac(num: Decimal, den: Decimal) -> Decimal:
    if den == 0:
        return Decimal("0")
    return num / den


def _operating_tax_rate(canonical_state: CanonicalCompanyState) -> Decimal:
    """Return the operating tax rate as a decimal fraction.

    Precedence: Module A.1 adjustment (the extraction engine's
    canonical rate) → NOPATBridge implied rate (operating_taxes /
    anchor) → 0.
    """
    for adj in canonical_state.adjustments.module_a_taxes:
        if adj.module == "A.1":
            return adj.amount / _HUNDRED
    bridge_list = canonical_state.analysis.nopat_bridge_by_period
    if bridge_list:
        bridge = bridge_list[0]
        anchor = bridge.ebita if bridge.ebita is not None else bridge.ebitda
        if anchor != 0:
            return abs(bridge.operating_taxes) / anchor
    return Decimal("0")
