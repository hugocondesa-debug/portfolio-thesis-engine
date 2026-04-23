"""Phase 2 Sprint 3 regression tests — peers + cost of capital.

Part A — Peer declaration (5):
- ``test_peer_discovery_fresh_returns_provider_peers``
- ``test_peer_discovery_persists_to_yaml``
- ``test_sync_preserves_user_overrides``
- ``test_sync_preserves_user_included_flag_across_refreshes``
- ``test_max_peers_display_truncates``

Part B — Peer fundamentals fetch + comparison (5):
- ``test_fetch_builds_comparison_from_static_provider``
- ``test_comparison_computes_median``
- ``test_comparison_percentile_rank``
- ``test_comparison_skips_unincluded_peers``
- ``test_comparison_handles_missing_metrics_gracefully``

Part C — Damodaran loader (3):
- ``test_damodaran_country_crp_lookup``
- ``test_damodaran_industry_beta_lookup``
- ``test_damodaran_synthetic_rating_brackets``

Part D.1 — Cost of equity (8):
- ``test_coe_developed_regime_euroeyes_8_10_percent``
- ``test_coe_requires_usd_conversion_when_inflation_diff_gt_3``
- ``test_coe_levered_beta_relevering_formula``
- ``test_coe_weighted_crp_by_geography``
- ``test_coe_falls_back_to_listing_country_without_geography``
- ``test_coe_geography_weights_must_sum_to_one``
- ``test_coe_unknown_industry_raises``
- ``test_coe_unknown_currency_raises``

Part D.2 — Cost of debt (4):
- ``test_cod_zero_debt_not_applicable``
- ``test_cod_missing_interest_expense_not_applicable``
- ``test_cod_synthetic_rating_applied``
- ``test_cod_aftertax_applies_tax_shield``

Part D.3 — WACC (5):
- ``test_wacc_euroeyes_8_10_percent``
- ``test_wacc_manual_comparison_delta_bps``
- ``test_wacc_capital_weights_from_market_values``
- ``test_wacc_capital_weights_fallback_to_de_ratio``
- ``test_wacc_audit_narrative_present``

Part E — Peer valuation (6):
- ``test_multiples_discount_vs_peer_median``
- ``test_multiples_roic_positioning_below``
- ``test_multiples_valuation_positioning_discount``
- ``test_regression_skipped_when_below_min_peers``
- ``test_regression_signal_undervalued_when_actual_below_predicted``
- ``test_build_peer_valuation_summary_bullets_non_empty``

Part F — CLI (3):
- ``test_analyze_cli_renders_cost_of_capital_section``
- ``test_analyze_markdown_includes_cost_of_capital``
- ``test_peers_cli_exits_when_no_peer_declaration``

Integration (4):
- ``test_euroeyes_wacc_auto_matches_manual_within_5bps``
- ``test_euroeyes_regime_developed``
- ``test_euroeyes_geography_weighted_crp_0_74pct``
- ``test_euroeyes_cod_not_applicable_zero_debt``

Total: 43 tests.
"""

from __future__ import annotations

import io
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.console import Console

from portfolio_thesis_engine.capital import (
    GeographyWeight,
    WACCGenerator,
    WACCGeneratorInputs,
)
from portfolio_thesis_engine.cli import analyze_cmd, peers_cmd
from portfolio_thesis_engine.peers import (
    PeerDiscoverer,
    PeerMetricsFetcher,
    build_peer_valuation,
)
from portfolio_thesis_engine.peers.fetcher import make_static_provider
from portfolio_thesis_engine.reference import DamodaranReference
from portfolio_thesis_engine.schemas.peers import (
    PeerCompany,
    PeerFundamentals,
    PeerSet,
)


# ======================================================================
# Shared fixtures
# ======================================================================
def _fund(
    ticker: str,
    *,
    pe: Decimal | None = None,
    ev_ebitda: Decimal | None = None,
    ev_sales: Decimal | None = None,
    roic: Decimal | None = None,
    revenue_growth: Decimal | None = None,
    margin: Decimal | None = None,
    net_margin: Decimal | None = None,
    leverage: Decimal | None = None,
) -> PeerFundamentals:
    return PeerFundamentals(
        ticker=ticker,
        period="FY2024",
        currency="USD",
        price_to_earnings=pe,
        ev_to_ebitda=ev_ebitda,
        ev_to_sales=ev_sales,
        roic=roic,
        revenue_growth_3y_cagr=revenue_growth,
        operating_margin=margin,
        net_margin=net_margin,
        financial_leverage=leverage,
        fetched_at=datetime.now(UTC),
    )


def _peer(
    ticker: str,
    *,
    source: str = "FMP_AUTO",
    included: bool = True,
    rationale: str | None = None,
) -> PeerCompany:
    return PeerCompany(
        ticker=ticker,
        name=f"{ticker} Corp",
        country="US",
        listing_currency="USD",
        source=source,  # type: ignore[arg-type]
        included=included,
        rationale=rationale,
    )


class _StubPeerProvider:
    def __init__(
        self,
        peers: list[PeerCompany],
        sector: str | None = "Healthcare",
        industry: str | None = "Medical Care",
    ) -> None:
        self._peers = peers
        self._sector = sector
        self._industry = industry

    def fetch_peers(
        self, ticker: str
    ) -> tuple[str | None, str | None, list[PeerCompany]]:
        _ = ticker
        return self._sector, self._industry, list(self._peers)


# ======================================================================
# Part A — peer discovery
# ======================================================================
class TestPartAPeerDiscovery:
    def test_peer_discovery_fresh_returns_provider_peers(self) -> None:
        provider = _StubPeerProvider(
            [_peer("EYE"), _peer("LENSL"), _peer("HIM")]
        )
        discoverer = PeerDiscoverer(provider=provider)
        peer_set = discoverer._generate_fresh("1846.HK")
        assert peer_set.target_ticker == "1846.HK"
        assert [p.ticker for p in peer_set.peers] == ["EYE", "LENSL", "HIM"]
        assert peer_set.fmp_sector == "Healthcare"

    def test_peer_discovery_persists_to_yaml(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from portfolio_thesis_engine.shared import config

        monkeypatch.setattr(config.settings, "data_dir", tmp_path)
        provider = _StubPeerProvider([_peer("EYE")])
        discoverer = PeerDiscoverer(provider=provider)
        peer_set = discoverer._generate_fresh("1846.HK")
        written = discoverer.save(peer_set)
        assert written.exists()
        reloaded = discoverer.load_or_create("1846.HK")
        assert [p.ticker for p in reloaded.peers] == ["EYE"]

    def test_sync_preserves_user_overrides(self) -> None:
        user_peer = _peer("EYE", source="USER_OVERRIDE", rationale="Direct optical")
        fmp_peers_v2 = [_peer("LENSL"), _peer("NEW_PEER")]
        discoverer = PeerDiscoverer(provider=_StubPeerProvider(fmp_peers_v2))
        peer_set = PeerSet(
            target_ticker="1846.HK",
            peers=[user_peer, _peer("OLD_FMP")],
            generated_at=datetime.now(UTC),
        )
        synced = discoverer.sync_with_provider(peer_set)
        tickers = [p.ticker for p in synced.peers]
        assert "EYE" in tickers  # User override preserved
        assert "LENSL" in tickers
        assert "NEW_PEER" in tickers
        # OLD_FMP that's no longer in FMP results is dropped.
        assert "OLD_FMP" not in tickers

    def test_sync_preserves_user_included_flag_across_refreshes(self) -> None:
        discoverer = PeerDiscoverer(
            provider=_StubPeerProvider([_peer("LENSL", included=True)])
        )
        peer_set = PeerSet(
            target_ticker="1846.HK",
            peers=[_peer("LENSL", included=False, rationale="Wrong industry")],
            generated_at=datetime.now(UTC),
        )
        synced = discoverer.sync_with_provider(peer_set)
        lensl = next(p for p in synced.peers if p.ticker == "LENSL")
        # User had excluded LENSL — preserved after sync.
        assert lensl.included is False

    def test_max_peers_display_truncates(self) -> None:
        many = [_peer(f"P{i}") for i in range(30)]
        discoverer = PeerDiscoverer(provider=_StubPeerProvider(many))
        peer_set = PeerSet(
            target_ticker="1846.HK",
            peers=[],
            max_peers_display=20,
            generated_at=datetime.now(UTC),
        )
        synced = discoverer.sync_with_provider(peer_set)
        assert len(synced.peers) == 20


# ======================================================================
# Part B — peer fundamentals + comparison
# ======================================================================
class TestPartBPeerFetch:
    def test_fetch_builds_comparison_from_static_provider(self) -> None:
        target = _fund("T", pe=Decimal("11.5"), ev_ebitda=Decimal("2.7"),
                      roic=Decimal("8.2"), margin=Decimal("16.2"))
        p1 = _fund("P1", pe=Decimal("15"), ev_ebitda=Decimal("8"),
                   roic=Decimal("12"), margin=Decimal("18"))
        p2 = _fund("P2", pe=Decimal("20"), ev_ebitda=Decimal("12"),
                   roic=Decimal("15"), margin=Decimal("22"))
        provider = make_static_provider({"T": target, "P1": p1, "P2": p2})
        fetcher = PeerMetricsFetcher(provider=provider)
        peer_set = PeerSet(
            target_ticker="T",
            peers=[_peer("P1"), _peer("P2")],
            generated_at=datetime.now(UTC),
        )
        comparison = fetcher.fetch(peer_set)
        assert comparison is not None
        assert comparison.peer_median["price_to_earnings"] == Decimal("17.5")
        assert len(comparison.peer_fundamentals) == 2

    def test_comparison_computes_median(self) -> None:
        target = _fund("T", roic=Decimal("5"))
        peers = [
            _fund("P1", roic=Decimal("10")),
            _fund("P2", roic=Decimal("15")),
            _fund("P3", roic=Decimal("20")),
        ]
        provider = make_static_provider({
            "T": target, "P1": peers[0], "P2": peers[1], "P3": peers[2]
        })
        fetcher = PeerMetricsFetcher(provider=provider)
        peer_set = PeerSet(
            target_ticker="T",
            peers=[_peer("P1"), _peer("P2"), _peer("P3")],
            generated_at=datetime.now(UTC),
        )
        comparison = fetcher.fetch(peer_set)
        assert comparison is not None
        assert comparison.peer_median["roic"] == Decimal("15")

    def test_comparison_percentile_rank(self) -> None:
        target = _fund("T", roic=Decimal("10"))
        peers = [_fund(f"P{i}", roic=Decimal(str(5 + i))) for i in range(10)]
        provider = make_static_provider(
            {"T": target, **{p.ticker: p for p in peers}}
        )
        fetcher = PeerMetricsFetcher(provider=provider)
        peer_set = PeerSet(
            target_ticker="T",
            peers=[_peer(p.ticker) for p in peers],
            generated_at=datetime.now(UTC),
        )
        comparison = fetcher.fetch(peer_set)
        assert comparison is not None
        # target ROIC 10 vs peers 5..14 → 5 peers below → 50th percentile
        assert comparison.target_percentile["roic"] == 50

    def test_comparison_skips_unincluded_peers(self) -> None:
        target = _fund("T", roic=Decimal("5"))
        p1 = _fund("P1", roic=Decimal("10"))
        p2 = _fund("P2", roic=Decimal("20"))
        provider = make_static_provider({"T": target, "P1": p1, "P2": p2})
        fetcher = PeerMetricsFetcher(provider=provider)
        peer_set = PeerSet(
            target_ticker="T",
            peers=[_peer("P1", included=True), _peer("P2", included=False)],
            generated_at=datetime.now(UTC),
        )
        comparison = fetcher.fetch(peer_set)
        assert comparison is not None
        assert len(comparison.peer_fundamentals) == 1
        assert comparison.peer_fundamentals[0].ticker == "P1"

    def test_comparison_handles_missing_metrics_gracefully(self) -> None:
        target = _fund("T", roic=Decimal("5"), pe=None)
        p1 = _fund("P1", roic=Decimal("10"), pe=Decimal("15"))
        p2 = _fund("P2", roic=Decimal("20"))  # no pe
        provider = make_static_provider({"T": target, "P1": p1, "P2": p2})
        fetcher = PeerMetricsFetcher(provider=provider)
        peer_set = PeerSet(
            target_ticker="T",
            peers=[_peer("P1"), _peer("P2")],
            generated_at=datetime.now(UTC),
        )
        comparison = fetcher.fetch(peer_set)
        assert comparison is not None
        # Only P1 has PE → median equals P1's PE.
        assert comparison.peer_median["price_to_earnings"] == Decimal("15")


# ======================================================================
# Part C — Damodaran loader
# ======================================================================
class TestPartCDamodaran:
    def test_damodaran_country_crp_lookup(self) -> None:
        ref = DamodaranReference()
        assert ref.country_crp("Germany") == Decimal("0.0040")
        assert ref.country_crp("PRC") == Decimal("0.0150")
        assert ref.country_crp("NOEXIST") is None

    def test_damodaran_industry_beta_lookup(self) -> None:
        ref = DamodaranReference()
        assert ref.industry_unlevered_beta("healthcare_services") == Decimal("0.75")

    def test_damodaran_synthetic_rating_brackets(self) -> None:
        ref = DamodaranReference()
        # Coverage 15× → AAA
        rating, spread = ref.synthetic_rating_for_coverage(Decimal("15"))
        assert rating == "AAA"
        assert spread == Decimal("0.0063")
        # Coverage 3.5× → BBB (min 3.0)
        rating, _ = ref.synthetic_rating_for_coverage(Decimal("3.5"))
        assert rating == "BBB"


# ======================================================================
# Part D.1 — Cost of equity
# ======================================================================
class TestPartDCostOfEquity:
    def _euroeyes_inputs(self) -> WACCGeneratorInputs:
        return WACCGeneratorInputs(
            target_ticker="1846.HK",
            listing_currency="HKD",
            country_domicile="HK",
            industry_key="healthcare_services",
            debt_to_equity=Decimal("0"),
            marginal_tax_rate=Decimal("0.165"),
            revenue_geography=[
                GeographyWeight("Germany", Decimal("0.35")),
                GeographyWeight("PRC", Decimal("0.30")),
                GeographyWeight("Denmark", Decimal("0.15")),
                GeographyWeight("HK", Decimal("0.20")),
            ],
            equity_market_value=Decimal("968"),
            manual_wacc=Decimal("0.0812"),
        )

    def test_coe_developed_regime_euroeyes_8_10_percent(self) -> None:
        gen = WACCGenerator()
        result = gen.generate(self._euroeyes_inputs())
        assert result.cost_of_equity.currency_regime == "DEVELOPED"
        assert result.cost_of_equity.requires_usd_conversion is False
        # 8.095 % per Damodaran formula.
        assert abs(
            result.cost_of_equity.cost_of_equity_final - Decimal("0.0810")
        ) < Decimal("0.0005")

    def test_coe_requires_usd_conversion_when_inflation_diff_gt_3(self) -> None:
        """TRY inflation ~42 % vs USD ~2.4 % → HIGH_INFLATION regime."""
        inputs = WACCGeneratorInputs(
            target_ticker="TEST.IS",
            listing_currency="TRY",
            country_domicile="Turkey",
            industry_key="healthcare_services",
        )
        # Turkey isn't in our CRP table — expect graceful fallback to 0.
        # We only care that regime detection flips correctly.
        gen = WACCGenerator()
        result = gen.generate(inputs)
        assert result.cost_of_equity.currency_regime == "HIGH_INFLATION"
        assert result.cost_of_equity.requires_usd_conversion is True

    def test_coe_levered_beta_relevering_formula(self) -> None:
        inputs = WACCGeneratorInputs(
            target_ticker="TEST",
            listing_currency="USD",
            country_domicile="US",
            industry_key="healthcare_services",
            debt_to_equity=Decimal("0.5"),
            marginal_tax_rate=Decimal("0.25"),
        )
        gen = WACCGenerator()
        result = gen.generate(inputs)
        # levered = 0.75 × (1 + (1-0.25) × 0.5) = 0.75 × 1.375 = 1.03125
        assert abs(
            result.cost_of_equity.levered_beta - Decimal("1.03125")
        ) < Decimal("0.0001")

    def test_coe_weighted_crp_by_geography(self) -> None:
        gen = WACCGenerator()
        result = gen.generate(self._euroeyes_inputs())
        # 0.35 × 0.004 + 0.30 × 0.015 + 0.15 × 0.002 + 0.20 × 0.006 = 0.0074
        assert abs(
            result.cost_of_equity.weighted_crp - Decimal("0.0074")
        ) < Decimal("0.0001")

    def test_coe_falls_back_to_listing_country_without_geography(self) -> None:
        inputs = WACCGeneratorInputs(
            target_ticker="DE-TEST",
            listing_currency="EUR",
            country_domicile="Germany",
            industry_key="healthcare_services",
        )
        gen = WACCGenerator()
        result = gen.generate(inputs)
        # Falls back to Germany only: CRP = 0.004.
        assert result.cost_of_equity.weighted_crp == Decimal("0.004")
        assert list(result.cost_of_equity.revenue_geography.keys()) == ["Germany"]

    def test_coe_geography_weights_must_sum_to_one(self) -> None:
        bad = WACCGeneratorInputs(
            target_ticker="BAD",
            listing_currency="HKD",
            country_domicile="HK",
            industry_key="healthcare_services",
            revenue_geography=[
                GeographyWeight("Germany", Decimal("0.50")),
                GeographyWeight("PRC", Decimal("0.30")),
                # Missing 20 % → sums to 0.80.
            ],
        )
        with pytest.raises(ValueError, match="revenue_geography"):
            WACCGenerator().generate(bad)

    def test_coe_unknown_industry_raises(self) -> None:
        inputs = WACCGeneratorInputs(
            target_ticker="TEST",
            listing_currency="USD",
            country_domicile="US",
            industry_key="nonexistent_industry",
        )
        with pytest.raises(ValueError, match="industry beta"):
            WACCGenerator().generate(inputs)

    def test_coe_unknown_currency_raises(self) -> None:
        inputs = WACCGeneratorInputs(
            target_ticker="TEST",
            listing_currency="ZZZ",
            country_domicile="US",
            industry_key="healthcare_services",
        )
        with pytest.raises(ValueError, match="risk-free rate"):
            WACCGenerator().generate(inputs)


# ======================================================================
# Part D.2 — Cost of debt
# ======================================================================
class TestPartDCostOfDebt:
    def test_cod_zero_debt_not_applicable(self) -> None:
        inputs = WACCGeneratorInputs(
            target_ticker="TEST",
            listing_currency="USD",
            country_domicile="US",
            industry_key="healthcare_services",
            debt_to_equity=Decimal("0"),
            debt_book_value=Decimal("0"),
        )
        result = WACCGenerator().generate(inputs)
        assert result.cost_of_debt.is_applicable is False
        assert "not applicable" in (result.cost_of_debt.rationale or "").lower()

    def test_cod_missing_interest_expense_not_applicable(self) -> None:
        inputs = WACCGeneratorInputs(
            target_ticker="TEST",
            listing_currency="USD",
            country_domicile="US",
            industry_key="healthcare_services",
            debt_to_equity=Decimal("0.5"),
            debt_book_value=Decimal("100"),
            ebit=Decimal("50"),
            interest_expense=None,  # missing
        )
        result = WACCGenerator().generate(inputs)
        assert result.cost_of_debt.is_applicable is False

    def test_cod_synthetic_rating_applied(self) -> None:
        inputs = WACCGeneratorInputs(
            target_ticker="TEST",
            listing_currency="USD",
            country_domicile="US",
            industry_key="healthcare_services",
            debt_to_equity=Decimal("0.5"),
            debt_book_value=Decimal("100"),
            ebit=Decimal("150"),
            interest_expense=Decimal("10"),
            marginal_tax_rate=Decimal("0.25"),
        )
        result = WACCGenerator().generate(inputs)
        # EBIT/Interest = 15 → AAA bracket, spread 63 bps.
        assert result.cost_of_debt.is_applicable is True
        assert result.cost_of_debt.synthetic_rating == "AAA"
        assert result.cost_of_debt.rating_spread == Decimal("0.0063")

    def test_cod_aftertax_applies_tax_shield(self) -> None:
        inputs = WACCGeneratorInputs(
            target_ticker="TEST",
            listing_currency="USD",
            country_domicile="US",
            industry_key="healthcare_services",
            debt_to_equity=Decimal("0.5"),
            debt_book_value=Decimal("100"),
            ebit=Decimal("150"),
            interest_expense=Decimal("10"),
            marginal_tax_rate=Decimal("0.25"),
        )
        result = WACCGenerator().generate(inputs)
        # pretax = Rf 4% + 63bps = 4.63%; after-tax = 4.63% × (1-0.25) = 3.4725%
        assert result.cost_of_debt.cost_of_debt_aftertax is not None
        assert abs(
            result.cost_of_debt.cost_of_debt_aftertax - Decimal("0.034725")
        ) < Decimal("0.0001")


# ======================================================================
# Part D.3 — WACC
# ======================================================================
class TestPartDWACC:
    def test_wacc_euroeyes_8_10_percent(self) -> None:
        gen = WACCGenerator()
        inputs = WACCGeneratorInputs(
            target_ticker="1846.HK",
            listing_currency="HKD",
            country_domicile="HK",
            industry_key="healthcare_services",
            marginal_tax_rate=Decimal("0.165"),
            revenue_geography=[
                GeographyWeight("Germany", Decimal("0.35")),
                GeographyWeight("PRC", Decimal("0.30")),
                GeographyWeight("Denmark", Decimal("0.15")),
                GeographyWeight("HK", Decimal("0.20")),
            ],
        )
        result = gen.generate(inputs)
        # Target ≈ 8.10 %.
        assert abs(result.wacc - Decimal("0.0810")) < Decimal("0.0005")

    def test_wacc_manual_comparison_delta_bps(self) -> None:
        gen = WACCGenerator()
        inputs = WACCGeneratorInputs(
            target_ticker="1846.HK",
            listing_currency="HKD",
            country_domicile="HK",
            industry_key="healthcare_services",
            marginal_tax_rate=Decimal("0.165"),
            manual_wacc=Decimal("0.0812"),
            revenue_geography=[
                GeographyWeight("Germany", Decimal("0.35")),
                GeographyWeight("PRC", Decimal("0.30")),
                GeographyWeight("Denmark", Decimal("0.15")),
                GeographyWeight("HK", Decimal("0.20")),
            ],
        )
        result = gen.generate(inputs)
        assert result.manual_wacc == Decimal("0.0812")
        assert result.manual_vs_computed_bps is not None
        assert abs(result.manual_vs_computed_bps) <= 5

    def test_wacc_capital_weights_from_market_values(self) -> None:
        inputs = WACCGeneratorInputs(
            target_ticker="TEST",
            listing_currency="USD",
            country_domicile="US",
            industry_key="healthcare_services",
            debt_to_equity=Decimal("0.5"),
            debt_book_value=Decimal("100"),
            equity_market_value=Decimal("300"),
            ebit=Decimal("200"),
            interest_expense=Decimal("10"),
        )
        result = WACCGenerator().generate(inputs)
        # E/V = 300/400 = 0.75; D/V = 100/400 = 0.25.
        assert result.equity_weight == Decimal("0.75")
        assert result.debt_weight == Decimal("0.25")

    def test_wacc_capital_weights_fallback_to_de_ratio(self) -> None:
        inputs = WACCGeneratorInputs(
            target_ticker="TEST",
            listing_currency="USD",
            country_domicile="US",
            industry_key="healthcare_services",
            debt_to_equity=Decimal("0.4"),
            equity_market_value=None,
        )
        result = WACCGenerator().generate(inputs)
        # total = 1 + 0.4 = 1.4; E/V = 1/1.4 ≈ 0.714; D/V = 0.4/1.4 ≈ 0.286.
        assert abs(result.equity_weight - Decimal("0.7143")) < Decimal("0.001")
        assert abs(result.debt_weight - Decimal("0.2857")) < Decimal("0.001")

    def test_wacc_audit_narrative_present(self) -> None:
        gen = WACCGenerator()
        inputs = WACCGeneratorInputs(
            target_ticker="TEST",
            listing_currency="USD",
            country_domicile="US",
            industry_key="healthcare_services",
        )
        result = gen.generate(inputs)
        assert "Currency regime" in result.wacc_audit_narrative
        assert "CoE" in result.wacc_audit_narrative


# ======================================================================
# Part E — peer valuation
# ======================================================================
class TestPartEPeerValuation:
    def _comparison_euroeyes_like(self):
        target = _fund(
            "1846.HK", pe=Decimal("11.5"), ev_ebitda=Decimal("2.7"),
            ev_sales=Decimal("0.45"), roic=Decimal("8.2"),
            revenue_growth=Decimal("0.2"), margin=Decimal("16.2"),
        )
        peers = [
            _fund(f"P{i}",
                  pe=Decimal("15") + Decimal(str(i)),
                  ev_ebitda=Decimal("8") + Decimal(str(i * 0.5)),
                  ev_sales=Decimal("1.5") + Decimal(str(i * 0.1)),
                  roic=Decimal("10") + Decimal(str(i)),
                  revenue_growth=Decimal("5") + Decimal(str(i * 0.2)),
                  margin=Decimal("16") + Decimal(str(i * 0.3)),
                  )
            for i in range(7)
        ]
        provider = make_static_provider({
            "1846.HK": target, **{p.ticker: p for p in peers}
        })
        fetcher = PeerMetricsFetcher(provider=provider)
        peer_set = PeerSet(
            target_ticker="1846.HK",
            peers=[_peer(p.ticker) for p in peers],
            min_peers_regression=5,
            generated_at=datetime.now(UTC),
        )
        return fetcher.fetch(peer_set)

    def test_multiples_discount_vs_peer_median(self) -> None:
        comparison = self._comparison_euroeyes_like()
        valuation = build_peer_valuation(comparison, min_peers=5)
        assert valuation.multiples is not None
        assert valuation.multiples.target_discount_ev_ebitda_pct is not None
        # Target 2.7x vs median ≥ 8.5x → strong discount (< −50 %).
        assert valuation.multiples.target_discount_ev_ebitda_pct < Decimal("-50")

    def test_multiples_roic_positioning_below(self) -> None:
        comparison = self._comparison_euroeyes_like()
        valuation = build_peer_valuation(comparison, min_peers=5)
        assert valuation.multiples is not None
        assert valuation.multiples.roic_positioning == "BELOW_PEER"

    def test_multiples_valuation_positioning_discount(self) -> None:
        comparison = self._comparison_euroeyes_like()
        valuation = build_peer_valuation(comparison, min_peers=5)
        assert valuation.multiples is not None
        assert valuation.multiples.valuation_positioning == "DISCOUNT"

    def test_regression_skipped_when_below_min_peers(self) -> None:
        target = _fund("T", ev_ebitda=Decimal("5"), roic=Decimal("10"),
                      revenue_growth=Decimal("5"), margin=Decimal("15"))
        p1 = _fund("P1", ev_ebitda=Decimal("8"), roic=Decimal("12"),
                   revenue_growth=Decimal("7"), margin=Decimal("18"))
        provider = make_static_provider({"T": target, "P1": p1})
        fetcher = PeerMetricsFetcher(provider=provider)
        peer_set = PeerSet(
            target_ticker="T",
            peers=[_peer("P1")],
            min_peers_regression=5,
            generated_at=datetime.now(UTC),
        )
        comparison = fetcher.fetch(peer_set)
        assert comparison is not None
        valuation = build_peer_valuation(comparison, min_peers=5)
        assert valuation.regression is None

    def test_regression_signal_undervalued_when_actual_below_predicted(
        self,
    ) -> None:
        comparison = self._comparison_euroeyes_like()
        valuation = build_peer_valuation(comparison, min_peers=5)
        assert valuation.regression is not None
        # Actual 2.7× well below peer-fundamentals-predicted multiple.
        assert valuation.regression.signal == "UNDERVALUED"

    def test_build_peer_valuation_summary_bullets_non_empty(self) -> None:
        comparison = self._comparison_euroeyes_like()
        valuation = build_peer_valuation(comparison, min_peers=5)
        assert valuation.summary_bullets


# ======================================================================
# Part F — CLI
# ======================================================================
class TestPartFCLI:
    def test_analyze_cli_renders_cost_of_capital_section(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The `pte analyze` CLI now prints the auto-generated WACC
        section after ROIC attribution. We exercise the live code on
        the EuroEyes canonical state shipped under data/yamls/."""
        from portfolio_thesis_engine.analytical.historicals import (
            HistoricalNormalizer,
        )

        buf = io.StringIO()
        test_console = Console(file=buf, width=240, record=True)
        monkeypatch.setattr(analyze_cmd, "console", test_console)
        normalizer = HistoricalNormalizer()
        analyze_cmd._run_analyze(
            "1846.HK", export=None, normalizer=normalizer
        )
        rendered = buf.getvalue()
        assert "Cost of Capital" in rendered
        assert "WACC" in rendered

    def test_analyze_markdown_includes_cost_of_capital(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from portfolio_thesis_engine.analytical.historicals import (
            HistoricalNormalizer,
        )

        buf = io.StringIO()
        test_console = Console(file=buf, width=240)
        monkeypatch.setattr(analyze_cmd, "console", test_console)
        out = tmp_path / "analytical.md"
        analyze_cmd._run_analyze(
            "1846.HK", export=out, normalizer=HistoricalNormalizer()
        )
        md = out.read_text()
        assert "## Cost of Capital" in md

    def test_peers_cli_exits_when_no_peer_declaration(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        from portfolio_thesis_engine.shared import config
        import typer

        monkeypatch.setattr(config.settings, "data_dir", tmp_path)
        buf = io.StringIO()
        monkeypatch.setattr(peers_cmd, "console", Console(file=buf, width=120))
        with pytest.raises(typer.Exit):
            peers_cmd._run_peers("NOPE", export=None)


# ======================================================================
# Integration — EuroEyes
# ======================================================================
class TestEuroEyesIntegration:
    def _result(self):
        gen = WACCGenerator()
        inputs = WACCGeneratorInputs(
            target_ticker="1846.HK",
            listing_currency="HKD",
            country_domicile="HK",
            industry_key="healthcare_services",
            marginal_tax_rate=Decimal("0.165"),
            manual_wacc=Decimal("0.0812"),
            revenue_geography=[
                GeographyWeight("Germany", Decimal("0.35")),
                GeographyWeight("PRC", Decimal("0.30")),
                GeographyWeight("Denmark", Decimal("0.15")),
                GeographyWeight("HK", Decimal("0.20")),
            ],
        )
        return gen.generate(inputs)

    def test_euroeyes_wacc_auto_matches_manual_within_5bps(self) -> None:
        result = self._result()
        assert result.manual_vs_computed_bps is not None
        assert abs(result.manual_vs_computed_bps) <= 5

    def test_euroeyes_regime_developed(self) -> None:
        result = self._result()
        assert result.cost_of_equity.currency_regime == "DEVELOPED"

    def test_euroeyes_geography_weighted_crp_0_74pct(self) -> None:
        result = self._result()
        # 74 bps.
        assert abs(
            result.cost_of_equity.weighted_crp - Decimal("0.0074")
        ) < Decimal("0.00001")

    def test_euroeyes_cod_not_applicable_zero_debt(self) -> None:
        result = self._result()
        assert result.cost_of_debt.is_applicable is False
        assert result.cost_of_debt.cost_of_debt_aftertax is None
