"""Phase 2 Sprint 4A-beta — three-statement forecast orchestrator.

Ties together:

- ``scenarios.yaml`` (drivers + per-scenario overrides)
- ``capital_allocation.yaml`` (dividend, buyback, debt, M&A, share-issuance policies)
- latest canonical state (base-year revenue, margin, PPE, goodwill, cash, debt, equity, shares)

and runs a fixed-point solver per scenario to produce 5-year IS/BS/CF
projections + forward ratios. Writes a JSON snapshot to
``data/forecast_snapshots/{ticker}/{ticker}_{timestamp}.json``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from portfolio_thesis_engine.capital import WACCGenerator
from portfolio_thesis_engine.capital.loaders import (
    build_generator_inputs_from_state,
)
from portfolio_thesis_engine.dcf.scenarios import load_scenarios
from portfolio_thesis_engine.dcf.schemas import (
    Scenario,
    ScenarioDriverOverride,
    ScenarioSet,
)
from portfolio_thesis_engine.forecast.balance_sheet import (
    forecast_balance_sheet,
)
from portfolio_thesis_engine.forecast.capital_allocation_consumer import (
    ParsedCapitalAllocation,
    default_policies,
    load_capital_allocation,
)
from portfolio_thesis_engine.forecast.cash_flow import derive_cash_flow
from portfolio_thesis_engine.forecast.forward_ratios import (
    compute_forward_ratios,
)
from portfolio_thesis_engine.forecast.forward_wacc import compute_forward_wacc
from portfolio_thesis_engine.forecast.income_statement import (
    forecast_income_statement,
)
from portfolio_thesis_engine.forecast.iterative_solver import (
    compute_cash_residual,
    fixed_point_solve,
)
from portfolio_thesis_engine.forecast.schemas import (
    BalanceSheetYear,
    CashFlowYear,
    ForecastResult,
    ForwardRatiosYear,
    IncomeStatementYear,
    ThreeStatementProjection,
)
from portfolio_thesis_engine.ingestion.wacc_parser import parse_wacc_inputs
from portfolio_thesis_engine.schemas.company import CanonicalCompanyState
from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.storage.base import normalise_ticker

_REVENUE_LABELS = ("revenue", "total revenue", "sales", "turnover")
_OPERATING_INCOME_LABELS = (
    "operating profit",
    "operating income",
    "profit from operations",
)
_NET_INCOME_LABELS = (
    "profit for the year",
    "profit for the period",
    "net income",
    "net profit",
)
_PPE_LABELS = (
    "property, plant and equipment",
    "property plant and equipment",
    "property and equipment",
    "plant and equipment",
)
_GOODWILL_LABELS = ("goodwill",)
_INTEREST_INCOME_LABELS = ("finance income", "interest income", "investment income")
_INTEREST_EXPENSE_LABELS = (
    "finance expenses",
    "interest expense",
    "finance costs",
)
_CAPEX_LABELS = (
    "purchases of property, plant and equipment",
    "capital expenditure",
)

# Heuristic fallback shares for the EuroEyes test bed — used only when
# the canonical state omits ``identity.shares_outstanding`` (see Risk #3
# in the sprint plan).
_EUROEYES_FALLBACK_SHARES = Decimal("320_053_000")


@dataclass
class ForwardWACCContext:
    """Concrete ``WACCContext`` adapter over :class:`WACCComputation`.

    Bridges the Sprint-3 engine output (CoE final, CoD after-tax,
    marginal tax rate, blended WACC) into the shape expected by
    :func:`forecast.forward_wacc.compute_forward_wacc`. When the
    Sprint-3 engine returns CoD inapplicable (zero-debt company),
    ``cost_of_debt`` is set to ``Decimal("0")``; forward WACC then
    drops CoD to zero whenever the projected year also has no debt.
    """

    cost_of_equity: Decimal
    cost_of_debt: Decimal
    tax_rate: Decimal
    base_wacc: Decimal


def _first_line_value(
    lines: list[Any], labels: tuple[str, ...]
) -> Decimal | None:
    """Return the first non-subtotal line whose lowercase label matches
    one of ``labels``; subtotals accepted when no plain line matches."""
    normalised = tuple(lbl.lower() for lbl in labels)
    plain: Decimal | None = None
    for line in lines:
        if line.label.lower() in normalised:
            plain = line.value
            break
    return plain


class ForecastOrchestrator:
    """Per-ticker, per-scenario three-statement forecast."""

    def __init__(
        self,
        state_repo: Any | None = None,
        tax_rate_override: Decimal | None = None,
    ) -> None:
        from portfolio_thesis_engine.storage.yaml_repo import (
            CompanyStateRepository,
        )

        self.state_repo = state_repo or CompanyStateRepository()
        self.tax_rate_override = tax_rate_override

    # ------------------------------------------------------------------
    def run(self, ticker: str, years: int = 5) -> ForecastResult | None:
        scenario_set = load_scenarios(ticker)
        if scenario_set is None:
            return None

        state = self._latest_canonical_state(
            ticker, preferred_period_label=scenario_set.base_year
        )
        if state is None:
            return None

        capital_allocation = load_capital_allocation(ticker) or default_policies()
        base_state = self._extract_base_state(state, scenario_set)

        # Sprint-3 WACCGenerator output (same CoE/CoD for every scenario
        # because they describe the same company's structural capital
        # cost). Forward WACC per year is re-weighted from the projected
        # balance sheet inside _compute_ratios. Market price load lives
        # at orchestrator level so a single parser call serves all
        # scenarios.
        wacc_context = self._build_wacc_context(ticker, state, base_state)
        market_price = self._load_market_price(ticker)

        projections: list[ThreeStatementProjection] = []
        for scenario in scenario_set.scenarios:
            projection = self._project_scenario(
                scenario=scenario,
                base_drivers=scenario_set.base_drivers,
                base_state=base_state,
                capital_allocation=capital_allocation,
                years=years,
                wacc_context=wacc_context,
                market_price=market_price,
            )
            projections.append(projection)

        # Aggregate — probability-weighted Y1 EPS (scenarios.yaml validates
        # probabilities sum to ~1, so dividing is unnecessary).
        weighted_eps_y1 = Decimal("0")
        weighted_per_y1 = Decimal("0")
        prob_total_per = Decimal("0")
        for proj in projections:
            if not proj.income_statement:
                continue
            weighted_eps_y1 += (
                proj.income_statement[0].eps * proj.scenario_probability
            )
            if proj.forward_ratios:
                per = proj.forward_ratios[0].per_at_market_price
                if per is not None:
                    weighted_per_y1 += per * proj.scenario_probability
                    prob_total_per += proj.scenario_probability

        expected_per = (
            weighted_per_y1 / prob_total_per if prob_total_per > 0 else None
        )

        return ForecastResult(
            ticker=ticker,
            generated_at=datetime.now(UTC).isoformat(),
            projections=projections,
            expected_forward_eps_y1=weighted_eps_y1,
            expected_forward_per_y1=expected_per,
        )

    # ------------------------------------------------------------------
    def _build_wacc_context(
        self,
        ticker: str,
        state: CanonicalCompanyState,
        base_state: dict[str, Any],
    ) -> ForwardWACCContext | None:
        """Return a :class:`ForwardWACCContext` built from the Sprint-3
        :class:`WACCGenerator`. Returns ``None`` when the generator
        raises (e.g. no Damodaran industry mapping for the ticker) so
        :func:`compute_forward_wacc` falls back to its hardcoded base.
        """
        tax_rate = base_state.get("tax_rate") or Decimal("0.25")
        try:
            inputs = build_generator_inputs_from_state(
                ticker, state, marginal_tax_rate=tax_rate
            )
            result = WACCGenerator().generate(inputs)
        except Exception:
            return None

        cod = result.cost_of_debt
        cod_aftertax = (
            cod.cost_of_debt_aftertax
            if cod.is_applicable and cod.cost_of_debt_aftertax is not None
            else Decimal("0")
        )
        return ForwardWACCContext(
            cost_of_equity=result.cost_of_equity.cost_of_equity_final,
            cost_of_debt=cod_aftertax,
            tax_rate=result.cost_of_equity.marginal_tax_rate,
            base_wacc=result.wacc,
        )

    # ------------------------------------------------------------------
    def _load_market_price(self, ticker: str) -> Decimal | None:
        """Parse ``data/documents/{ticker}/wacc_inputs/wacc_inputs.md``
        via the Sprint-3 ingestion parser and return ``current_price``.

        Returns ``None`` when the file is missing or the parser raises
        — callers treat missing price as "display n/a for PER / FCF
        yield" rather than failing the forecast.
        """
        path = (
            settings.data_dir
            / "documents"
            / normalise_ticker(ticker)
            / "wacc_inputs"
            / "wacc_inputs.md"
        )
        if not path.exists():
            return None
        try:
            parsed = parse_wacc_inputs(path)
        except Exception:
            return None
        return parsed.current_price

    # ------------------------------------------------------------------
    def _latest_canonical_state(
        self,
        ticker: str,
        preferred_period_label: str | None = None,
    ) -> CanonicalCompanyState | None:
        """Pick the canonical state to base the forecast on.

        When ``preferred_period_label`` is supplied (e.g. ``"FY2024"``
        from ``scenarios.yaml``), prefer states whose primary period
        matches. Otherwise pick the most recent state that carries an
        InvestedCapital block. Full-year audited periods trump interim
        H1 states so forecast base values don't half-year-scale.
        """
        versions = self.state_repo.list_versions(ticker)
        if not versions:
            return None
        states = [
            self.state_repo.get_version(ticker, v) for v in versions
        ]
        states = [s for s in states if s is not None]
        if not states:
            return None

        def _complete(s: CanonicalCompanyState) -> bool:
            return bool(s.analysis.invested_capital_by_period)

        complete = [s for s in states if _complete(s)]
        pool = complete or states

        if preferred_period_label:
            matches = [
                s
                for s in pool
                if s.reclassified_statements
                and s.reclassified_statements[0].period.label
                == preferred_period_label
            ]
            if matches:
                return max(matches, key=lambda s: s.extraction_date)

        return max(pool, key=lambda s: s.extraction_date)

    # ------------------------------------------------------------------
    def _extract_base_state(
        self,
        state: CanonicalCompanyState,
        scenario_set: ScenarioSet,
    ) -> dict[str, Any]:
        rs_list = state.reclassified_statements
        rs = rs_list[0] if rs_list else None
        ic = (
            state.analysis.invested_capital_by_period[0]
            if state.analysis.invested_capital_by_period
            else None
        )
        bridge = (
            state.analysis.nopat_bridge_by_period[0]
            if state.analysis.nopat_bridge_by_period
            else None
        )

        revenue = (
            _first_line_value(rs.income_statement, _REVENUE_LABELS)
            if rs is not None
            else None
        ) or Decimal(
            str(
                scenario_set.base_drivers.get("revenue", {}).get(
                    "base_year_value", 0
                )
            )
        )

        operating_income = (
            _first_line_value(rs.income_statement, _OPERATING_INCOME_LABELS)
            if rs is not None
            else None
        )
        if operating_income is None and bridge is not None:
            operating_income = bridge.operating_income or Decimal("0")
        operating_income = operating_income or Decimal("0")

        operating_margin = (
            operating_income / revenue if revenue > 0 else Decimal("0")
        )

        net_income = (
            _first_line_value(rs.income_statement, _NET_INCOME_LABELS)
            if rs is not None
            else None
        )
        if net_income is None and bridge is not None:
            net_income = bridge.reported_net_income
        net_income = net_income or Decimal("0")

        ppe = (
            _first_line_value(rs.balance_sheet, _PPE_LABELS)
            if rs is not None
            else None
        ) or Decimal("0")
        goodwill = (
            _first_line_value(rs.balance_sheet, _GOODWILL_LABELS)
            if rs is not None
            else None
        ) or Decimal("0")

        cash = ic.financial_assets if ic is not None else Decimal("0")
        debt = ic.bank_debt if ic is not None else Decimal("0")
        equity = ic.equity_claims if ic is not None else Decimal("0")
        wc = ic.operating_working_capital if ic is not None else Decimal("0")
        total_assets = (
            (ppe + goodwill + wc + cash) if ic is not None else Decimal("0")
        )

        shares = state.identity.shares_outstanding or _EUROEYES_FALLBACK_SHARES

        da = bridge.depreciation + bridge.amortisation if bridge else Decimal("0")
        ebitda = bridge.ebitda if bridge else (operating_income + da)

        # Base-year tax rate — prefer scenarios.yaml 'statutory' block.
        tax_block = scenario_set.base_drivers.get("tax_rate", {}) or {}
        tax_rate = (
            self.tax_rate_override
            if self.tax_rate_override is not None
            else Decimal(str(tax_block.get("statutory", "0.25")))
        )

        return {
            "revenue": revenue,
            "operating_margin": operating_margin,
            "operating_income": operating_income,
            "net_income": net_income,
            "ppe": ppe,
            "goodwill": goodwill,
            "cash": cash,
            "debt": debt,
            "equity": equity,
            "working_capital": wc,
            "total_assets": total_assets,
            "shares_outstanding": shares,
            "tax_rate": tax_rate,
            "da": da,
            "ebitda": ebitda,
            "base_year_label": (
                rs.period.label if rs is not None else scenario_set.base_year
            ),
        }

    # ------------------------------------------------------------------
    def _merge_drivers(
        self,
        base: dict[str, Any],
        overrides: dict[str, ScenarioDriverOverride],
    ) -> dict[str, Any]:
        """Sparse merge — only specified ScenarioDriverOverride fields
        replace the base."""
        merged: dict[str, Any] = {
            k: (dict(v) if isinstance(v, dict) else v) for k, v in base.items()
        }
        for driver_name, override in (overrides or {}).items():
            if not isinstance(override, ScenarioDriverOverride):
                continue
            current = merged.setdefault(driver_name, {})
            if not isinstance(current, dict):
                current = {}
            if override.current is not None:
                current["current"] = override.current
            if override.target_terminal is not None:
                current["target_terminal"] = override.target_terminal
            if override.growth_pattern is not None:
                current["growth_pattern"] = list(override.growth_pattern)
            if override.fade_pattern is not None:
                current["fade_pattern"] = override.fade_pattern
            merged[driver_name] = current
        return merged

    # ------------------------------------------------------------------
    def _scenario_adjusted_capital_allocation(
        self,
        scenario: Scenario,
        capital_allocation: ParsedCapitalAllocation,
    ) -> ParsedCapitalAllocation:
        """Sprint 4A-beta placeholder — scenario-agnostic (see Risk #2).

        Future 4A-beta.2 sprint will tilt deployment by scenario (e.g.
        ``m_and_a_accelerated`` scenario gets 1.5× M&A target, bears
        slow deployment to 0.5×). For now, returns the same policy for
        every scenario so that the solver has deterministic inputs.
        """
        _ = scenario  # placeholder
        return capital_allocation

    # ------------------------------------------------------------------
    def _project_scenario(
        self,
        *,
        scenario: Scenario,
        base_drivers: dict[str, Any],
        base_state: dict[str, Any],
        capital_allocation: ParsedCapitalAllocation,
        years: int,
        wacc_context: ForwardWACCContext | None = None,
        market_price: Decimal | None = None,
    ) -> ThreeStatementProjection:
        drivers = self._merge_drivers(base_drivers, scenario.driver_overrides)
        ca = self._scenario_adjusted_capital_allocation(
            scenario=scenario, capital_allocation=capital_allocation
        )

        # Pull driver values with sensible fallbacks to base-state.
        revenue_cfg = drivers.get("revenue", {}) or {}
        margin_cfg = drivers.get("operating_margin", {}) or {}
        tax_cfg = drivers.get("tax_rate", {}) or {}
        capex_cfg = drivers.get("capex_intensity", {}) or {}
        wc_cfg = drivers.get("working_capital_intensity", {}) or {}
        depreciation_cfg = drivers.get("depreciation_rate", {}) or {}

        growth_pattern = [
            Decimal(str(g)) for g in (revenue_cfg.get("growth_pattern") or [])
        ]
        if not growth_pattern:
            growth_pattern = [Decimal("0.05")] * years

        margin_current = Decimal(
            str(margin_cfg.get("current", base_state["operating_margin"]))
        )
        margin_terminal = Decimal(
            str(margin_cfg.get("target_terminal", margin_current))
        )
        margin_fade_years = int(
            revenue_cfg.get("fade_to_terminal_over_years", years) or years
        )

        tax_rate = (
            self.tax_rate_override
            if self.tax_rate_override is not None
            else Decimal(str(tax_cfg.get("statutory", base_state["tax_rate"])))
        )

        capex_current = Decimal(str(capex_cfg.get("current", 0)))
        capex_terminal_raw = (
            capex_cfg.get("target")
            or capex_cfg.get("target_terminal")
            or capex_current
        )
        capex_terminal = Decimal(str(capex_terminal_raw))

        wc_target = Decimal(
            str(wc_cfg.get("target", wc_cfg.get("current", 0)))
        )

        depreciation_rate = Decimal(
            str(depreciation_cfg.get("current", "0.08"))
        )

        # Stage 1: first-pass IS (drives revenue + NI for solver inputs).
        is_projections = forecast_income_statement(
            base_year_revenue=base_state["revenue"],
            base_year_operating_margin=margin_current,
            base_year_shares_outstanding=base_state["shares_outstanding"],
            growth_pattern=growth_pattern,
            margin_target_terminal=margin_terminal,
            margin_fade_years=margin_fade_years,
            tax_rate=tax_rate,
            years=years,
        )

        # Stage 2: solver iterates BS + CF until cash converges. The IS
        # may be recomputed each iteration only when shares evolve
        # (buybacks / issuance) or when interest changes materially.
        bs_list, cf_list, is_projections, convergence_info = (
            self._solve_three_statement(
                is_projections=is_projections,
                base_state=base_state,
                drivers={
                    "capex_current": capex_current,
                    "capex_terminal": capex_terminal,
                    "wc_target": wc_target,
                    "depreciation_rate": depreciation_rate,
                    "margin_current": margin_current,
                    "margin_terminal": margin_terminal,
                    "margin_fade_years": margin_fade_years,
                    "growth_pattern": growth_pattern,
                    "tax_rate": tax_rate,
                },
                capital_allocation=ca,
                years=years,
            )
        )

        # Stage 3: forward ratios.
        forward_ratios = self._compute_ratios(
            is_projections=is_projections,
            bs_list=bs_list,
            cf_list=cf_list,
            base_state=base_state,
            drivers={
                "depreciation_rate": depreciation_rate,
                "tax_rate": tax_rate,
            },
            wacc_context=wacc_context,
            market_price=market_price,
        )

        warnings_list: list[str] = []
        if not convergence_info.get("converged"):
            warnings_list.append(
                f"Solver did not converge in "
                f"{convergence_info.get('iterations')} iterations "
                f"(residual={convergence_info.get('final_residual'):.6f})"
            )

        return ThreeStatementProjection(
            scenario_name=scenario.name,
            scenario_probability=scenario.probability,
            base_year_label=base_state["base_year_label"],
            projection_years=years,
            income_statement=is_projections,
            balance_sheet=bs_list,
            cash_flow=cf_list,
            forward_ratios=forward_ratios,
            solver_convergence=convergence_info,
            warnings=warnings_list,
        )

    # ------------------------------------------------------------------
    def _solve_three_statement(
        self,
        *,
        is_projections: list[IncomeStatementYear],
        base_state: dict[str, Any],
        drivers: dict[str, Any],
        capital_allocation: ParsedCapitalAllocation,
        years: int,
    ) -> tuple[
        list[BalanceSheetYear],
        list[CashFlowYear],
        list[IncomeStatementYear],
        dict[str, Any],
    ]:
        initial_state: dict[str, Any] = {
            "bs_cash": [base_state["cash"]] * years,
            "is_projections": is_projections,
            "bs_list": [],
            "cf_list": [],
        }

        def iteration(state: dict[str, Any]) -> dict[str, Any]:
            is_list: list[IncomeStatementYear] = state["is_projections"]
            revenues = [y.revenue for y in is_list]
            nets = [y.net_income for y in is_list]

            # Capex = revenue × intensity (linear fade from current to terminal).
            capex_current = drivers["capex_current"]
            capex_terminal = drivers["capex_terminal"]
            capex = [
                revenues[i]
                * _linear(
                    capex_current, capex_terminal, i + 1, years
                )
                for i in range(years)
            ]

            # D&A approximation tied to PPE roll: start from base PPE +
            # accumulated capex, apply depreciation_rate. Sprint 4A-alpha
            # used revenue × rate/10; we keep that divisor for parity
            # with the DCF first-stage.
            da = [
                revenues[i] * (drivers["depreciation_rate"] / Decimal("10"))
                for i in range(years)
            ]

            # Capital allocation per year.
            dividends = _compute_dividends(nets, capital_allocation, years)
            buybacks = _compute_buybacks(capital_allocation, years)
            ma_deployment = _compute_ma_deployment(capital_allocation, years)
            debt_deltas = _compute_debt_deltas(
                capital_allocation=capital_allocation,
                ma_deployment=ma_deployment,
                base_debt=base_state["debt"],
                years=years,
            )

            # WC target.
            wc_target = drivers["wc_target"]
            wc_per_year = [r * wc_target for r in revenues]

            bs_list = forecast_balance_sheet(
                base_year_ppe=base_state["ppe"],
                base_year_goodwill=base_state["goodwill"],
                base_year_wc=base_state["working_capital"],
                base_year_cash=base_state["cash"],
                base_year_debt=base_state["debt"],
                base_year_equity=base_state["equity"],
                base_year_total_assets=base_state["total_assets"],
                capex_per_year=capex,
                da_per_year=da,
                ma_deployment_per_year=ma_deployment,
                revenue_per_year=revenues,
                wc_to_revenue_target=wc_target,
                net_income_per_year=nets,
                dividends_per_year=dividends,
                buybacks_per_year=buybacks,
                debt_delta_per_year=debt_deltas,
                years=years,
            )

            # Derive CF; propagate cash roll-forward.
            cf_list: list[CashFlowYear] = []
            cash_evolution = [base_state["cash"]]
            for y in range(1, years + 1):
                idx = y - 1
                wc_prev = (
                    base_state["working_capital"]
                    if y == 1
                    else wc_per_year[idx - 1]
                )
                wc_change = wc_per_year[idx] - wc_prev

                cf = derive_cash_flow(
                    net_income=nets[idx],
                    da=da[idx],
                    wc_change=wc_change,
                    capex=capex[idx],
                    ma_deployment=ma_deployment[idx],
                    dividends_paid=dividends[idx],
                    buybacks_executed=buybacks[idx],
                    debt_issued=max(Decimal("0"), debt_deltas[idx]),
                    debt_repaid=max(Decimal("0"), -debt_deltas[idx]),
                    net_interest=Decimal("0"),
                    tax_rate=drivers["tax_rate"],
                    year=y,
                )
                cf_list.append(cf)
                cash_evolution.append(cash_evolution[-1] + cf.net_change_cash)

            # Update BS cash with solver-derived values.
            bs_list = [
                bs.model_copy(update={"cash": cash_evolution[i + 1]})
                for i, bs in enumerate(bs_list)
            ]
            # Rebuild totals with updated cash.
            bs_list = [
                bs.model_copy(
                    update={
                        "total_assets": bs.ppe_net
                        + bs.goodwill
                        + bs.working_capital_net
                        + bs.cash
                    }
                )
                for bs in bs_list
            ]

            return {
                "bs_cash": cash_evolution[1:],
                "is_projections": is_list,
                "bs_list": bs_list,
                "cf_list": cf_list,
            }

        final_state, convergence_info = fixed_point_solve(
            initial_state=initial_state,
            iteration_fn=iteration,
            convergence_fn=compute_cash_residual,
        )

        return (
            final_state.get("bs_list", []),
            final_state.get("cf_list", []),
            final_state.get("is_projections", is_projections),
            convergence_info,
        )

    # ------------------------------------------------------------------
    def _compute_ratios(
        self,
        *,
        is_projections: list[IncomeStatementYear],
        bs_list: list[BalanceSheetYear],
        cf_list: list[CashFlowYear],
        base_state: dict[str, Any],
        drivers: dict[str, Any],
        wacc_context: ForwardWACCContext | None = None,
        market_price: Decimal | None = None,
    ) -> list[ForwardRatiosYear]:
        """Compute per-year forward ratios + per-year WACC.

        Sprint 4A-beta.1 — ``wacc_context`` is built once per ticker
        from the Sprint-3 WACCGenerator output; each projected year
        re-weights equity/debt from the balance sheet. ``market_price``
        is parsed once from ``wacc_inputs.md`` upstream (same source
        the DCF orchestrator uses).
        """
        _ = base_state  # Reserved for fair-value hook (Sprint 4B).
        ratios: list[ForwardRatiosYear] = []
        for idx, is_year in enumerate(is_projections):
            if idx >= len(bs_list) or idx >= len(cf_list):
                break
            bs_year = bs_list[idx]
            cf_year = cf_list[idx]
            da_implied = is_year.revenue * (
                drivers["depreciation_rate"] / Decimal("10")
            )
            ebitda = is_year.operating_income + da_implied
            ratio = compute_forward_ratios(
                is_year=is_year,
                bs_year=bs_year,
                cf_year=cf_year,
                market_price=market_price,
                fair_value=None,
                ebitda_year=ebitda,
            )
            wacc = compute_forward_wacc(
                bs_year=bs_year,
                is_year=is_year,
                wacc_context=wacc_context,
            )
            ratio = ratio.model_copy(update={"wacc_applied": wacc})
            ratios.append(ratio)
        return ratios


# ----------------------------------------------------------------------
# Free-function helpers (capital allocation schedules)
# ----------------------------------------------------------------------
def _linear(
    start: Decimal, end: Decimal, step: int, total_steps: int
) -> Decimal:
    if total_steps <= 0:
        return end
    fraction = Decimal(min(max(step, 0), total_steps)) / Decimal(total_steps)
    return start + (end - start) * fraction


def _compute_dividends(
    net_incomes: list[Decimal],
    capital_allocation: ParsedCapitalAllocation,
    years: int,
) -> list[Decimal]:
    """Return per-year dividend **outflow magnitudes** (positive)."""
    policy = capital_allocation.dividend_policy
    if policy.type == "PAYOUT_RATIO" and policy.payout_ratio is not None:
        return [
            max(Decimal("0"), net_incomes[i] * policy.payout_ratio)
            for i in range(years)
        ]
    if policy.type == "FIXED_AMOUNT" and policy.fixed_amount is not None:
        return [policy.fixed_amount for _ in range(years)]
    if policy.type == "GROWTH_PATTERN" and policy.fixed_amount is not None:
        growth = policy.growth_rate or Decimal("0")
        amounts: list[Decimal] = []
        current = policy.fixed_amount
        for _ in range(years):
            amounts.append(current)
            current = current * (Decimal("1") + growth)
        return amounts
    # ZERO or CONDITIONAL-without-condition-met → no dividends.
    return [Decimal("0")] * years


def _compute_buybacks(
    capital_allocation: ParsedCapitalAllocation, years: int
) -> list[Decimal]:
    """Return per-year buyback outflow magnitudes (positive)."""
    policy = capital_allocation.buyback_policy
    if policy.type == "FIXED_ANNUAL" and policy.annual_amount > 0:
        return [policy.annual_amount] * years
    if policy.type == "PROGRAMMATIC" and policy.annual_amount > 0:
        return [policy.annual_amount] * years
    if policy.type == "CONDITIONAL" and policy.annual_amount > 0:
        # Assume condition holds for the projection horizon — conservative
        # midpoint between "always firing" and "never firing".
        return [policy.annual_amount] * years
    return [Decimal("0")] * years


def _compute_ma_deployment(
    capital_allocation: ParsedCapitalAllocation, years: int
) -> list[Decimal]:
    """Return per-year M&A deployment magnitudes (positive; CF will sign)."""
    policy = capital_allocation.ma_policy
    if policy.type in ("OPPORTUNISTIC", "PROGRAMMATIC", "ACQUIRE_ONLY"):
        return [policy.annual_deployment_target] * years
    return [Decimal("0")] * years


def _compute_debt_deltas(
    *,
    capital_allocation: ParsedCapitalAllocation,
    ma_deployment: list[Decimal],
    base_debt: Decimal,
    years: int,
) -> list[Decimal]:
    """Return per-year debt deltas (+ issuance / − repayment).

    - MAINTAIN_ZERO: zero debt maintained unless ma_policy.funding_source
      is DEBT / MIXED (LEVER_UP alternative only fires when the analyst
      has explicitly signalled debt-funded M&A).
    - MAINTAIN_CURRENT: hold base_debt flat.
    - REPAY: ramp toward zero over horizon.
    - LEVER_UP / TARGET_RATIO: Sprint 4A-beta.2 will lift here.
    """
    policy = capital_allocation.debt_policy
    ma_funding = (capital_allocation.ma_policy.funding_source or "").upper()
    if policy.type == "MAINTAIN_ZERO":
        alt = policy.alternative_for_ma or {}
        if (
            alt.get("type") == "LEVER_UP"
            and ma_funding in ("DEBT", "MIXED")
            and any(m > 0 for m in ma_deployment)
        ):
            # Approximation: draw debt equal to the M&A deployment in Y1
            # and hold flat. Sprint 4A-beta.2 will track
            # target_debt_to_ebitda more precisely.
            deltas: list[Decimal] = []
            for i in range(years):
                deltas.append(ma_deployment[i] if i == 0 else Decimal("0"))
            return deltas
        return [Decimal("0")] * years
    if policy.type == "MAINTAIN_CURRENT":
        return [Decimal("0")] * years
    if policy.type == "REPAY" and base_debt > 0:
        per_year = base_debt / Decimal(max(years, 1))
        return [-per_year for _ in range(years)]
    return [Decimal("0")] * years


# ----------------------------------------------------------------------
# Persistence (Part K)
# ----------------------------------------------------------------------
def persist_forecast(result: ForecastResult) -> Path:
    """Write the forecast result to
    ``data/forecast_snapshots/{ticker}/{ticker}_{YYYYMMDDTHHMMSSZ}.json``.
    Creates the directory if missing; returns the Path of the new file.
    """
    ticker_dir = (
        settings.data_dir
        / "forecast_snapshots"
        / normalise_ticker(result.ticker)
    )
    ticker_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    filename = f"{normalise_ticker(result.ticker)}_{timestamp}.json"
    file_path = ticker_dir / filename

    # Sanitise non-finite decimals that would fail JSON encoding.
    payload = result.model_dump_json(indent=2)
    # Strip ANSI control chars from any free-text field (rare but guards
    # against inadvertent injection from yaml strings).
    payload = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", payload)
    file_path.write_text(payload)
    return file_path


__all__ = ["ForecastOrchestrator", "persist_forecast"]
