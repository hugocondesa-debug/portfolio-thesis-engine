"""Phase 2 Sprint 4A-alpha — DCF orchestrator.

Assembles the Sprint-3 auto WACC + Sprint-4 profile / scenarios /
engine into a single ``run_dcf(ticker)`` entry point consumed by the
CLI. The orchestrator is deliberately thin — each piece lives in its
own module for testability.
"""

from __future__ import annotations

from decimal import Decimal

from portfolio_thesis_engine.capital import WACCGenerator
from portfolio_thesis_engine.capital.loaders import (
    build_generator_inputs_from_state,
)
from portfolio_thesis_engine.dcf.engine import ValuationEngine
from portfolio_thesis_engine.dcf.p1_engine import PeriodInputs
from portfolio_thesis_engine.dcf.profiles import load_valuation_profile
from portfolio_thesis_engine.dcf.scenarios import load_scenarios
from portfolio_thesis_engine.dcf.schemas import (
    DCFProfile,
    DCFValuationResult,
)
from portfolio_thesis_engine.reference import DamodaranReference


class DCFOrchestrator:
    """Run the DCF for a ticker: load canonical state, auto-generate
    stage-1 WACC (Sprint 3), compute mature stage-3 WACC from the
    profile, load scenarios, dispatch to the profile-specific engine."""

    def __init__(
        self,
        state_repo: object | None = None,
        reference: DamodaranReference | None = None,
    ) -> None:
        from portfolio_thesis_engine.storage.yaml_repo import (
            CompanyStateRepository,
        )

        self.state_repo = state_repo or CompanyStateRepository()
        self.reference = reference or DamodaranReference()

    # ------------------------------------------------------------------
    def run(self, ticker: str) -> DCFValuationResult | None:
        state = self._latest_canonical_state(ticker)
        if state is None:
            return None

        valuation_profile = load_valuation_profile(ticker)
        scenario_set = load_scenarios(ticker)
        if scenario_set is None:
            return None

        stage_1_wacc = self._stage_1_wacc(ticker, state)
        stage_3_wacc = self._stage_3_wacc(
            state, valuation_profile, stage_1_wacc
        )

        period_inputs = self._period_inputs(
            ticker=ticker,
            state=state,
            stage_1_wacc=stage_1_wacc,
            stage_3_wacc=stage_3_wacc,
            valuation_profile=valuation_profile,
        )

        if valuation_profile.profile.code == DCFProfile.P1_INDUSTRIAL_SERVICES:
            peer_comparison = self._load_peer_comparison(ticker)
            return ValuationEngine().run(
                valuation_profile=valuation_profile,
                scenario_set=scenario_set,
                period_inputs=period_inputs,
                peer_comparison=peer_comparison,
            )
        raise NotImplementedError(
            f"DCF profile {valuation_profile.profile.code} is planned "
            "for Sprint 4A-beta / 4B / 4C."
        )

    # ------------------------------------------------------------------
    def _load_peer_comparison(self, ticker: str):
        """Sprint 4A-alpha.2 — best-effort peer-comparison load so the
        :class:`MultipleExitEngine` can source ``PEER_MEDIAN``
        multiples. Returns ``None`` when Sprint 3 peer data isn't
        available for the ticker."""
        try:
            from portfolio_thesis_engine.peers import (
                PeerDiscoverer,
                PeerMetricsFetcher,
            )

            peer_set = PeerDiscoverer().load_or_create(ticker)
            if not peer_set.peers:
                return None
            fetcher = PeerMetricsFetcher()
            return fetcher.fetch(peer_set)
        except Exception:
            return None

    # ------------------------------------------------------------------
    def _latest_canonical_state(self, ticker: str):
        """Sprint 4A-alpha — prefer the most recent state that has
        both ``shares_outstanding`` and an ``InvestedCapital`` block
        populated. Preliminary states (FY2025 investor presentations)
        can land newer but omit these fields; they're unsuitable for
        the DCF inputs even though they're the "latest" extraction."""
        versions = self.state_repo.list_versions(ticker)
        if not versions:
            return None
        states = [
            self.state_repo.get_version(ticker, v) for v in versions
        ]
        states = [s for s in states if s is not None]
        if not states:
            return None
        def _complete(s) -> bool:
            return (
                s.identity.shares_outstanding is not None
                and bool(s.analysis.invested_capital_by_period)
            )
        complete = [s for s in states if _complete(s)]
        pool = complete or states
        return max(pool, key=lambda s: s.extraction_date)

    def _stage_1_wacc(self, ticker: str, state) -> Decimal:
        inputs = build_generator_inputs_from_state(
            ticker, state, marginal_tax_rate=Decimal("0.165")
        )
        result = WACCGenerator(reference=self.reference).generate(inputs)
        return result.wacc

    def _stage_3_wacc(
        self, state, valuation_profile, stage_1_wacc: Decimal
    ) -> Decimal:
        """Stage-3 "mature" WACC. For P1 we relever the profile's
        mature-β against the target-leverage, then apply the same ERP
        + CRP + Rf stack as Sprint 3."""
        currency = state.identity.reporting_currency.value
        rf = self.reference.risk_free_rate(currency) or stage_1_wacc
        mature_beta = valuation_profile.wacc_evolution.stage_3_mature_beta
        target_de = valuation_profile.wacc_evolution.stage_3_target_leverage
        tax = Decimal("0.165")
        levered = mature_beta * (Decimal("1") + (Decimal("1") - tax) * target_de)
        erp = self.reference.mature_market_erp()
        # Same geography CRP as stage 1 (Sprint 4 doesn't re-weight by
        # hypothetical future geographies).
        stage_1_inputs = build_generator_inputs_from_state(state.identity.ticker, state)
        weighted_crp = Decimal("0")
        for g in stage_1_inputs.revenue_geography:
            weighted_crp += g.weight * (self.reference.country_crp(g.country) or Decimal("0"))
        if not stage_1_inputs.revenue_geography:
            weighted_crp = self.reference.country_crp(state.identity.country_domicile) or Decimal("0")
        coe_mature = rf + levered * (erp + weighted_crp)
        # Zero-debt target simplifies WACC = CoE.
        if target_de == 0:
            return coe_mature
        # With debt, blend equity/debt weights.
        equity_weight = Decimal("1") / (Decimal("1") + target_de)
        debt_weight = target_de / (Decimal("1") + target_de)
        cod_pretax = rf + Decimal("0.015")  # ~ BBB spread placeholder
        cod_aftertax = cod_pretax * (Decimal("1") - tax)
        return equity_weight * coe_mature + debt_weight * cod_aftertax

    def _period_inputs(
        self,
        *,
        ticker: str,
        state,
        stage_1_wacc: Decimal,
        stage_3_wacc: Decimal,
        valuation_profile,
    ) -> PeriodInputs:
        ic = (
            state.analysis.invested_capital_by_period[0]
            if state.analysis.invested_capital_by_period
            else None
        )
        cash = ic.financial_assets if ic is not None else Decimal("0")
        debt = ic.bank_debt if ic is not None else Decimal("0")
        net_debt = debt - cash  # Negative when net-cash.
        shares = state.identity.shares_outstanding or Decimal("1")
        market_price = _load_market_price_from_wacc_inputs(ticker)
        return PeriodInputs(
            ticker=ticker,
            stage_1_wacc=stage_1_wacc,
            stage_3_wacc=stage_3_wacc,
            net_debt=net_debt,
            non_operating_assets=Decimal("0"),
            shares_outstanding=shares,
            market_price=market_price,
            industry_median_ev_ebitda=(
                valuation_profile.terminal_value.cross_check_industry_median
            ),
        )


def _load_market_price_from_wacc_inputs(ticker: str) -> Decimal | None:
    """Sprint 4A-alpha.1 Issue 1 — pull ``current_price`` from the
    ticker's ``wacc_inputs.md``. Returns ``None`` when the file is
    missing or unparseable; callers can then fall back to a
    user-supplied override via the CLI ``--market-price`` flag."""
    try:
        from portfolio_thesis_engine.ingestion.wacc_parser import (
            parse_wacc_inputs,
        )
        from portfolio_thesis_engine.shared.config import settings
        from portfolio_thesis_engine.storage.base import normalise_ticker

        path = (
            settings.data_dir
            / "documents"
            / normalise_ticker(ticker)
            / "wacc_inputs"
            / "wacc_inputs.md"
        )
        if not path.exists():
            return None
        wacc_inputs = parse_wacc_inputs(path)
        return wacc_inputs.current_price
    except Exception:
        return None


__all__ = ["DCFOrchestrator"]
