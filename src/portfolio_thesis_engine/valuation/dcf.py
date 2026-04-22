"""FCFF DCF engine — three-scenario, mid-year-discounted, EBITA basis.

Projection walk (per year ``i`` in ``1..N``):

1. **Revenue(i) = Revenue(i-1) × (1 + revenue_cagr)** where
   ``revenue_cagr`` is the scenario driver for the explicit period.
2. **Operating margin(i)** linearly interpolates from the base-year
   **sustainable** operating margin to ``terminal_operating_margin``
   over ``N`` years. The sustainable base strips non-recurring items
   that appear inside reported EBIT (``Other gains, net``, government
   grants, FV remeasurements); the NOPAT bridge persists both
   reported and sustainable values for the audit trail.
3. **EBIT(i) = Revenue(i) × margin(i)**.
4. **Amortisation(i) = Revenue(i) × amortisation_ratio** (base-year
   ratio held constant). When the canonical extraction can't isolate
   amortisation from depreciation, the ratio is ``0``.
5. **EBITA(i) = EBIT(i) + Amortisation(i)**.
6. **Operating taxes(i) = EBITA(i) × operating_tax_rate**, rate from
   Module A.1 adjustment (or :class:`NOPATBridge` implied rate as
   fallback).
7. **NOPAT(i) = EBITA(i) × (1 − t)**. Phase 1.5.9 moves the NOPAT
   anchor from EBIT to EBITA so operational amortisation flows
   through as a real expense (its tax shield sits inside NOPAT);
   depreciation stays non-cash and is added back in FCFF.
8. **FCFF(i) = NOPAT(i) + Depreciation(i) − CapEx(i) − ΔWC(i)**.
   Depreciation — not full D&A — is the add-back. ΔWC stays at 0 in
   Phase 1 (Phase 2 wires DSO/DPO/DIO from ratios).

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
from portfolio_thesis_engine.schemas.valuation import (
    EquityBridgeDetail,
    EVBreakdown,
    MarketSnapshot,
    ProjectionYear,
    Scenario,
    SensitivityGrid,
    TerminalProjection,
)
from portfolio_thesis_engine.valuation.base import (
    DCFResult,
    ValuationEngine,
    ValuationResult,
)

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
        # Phase 1.5.9: separate depreciation from amortisation. Amort
        # feeds EBITA; depreciation is the FCFF add-back.
        dep_ratio = base["depreciation_to_revenue_fraction"]
        amort_ratio = base["amortisation_to_revenue_fraction"]
        # Phase 1.5.9.1: WC at constant revenue ratio; ΔWC = WC_y − WC_{y-1}.
        wc_ratio = base["wc_to_revenue_fraction"]
        wc_prev = base["base_operating_working_capital"]

        projected: list[Decimal] = []
        detail: dict[int, dict[str, Decimal]] = {}
        revenue_prev = base["base_revenue"]

        for i in range(1, self.n_years + 1):
            revenue = revenue_prev * (_ONE + cagr)
            # Linear interpolation from base_margin (sustainable) to
            # terminal_margin over ``n_years`` — year 1 is the first step.
            interp = Decimal(i) / Decimal(self.n_years)
            margin = base_margin + (terminal_margin - base_margin) * interp

            ebit = revenue * margin
            amortisation = revenue * amort_ratio
            ebita = ebit + amortisation
            taxes = ebita * tax_rate
            nopat = ebita - taxes

            capex = revenue * capex_ratio
            depreciation = revenue * dep_ratio
            # Working-capital change at constant revenue ratio.
            # Positive ΔWC reduces FCFF (cash tied up in receivables /
            # inventory growth).
            wc_current = revenue * wc_ratio
            wc_change = wc_current - wc_prev

            # FCFF = NOPAT + Depreciation − CapEx − ΔWC. Amortisation is
            # NOT added back — it's already captured inside NOPAT via
            # the EBITA anchor.
            fcff = nopat + depreciation - capex - wc_change
            projected.append(fcff)
            detail[i] = {
                "revenue": revenue,
                "margin": margin,
                "ebit": ebit,
                "amortisation": amortisation,
                "ebita": ebita,
                "taxes": taxes,
                "nopat": nopat,
                "capex": capex,
                "depreciation": depreciation,
                "wc_change": wc_change,
                "fcff": fcff,
            }
            revenue_prev = revenue
            wc_prev = wc_current

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

        # Operating income / profit — reported. Sustainable income (if
        # the analysis layer detected non-recurring items) wins for the
        # forward projection base.
        reported_oi = _sum_by_regex(
            rs.income_statement, _OPERATING_INCOME_LABEL
        )
        bridge_list = canonical_state.analysis.nopat_bridge_by_period
        sustainable_oi: Decimal | None = None
        if bridge_list and bridge_list[0].operating_income_sustainable is not None:
            sustainable_oi = bridge_list[0].operating_income_sustainable
        base_oi = sustainable_oi if sustainable_oi is not None else reported_oi
        base_margin = _safe_frac(base_oi, revenue)
        reported_margin = _safe_frac(reported_oi, revenue)

        # CapEx — CF line whose label matches the purchase-of-PPE
        # pattern. Absolute value since CF reports outflows as
        # negative.
        capex = abs(_sum_by_regex(rs.cash_flow, _CAPEX_LABEL))
        capex_ratio = _safe_frac(capex, revenue)

        # Phase 1.5.9 — separate depreciation from amortisation so the
        # projection can build EBITA (EBIT + A) and FCFF (NOPAT + D).
        # Source of truth: :class:`NOPATBridge.depreciation` /
        # ``.amortisation``, populated by the AnalysisDeriver from the
        # PP&E + intangibles notes.
        if bridge_list:
            bridge = bridge_list[0]
            depreciation = bridge.depreciation or Decimal("0")
            amortisation = bridge.amortisation or Decimal("0")
        else:
            depreciation = Decimal("0")
            amortisation = Decimal("0")
        dep_ratio = _safe_frac(depreciation, revenue)
        amort_ratio = _safe_frac(amortisation, revenue)
        da_ratio = _safe_frac(depreciation + amortisation, revenue)

        # Phase 1.5.9.1 — operating working capital as % of revenue.
        # Projection holds the ratio constant; per-year ΔWC = WC_y −
        # WC_{y-1} flows into FCFF. Phase 2 refines via DSO/DPO/DIO.
        ic_list = canonical_state.analysis.invested_capital_by_period
        operating_wc = (
            ic_list[0].operating_working_capital if ic_list else Decimal("0")
        )
        wc_ratio = _safe_frac(operating_wc, revenue)

        # Operating tax rate: prefer A.1 adjustment, otherwise bridge ratio.
        tax_rate = _operating_tax_rate(canonical_state)

        return {
            "base_revenue": revenue,
            "base_operating_margin_fraction": base_margin,
            "reported_operating_margin_fraction": reported_margin,
            "base_operating_income": base_oi,
            "reported_operating_income": reported_oi,
            "capex_to_revenue_fraction": capex_ratio,
            "depreciation_to_revenue_fraction": dep_ratio,
            "amortisation_to_revenue_fraction": amort_ratio,
            "da_to_revenue_fraction": da_ratio,
            "wc_to_revenue_fraction": wc_ratio,
            "base_operating_working_capital": operating_wc,
            "operating_tax_rate_fraction": tax_rate,
        }

    # ------------------------------------------------------------------
    def _pct_to_fraction(self, value: Decimal | None) -> Decimal:
        """Convert an optional percentage driver to a decimal fraction."""
        if value is None:
            return Decimal("0")
        return value / _HUNDRED

    # ------------------------------------------------------------------
    def base_year_schedule(
        self, canonical_state: CanonicalCompanyState
    ) -> dict[str, Decimal]:
        """Return the year-0 intermediates (revenue, OI reported +
        sustainable, CapEx, D, A, tax rate) — used by the composer to
        persist the projection schedule's base row."""
        return self._extract_base_year(canonical_state)

    # ------------------------------------------------------------------
    def compute(
        self,
        canonical_state: CanonicalCompanyState,
        scenario: Scenario,
        market: MarketSnapshot,
    ) -> ValuationResult:
        """Phase 1.5.9 top-level protocol entry point.

        Runs the full FCFF chain (project → terminal → discount →
        equity bridge) and assembles a :class:`ValuationResult` with
        the projection schedule + terminal block + EV breakdown +
        equity bridge + sensitivity grids. The pipeline calls this via
        :class:`~portfolio_thesis_engine.valuation.dispatcher.ValuationDispatcher`.
        """
        # Late import to avoid circular.
        from portfolio_thesis_engine.valuation.equity_bridge import EquityBridge

        wacc_pct = (
            market.wacc
            if market.wacc is not None
            else Decimal("8")  # conservative default
        )
        equity_bridge = EquityBridge()
        dcf = self.compute_target(
            scenario=scenario,
            wacc_pct=wacc_pct,
            canonical_state=canonical_state,
        )
        equity = equity_bridge.compute(dcf, canonical_state)

        projection = self._build_projection_schedule(
            canonical_state=canonical_state,
            dcf=dcf,
            wacc_pct=wacc_pct,
        )
        terminal = self._build_terminal_block(
            scenario=scenario, dcf=dcf, wacc_pct=wacc_pct
        )
        ev_breakdown = EVBreakdown(
            sum_pv_explicit=dcf.pv_explicit,
            pv_terminal=dcf.pv_terminal,
            total_ev=dcf.enterprise_value,
        )
        eq_bridge = _build_equity_bridge_detail(
            equity=equity, canonical_state=canonical_state
        )
        sensitivity_grids = [
            _grid_to_schema(
                self.compute_wacc_g_grid(
                    scenario=scenario,
                    canonical_state=canonical_state,
                    base_wacc_pct=wacc_pct,
                    equity_bridge_fn=equity_bridge.compute,
                ),
                scenario_label=scenario.label,
                axis_x="wacc",
                axis_y="terminal_growth",
            ),
            _grid_to_schema(
                self.compute_cagr_margin_grid(
                    scenario=scenario,
                    canonical_state=canonical_state,
                    wacc_pct=wacc_pct,
                    equity_bridge_fn=equity_bridge.compute,
                ),
                scenario_label=scenario.label,
                axis_x="revenue_cagr",
                axis_y="terminal_margin",
            ),
        ]

        bridge_list = canonical_state.analysis.nopat_bridge_by_period
        nopat_methodology = (
            bridge_list[0].nopat_methodology
            if bridge_list
            else "ebit_based_no_amort_detected"
        )
        methodology = {
            "engine": "FCFFDCFEngine",
            "n_years": self.n_years,
            "wacc_pct": str(wacc_pct),
            "nopat_methodology": nopat_methodology,
            "fcff_formula": "NOPAT + Depreciation − CapEx − ΔWC",
            "base_margin_source": "sustainable" if _has_non_recurring(
                canonical_state
            ) else "reported",
        }

        return ValuationResult(
            projection=projection,
            terminal=terminal,
            enterprise_value_breakdown=ev_breakdown,
            equity_bridge=eq_bridge,
            sensitivity_grids=sensitivity_grids,
            target_per_share=equity.per_share,
            methodology=methodology,
        )

    # ------------------------------------------------------------------
    def _build_projection_schedule(
        self,
        canonical_state: CanonicalCompanyState,
        dcf: DCFResult,
        wacc_pct: Decimal,
    ) -> list[ProjectionYear]:
        """Assemble the projection schedule (year 0..N).

        Phase 1.5.9.1 — Year 0 shows both reported + sustainable margins
        and uses the primary (sustainable when available) as
        ``operating_margin_used`` so the display is internally
        consistent with the NOPAT bridge's primary ``nopat`` and with
        the forward projection (Years 1..N).
        """
        base = self.base_year_schedule(canonical_state)
        tax_rate = base["operating_tax_rate_fraction"]
        reported_margin_pct = (
            base["reported_operating_margin_fraction"] * _HUNDRED
        )
        sustainable_margin_pct = (
            base["base_operating_margin_fraction"] * _HUNDRED
        )
        reported_oi = base["reported_operating_income"]
        primary_oi = base["base_operating_income"]  # sustainable when avail
        base_revenue = base["base_revenue"]

        bridge_list = canonical_state.analysis.nopat_bridge_by_period
        base_amort = (
            bridge_list[0].amortisation if bridge_list else Decimal("0")
        )
        base_dep = (
            bridge_list[0].depreciation if bridge_list else Decimal("0")
        )
        primary_ebita = primary_oi + base_amort
        primary_nopat = primary_ebita * (_ONE - tax_rate)
        base_capex = base["capex_to_revenue_fraction"] * base_revenue
        margin_used_pct = sustainable_margin_pct

        rows: list[ProjectionYear] = [
            ProjectionYear(
                year=0,
                revenue=base_revenue,
                operating_margin_reported=_clip_pct_inline(reported_margin_pct),
                operating_margin_sustainable=(
                    _clip_pct_inline(sustainable_margin_pct)
                    if sustainable_margin_pct != reported_margin_pct
                    else None
                ),
                operating_margin_used=_clip_pct_inline(margin_used_pct),
                ebit=primary_oi,
                amort_for_ebita=base_amort if base_amort > 0 else None,
                ebita=primary_ebita if base_amort > 0 else None,
                nopat=primary_nopat,
                depreciation=base_dep,
                capex=base_capex,
                wc_change=None,
            )
        ]

        wacc_frac = wacc_pct / _HUNDRED
        one_plus = _ONE + wacc_frac
        for idx in sorted(dcf.projection_detail.keys()):
            d = dcf.projection_detail[idx]
            exponent = Decimal(idx) - Decimal("0.5")
            discount_factor = Decimal(str(float(one_plus) ** float(exponent)))
            pv_fcff = (
                d["fcff"] / discount_factor if discount_factor != 0 else Decimal("0")
            )
            rows.append(
                ProjectionYear(
                    year=idx,
                    revenue=d["revenue"],
                    operating_margin_reported=None,
                    operating_margin_sustainable=None,
                    operating_margin_used=_clip_pct_inline(d["margin"] * _HUNDRED),
                    ebit=d["ebit"],
                    amort_for_ebita=(
                        d["amortisation"] if d["amortisation"] > 0 else None
                    ),
                    ebita=d["ebita"] if d["amortisation"] > 0 else None,
                    nopat=d["nopat"],
                    depreciation=d["depreciation"],
                    capex=d["capex"],
                    wc_change=d["wc_change"],
                    fcff=d["fcff"],
                    discount_factor=discount_factor,
                    pv_fcff=pv_fcff,
                )
            )
        return rows

    # ------------------------------------------------------------------
    def _build_terminal_block(
        self,
        scenario: Scenario,
        dcf: DCFResult,
        wacc_pct: Decimal,
    ) -> TerminalProjection | None:
        if not dcf.projection_detail:
            return None
        last = dcf.projection_detail[max(dcf.projection_detail.keys())]
        g_pct = scenario.drivers.terminal_growth or Decimal("0")
        g_frac = g_pct / _HUNDRED
        terminal_fcff = last["fcff"] * (_ONE + g_frac)
        return TerminalProjection(
            revenue_final_year=last["revenue"],
            terminal_growth=_clip_pct_inline(g_pct),
            terminal_margin=_clip_pct_inline(
                scenario.drivers.terminal_margin or Decimal("0")
            ),
            terminal_wacc=_clip_pct_inline(wacc_pct),
            terminal_nopat=last["nopat"],
            terminal_fcff=terminal_fcff,
            terminal_value=dcf.terminal_value,
            pv_terminal=dcf.pv_terminal,
        )

    # ------------------------------------------------------------------
    def compute_wacc_g_grid(
        self,
        scenario: Scenario,
        canonical_state: CanonicalCompanyState,
        base_wacc_pct: Decimal,
        equity_bridge_fn: Any,  # callable: (DCFResult, canonical_state) -> EquityValue
        wacc_deltas_pct: tuple[Decimal, ...] = (
            Decimal("-0.5"),
            Decimal("0"),
            Decimal("0.5"),
        ),
        g_deltas_pct: tuple[Decimal, ...] = (
            Decimal("-0.25"),
            Decimal("0"),
            Decimal("0.25"),
        ),
    ) -> dict[str, Any]:
        """3×3 per-share target grid over ``(WACC, terminal g)``.

        Projection is computed once (independent of WACC/g); each cell
        recomputes terminal value + discounting + equity bridge so the
        target per share reflects the full chain.
        """
        base_g_pct = scenario.drivers.terminal_growth or Decimal("0")
        wacc_pcts = [base_wacc_pct + d for d in wacc_deltas_pct]
        g_pcts = [base_g_pct + d for d in g_deltas_pct]

        projected, _ = self.project_fcff(scenario, canonical_state)

        grid: list[list[Decimal]] = []
        for g_pct in g_pcts:
            row: list[Decimal] = []
            for wacc_pct in wacc_pcts:
                if wacc_pct <= g_pct:
                    row.append(Decimal("0"))
                    continue
                perturbed = scenario.model_copy(
                    update={
                        "drivers": scenario.drivers.model_copy(
                            update={"terminal_growth": g_pct}
                        )
                    }
                )
                tv = self.compute_terminal(projected[-1], perturbed, wacc_pct)
                pv_explicit, pv_terminal = self.compute_ev(projected, tv, wacc_pct)
                ev = pv_explicit + pv_terminal
                dcf = _build_dcf_result(
                    ev, pv_explicit, pv_terminal, tv, wacc_pct, g_pct, projected
                )
                equity = equity_bridge_fn(dcf, canonical_state)
                row.append(equity.per_share or Decimal("0"))
            grid.append(row)

        return {
            "x_values": wacc_pcts,  # WACC on x-axis
            "y_values": g_pcts,     # g on y-axis
            "target_per_share": grid,
            "base_x": base_wacc_pct,
            "base_y": base_g_pct,
        }

    # ------------------------------------------------------------------
    def compute_cagr_margin_grid(
        self,
        scenario: Scenario,
        canonical_state: CanonicalCompanyState,
        wacc_pct: Decimal,
        equity_bridge_fn: Any,
        cagr_deltas_pct: tuple[Decimal, ...] = (
            Decimal("-1"),
            Decimal("0"),
            Decimal("1"),
        ),
        margin_deltas_pct: tuple[Decimal, ...] = (
            Decimal("-1"),
            Decimal("0"),
            Decimal("1"),
        ),
    ) -> dict[str, Any]:
        """3×3 per-share target grid over ``(revenue CAGR, terminal
        margin)``. Each cell recomputes the full projection since both
        CAGR and margin change the revenue / EBIT path."""
        base_cagr = scenario.drivers.revenue_cagr or Decimal("0")
        base_margin = scenario.drivers.terminal_margin or Decimal("0")
        cagr_pcts = [base_cagr + d for d in cagr_deltas_pct]
        margin_pcts = [base_margin + d for d in margin_deltas_pct]

        grid: list[list[Decimal]] = []
        for margin_pct in margin_pcts:
            row: list[Decimal] = []
            for cagr_pct in cagr_pcts:
                perturbed = scenario.model_copy(
                    update={
                        "drivers": scenario.drivers.model_copy(
                            update={
                                "revenue_cagr": cagr_pct,
                                "terminal_margin": margin_pct,
                            }
                        )
                    }
                )
                try:
                    dcf = self.compute_target(
                        scenario=perturbed,
                        wacc_pct=wacc_pct,
                        canonical_state=canonical_state,
                    )
                except ValueError:
                    # Gordon undefined (WACC ≤ g) or other degeneracy.
                    row.append(Decimal("0"))
                    continue
                equity = equity_bridge_fn(dcf, canonical_state)
                row.append(equity.per_share or Decimal("0"))
            grid.append(row)

        return {
            "x_values": cagr_pcts,   # CAGR on x-axis
            "y_values": margin_pcts, # margin on y-axis
            "target_per_share": grid,
            "base_x": base_cagr,
            "base_y": base_margin,
        }

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


_PCT_MIN = Decimal("-100")
_PCT_MAX = Decimal("1000")


def _clip_pct_inline(value: Decimal) -> Decimal:
    """Clip to the :class:`Percentage` schema bounds (−100, 1000).

    Per-year projected margins can overshoot the schema when drivers
    are pathological; clipping avoids a Pydantic validation error at
    the ``ProjectionYear`` boundary."""
    if value < _PCT_MIN:
        return _PCT_MIN
    if value > _PCT_MAX:
        return _PCT_MAX
    return value


def _grid_to_schema(
    raw: dict[str, Any], scenario_label: str, axis_x: str, axis_y: str
) -> SensitivityGrid:
    return SensitivityGrid(
        scenario_label=scenario_label,
        axis_x=axis_x,
        axis_y=axis_y,
        x_values=[_clip_pct_inline(v) for v in raw["x_values"]],
        y_values=[_clip_pct_inline(v) for v in raw["y_values"]],
        target_per_share=raw["target_per_share"],
    )


def _build_equity_bridge_detail(
    equity: Any,
    canonical_state: CanonicalCompanyState,
) -> EquityBridgeDetail:
    """Turn an :class:`EquityValue` + :class:`InvestedCapital` block
    into the richer :class:`EquityBridgeDetail` schema.

    Phase 1.5.9.1: :attr:`bank_debt` and :attr:`lease_liabilities` flow
    into the display as separate lines so the bridge auditably shows
    ``cash + bank_debt + lease_liabilities + NCI = equity`` rather than
    a single opaque net-debt aggregate. The underlying math is
    unchanged (total financial_liabilities sum was already correct).
    """
    ic_list = canonical_state.analysis.invested_capital_by_period
    if ic_list:
        ic = ic_list[0]
        cash = ic.financial_assets
        bank_debt = ic.bank_debt
        lease_liabs = ic.lease_liabilities
        # Any residual (rare: if a balance-sheet line doesn't match
        # either pattern but is classified as financial).
        residual = ic.financial_liabilities - bank_debt - lease_liabs
        nci = ic.nci_claims
    else:
        cash = Decimal("0")
        bank_debt = Decimal("0")
        lease_liabs = Decimal("0")
        residual = Decimal("0")
        nci = Decimal("0")
    return EquityBridgeDetail(
        enterprise_value=equity.enterprise_value,
        cash_and_equivalents=cash,
        financial_debt=bank_debt,
        lease_liabilities=lease_liabs,
        non_controlling_interests=nci,
        other_adjustments=residual,
        equity_value=equity.equity_value,
        shares_outstanding=equity.shares_outstanding,
        target_per_share=equity.per_share,
    )


def _has_non_recurring(canonical_state: CanonicalCompanyState) -> bool:
    bridge_list = canonical_state.analysis.nopat_bridge_by_period
    if not bridge_list:
        return False
    return bridge_list[0].non_recurring_operating_items != 0


def _build_dcf_result(
    ev: Decimal,
    pv_explicit: Decimal,
    pv_terminal: Decimal,
    tv: Decimal,
    wacc_pct: Decimal,
    g_pct: Decimal,
    projected: list[Decimal],
) -> DCFResult:
    """Shim so sensitivity cells can call the EquityBridge without re-
    running :meth:`project_fcff` or rebuilding intermediate state."""
    return DCFResult(
        enterprise_value=ev,
        pv_explicit=pv_explicit,
        pv_terminal=pv_terminal,
        terminal_value=tv,
        wacc_used=wacc_pct,
        implied_g=g_pct,
        projected_fcff=tuple(projected),
        n_years=len(projected),
        projection_detail={},
    )


def _operating_tax_rate(canonical_state: CanonicalCompanyState) -> Decimal:
    """Return the operating tax rate as a decimal fraction.

    Precedence: Module A.1 adjustment (the extraction engine's
    canonical rate) → :class:`NOPATBridge` implied rate
    (``operating_taxes / EBITA``) → 0.

    Phase 1.5.9: the bridge-implied rate anchors on EBITA (matches
    the NOPAT anchor in :mod:`analysis`). When amortisation wasn't
    isolated, EBITA equals EBIT and the rate is identical to an EBIT
    basis.
    """
    for adj in canonical_state.adjustments.module_a_taxes:
        if adj.module == "A.1":
            return adj.amount / _HUNDRED
    bridge_list = canonical_state.analysis.nopat_bridge_by_period
    if bridge_list:
        bridge = bridge_list[0]
        # NOPAT anchor: EBITA when available, else EBIT, else EBITDA
        # for legacy bridges.
        anchor: Decimal | None = (
            bridge.ebita
            or bridge.operating_income
            or bridge.ebitda
        )
        if anchor and anchor != 0:
            return abs(bridge.operating_taxes) / anchor
    return Decimal("0")
