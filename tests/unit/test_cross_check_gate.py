"""Unit tests for the cross-check gate."""

from __future__ import annotations

import json
from decimal import Decimal
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from portfolio_thesis_engine.cross_check import (
    CrossCheckGate,
    CrossCheckStatus,
)
from portfolio_thesis_engine.cross_check.thresholds import (
    DEFAULT_METRIC_THRESHOLDS,
    DEFAULT_THRESHOLDS,
    load_thresholds,
    thresholds_for,
)
from portfolio_thesis_engine.market_data.base import (
    MarketDataError,
    TickerNotFoundError,
)
from portfolio_thesis_engine.market_data.fmp_provider import FMPProvider
from portfolio_thesis_engine.market_data.yfinance_provider import YFinanceProvider

# ======================================================================
# Fixtures / builders
# ======================================================================


_FULL_EXTRACTED: dict[str, Decimal] = {
    "revenue": Decimal("580"),
    "operating_income": Decimal("110"),
    "net_income": Decimal("75"),
    "total_assets": Decimal("3200"),
    "total_equity": Decimal("1900"),
    "cash": Decimal("450"),
    "operating_cash_flow": Decimal("135"),
    "capex": Decimal("-75"),
    "shares_outstanding": Decimal("200"),
    "market_cap": Decimal("2500"),
}


def _fmp_fund(
    revenue: float = 580.0,
    operating_income: float = 110.0,
    net_income: float = 75.0,
    total_assets: float = 3200.0,
    total_equity: float = 1900.0,
    cash: float = 450.0,
    operating_cash_flow: float = 135.0,
    capex: float = -75.0,
) -> dict:
    return {
        "income_statement": [
            {
                "revenue": revenue,
                "operatingIncome": operating_income,
                "netIncome": net_income,
            }
        ],
        "balance_sheet": [
            {
                "totalAssets": total_assets,
                "totalStockholdersEquity": total_equity,
                "cashAndCashEquivalents": cash,
            }
        ],
        "cash_flow": [
            {
                "operatingCashFlow": operating_cash_flow,
                "capitalExpenditure": capex,
            }
        ],
    }


def _yf_fund(
    revenue: float = 582.0,
    operating_income: float = 108.0,
    net_income: float = 76.0,
    total_assets: float = 3195.0,
    total_equity: float = 1905.0,
    cash: float = 449.0,
    operating_cash_flow: float = 134.0,
    capex: float = -74.0,
) -> dict:
    return {
        "income_statement": [
            {
                "Total Revenue": revenue,
                "Operating Income": operating_income,
                "Net Income": net_income,
            }
        ],
        "balance_sheet": [
            {
                "Total Assets": total_assets,
                "Stockholders Equity": total_equity,
                "Cash And Cash Equivalents": cash,
            }
        ],
        "cash_flow": [
            {
                "Operating Cash Flow": operating_cash_flow,
                "Capital Expenditure": capex,
            }
        ],
    }


def _fmp_km(shares_outstanding: float = 200.0, market_cap: float = 2500.0) -> dict:
    return {
        "records": [
            {
                "sharesOutstanding": shares_outstanding,
                "marketCap": market_cap,
            }
        ]
    }


def _yf_km(shares_outstanding: float = 199.0, market_cap: float = 2480.0) -> dict:
    return {
        "records": [
            {
                "sharesOutstanding": shares_outstanding,
                "marketCap": market_cap,
            }
        ]
    }


def _make_providers(
    fmp_fund_data: dict | BaseException | None = None,
    fmp_km_data: dict | BaseException | None = None,
    yf_fund_data: dict | BaseException | None = None,
    yf_km_data: dict | BaseException | None = None,
) -> tuple[MagicMock, MagicMock]:
    fmp = MagicMock(spec=FMPProvider)
    fmp.get_fundamentals = AsyncMock(
        side_effect=fmp_fund_data if isinstance(fmp_fund_data, BaseException) else None,
        return_value=fmp_fund_data if not isinstance(fmp_fund_data, BaseException) else None,
    )
    fmp.get_key_metrics = AsyncMock(
        side_effect=fmp_km_data if isinstance(fmp_km_data, BaseException) else None,
        return_value=fmp_km_data if not isinstance(fmp_km_data, BaseException) else None,
    )
    yf = MagicMock(spec=YFinanceProvider)
    yf.get_fundamentals = AsyncMock(
        side_effect=yf_fund_data if isinstance(yf_fund_data, BaseException) else None,
        return_value=yf_fund_data if not isinstance(yf_fund_data, BaseException) else None,
    )
    yf.get_key_metrics = AsyncMock(
        side_effect=yf_km_data if isinstance(yf_km_data, BaseException) else None,
        return_value=yf_km_data if not isinstance(yf_km_data, BaseException) else None,
    )
    return fmp, yf


# ======================================================================
# Thresholds module
# ======================================================================


class TestThresholds:
    def test_defaults_present(self) -> None:
        assert DEFAULT_THRESHOLDS["PASS"] == Decimal("0.02")
        assert DEFAULT_THRESHOLDS["WARN"] == Decimal("0.10")
        assert DEFAULT_THRESHOLDS["sources_disagree"] == Decimal("0.05")

    def test_metric_specific_defaults(self) -> None:
        assert "operating_income" in DEFAULT_METRIC_THRESHOLDS

    def test_load_no_override_uses_defaults(self) -> None:
        defaults, per_metric = load_thresholds(None)
        assert defaults["PASS"] == Decimal("0.02")
        assert per_metric["operating_income"]["PASS"] == Decimal("0.05")

    def test_load_override_defaults(self) -> None:
        override = json.dumps({"defaults": {"PASS": "0.03", "WARN": "0.12"}})
        defaults, _ = load_thresholds(override)
        assert defaults["PASS"] == Decimal("0.03")
        assert defaults["WARN"] == Decimal("0.12")
        # sources_disagree stays at default
        assert defaults["sources_disagree"] == Decimal("0.05")

    def test_load_override_per_metric(self) -> None:
        override = json.dumps({"per_metric": {"revenue": {"PASS": "0.01", "WARN": "0.05"}}})
        _, per_metric = load_thresholds(override)
        assert per_metric["revenue"]["PASS"] == Decimal("0.01")
        assert per_metric["revenue"]["WARN"] == Decimal("0.05")

    def test_load_invalid_json_falls_back_to_defaults(self) -> None:
        defaults, _ = load_thresholds("{not valid json")
        assert defaults["PASS"] == Decimal("0.02")

    def test_load_non_dict_top_level_falls_back(self) -> None:
        defaults, _ = load_thresholds('["not", "a", "dict"]')
        assert defaults["PASS"] == Decimal("0.02")

    def test_thresholds_for_per_metric_override(self) -> None:
        defaults, per_metric = load_thresholds(None)
        tol = thresholds_for("operating_income", defaults, per_metric)
        assert tol["PASS"] == Decimal("0.05")
        assert tol["WARN"] == Decimal("0.15")

    def test_thresholds_for_falls_back_to_defaults(self) -> None:
        defaults, per_metric = load_thresholds(None)
        tol = thresholds_for("revenue", defaults, per_metric)
        assert tol["PASS"] == Decimal("0.02")
        assert tol["WARN"] == Decimal("0.10")


# ======================================================================
# Happy-path check
# ======================================================================


class TestGateHappy:
    @pytest.mark.asyncio
    async def test_all_metrics_pass(self, tmp_path: Path) -> None:
        fmp, yf = _make_providers(
            fmp_fund_data=_fmp_fund(),
            fmp_km_data=_fmp_km(),
            yf_fund_data=_yf_fund(),
            yf_km_data=_yf_km(),
        )
        gate = CrossCheckGate(fmp, yf, log_dir=tmp_path)
        report = await gate.check(
            ticker="1846.HK",
            extracted_values=_FULL_EXTRACTED,
            period="FY2024",
        )
        assert report.overall_status == CrossCheckStatus.PASS
        assert report.blocking is False
        assert len(report.metrics) == 10
        assert all(m.status == CrossCheckStatus.PASS for m in report.metrics)


class TestGateWarn:
    @pytest.mark.asyncio
    async def test_one_metric_warn(self, tmp_path: Path) -> None:
        """Revenue extracted 580 but both sources show 700 → ~17% off → WARN
        per default 2-10% WARN, >10% FAIL. 17% > 10% → FAIL actually.
        Use a smaller drift that lands in WARN range."""
        fmp, yf = _make_providers(
            fmp_fund_data=_fmp_fund(revenue=620.0),
            fmp_km_data=_fmp_km(),
            yf_fund_data=_yf_fund(revenue=622.0),
            yf_km_data=_yf_km(),
        )
        gate = CrossCheckGate(fmp, yf, log_dir=tmp_path)
        report = await gate.check(
            ticker="1846.HK",
            extracted_values=_FULL_EXTRACTED,
            period="FY2024",
        )
        # 622 vs 580 → 7.2% Δ → WARN (2% < 7.2% < 10%)
        rev = next(m for m in report.metrics if m.metric == "revenue")
        assert rev.status == CrossCheckStatus.WARN
        assert report.overall_status == CrossCheckStatus.WARN
        assert report.blocking is False


class TestGateFail:
    @pytest.mark.asyncio
    async def test_one_metric_fail_blocks(self, tmp_path: Path) -> None:
        """Net income extracted 75 but both sources show 7.5 (10x off) → FAIL."""
        fmp, yf = _make_providers(
            fmp_fund_data=_fmp_fund(net_income=7.5),
            fmp_km_data=_fmp_km(),
            yf_fund_data=_yf_fund(net_income=7.6),
            yf_km_data=_yf_km(),
        )
        gate = CrossCheckGate(fmp, yf, log_dir=tmp_path)
        report = await gate.check(
            ticker="1846.HK",
            extracted_values=_FULL_EXTRACTED,
            period="FY2024",
        )
        ni = next(m for m in report.metrics if m.metric == "net_income")
        assert ni.status == CrossCheckStatus.FAIL
        assert report.overall_status == CrossCheckStatus.FAIL
        assert report.blocking is True


# ======================================================================
# Sources disagree
# ======================================================================


class TestSourcesDisagree:
    @pytest.mark.asyncio
    async def test_fmp_and_yf_differ_flags_sources_disagree(self, tmp_path: Path) -> None:
        """Extracted matches FMP within PASS tolerance but yfinance is 7%
        off from FMP → sources_disagree kicks in, status → WARN baseline +
        disagreement → SOURCES_DISAGREE."""
        fmp, yf = _make_providers(
            fmp_fund_data=_fmp_fund(revenue=580.0),
            fmp_km_data=_fmp_km(),
            yf_fund_data=_yf_fund(revenue=620.0),  # 6.9% vs FMP, >5%
            yf_km_data=_yf_km(),
        )
        gate = CrossCheckGate(fmp, yf, log_dir=tmp_path)
        report = await gate.check(
            ticker="1846.HK",
            extracted_values=_FULL_EXTRACTED,
            period="FY2024",
        )
        rev = next(m for m in report.metrics if m.metric == "revenue")
        # Extracted vs max(FMP,yf) = max(0, 40/580) = 6.9% → WARN tier,
        # but because FMP and yf disagree by >5% between themselves,
        # WARN is upgraded to SOURCES_DISAGREE.
        assert rev.status == CrossCheckStatus.SOURCES_DISAGREE
        assert "differ" in rev.notes.lower()
        assert report.overall_status == CrossCheckStatus.SOURCES_DISAGREE
        # Still non-blocking (not FAIL)
        assert report.blocking is False


# ======================================================================
# Unavailable
# ======================================================================


class TestUnavailable:
    @pytest.mark.asyncio
    async def test_neither_source_publishes_metric(self, tmp_path: Path) -> None:
        fmp_fund = _fmp_fund()
        # Strip capex from FMP CF
        fmp_fund["cash_flow"][0].pop("capitalExpenditure", None)
        yf_fund = _yf_fund()
        yf_fund["cash_flow"][0].pop("Capital Expenditure", None)

        fmp, yf = _make_providers(
            fmp_fund_data=fmp_fund,
            fmp_km_data=_fmp_km(),
            yf_fund_data=yf_fund,
            yf_km_data=_yf_km(),
        )
        gate = CrossCheckGate(fmp, yf, log_dir=tmp_path)
        report = await gate.check(
            ticker="1846.HK",
            extracted_values=_FULL_EXTRACTED,
            period="FY2024",
        )
        capex = next(m for m in report.metrics if m.metric == "capex")
        assert capex.status == CrossCheckStatus.UNAVAILABLE
        assert capex.fmp_value is None
        assert capex.yfinance_value is None
        # UNAVAILABLE doesn't elevate overall status
        assert report.overall_status == CrossCheckStatus.PASS

    @pytest.mark.asyncio
    async def test_extracted_missing_for_metric_is_unavailable(self, tmp_path: Path) -> None:
        """Caller didn't supply one of the metric keys — gate marks it
        UNAVAILABLE (can't cross-check nothing) without blocking."""
        fmp, yf = _make_providers(
            fmp_fund_data=_fmp_fund(),
            fmp_km_data=_fmp_km(),
            yf_fund_data=_yf_fund(),
            yf_km_data=_yf_km(),
        )
        partial = {k: v for k, v in _FULL_EXTRACTED.items() if k != "capex"}
        gate = CrossCheckGate(fmp, yf, log_dir=tmp_path)
        report = await gate.check(ticker="1846.HK", extracted_values=partial, period="FY2024")
        capex = next(m for m in report.metrics if m.metric == "capex")
        assert capex.status == CrossCheckStatus.UNAVAILABLE
        assert capex.extracted_value is None
        assert report.overall_status == CrossCheckStatus.PASS


# ======================================================================
# Metric-specific thresholds
# ======================================================================


class TestMetricSpecificThresholds:
    @pytest.mark.asyncio
    async def test_operating_income_wider_tolerance(self, tmp_path: Path) -> None:
        """operating_income has PASS<5% (vs default 2%). 3.6% drift should
        PASS under the metric-specific threshold."""
        fmp, yf = _make_providers(
            fmp_fund_data=_fmp_fund(operating_income=114.0),  # 3.6% above extracted 110
            fmp_km_data=_fmp_km(),
            yf_fund_data=_yf_fund(operating_income=114.0),
            yf_km_data=_yf_km(),
        )
        gate = CrossCheckGate(fmp, yf, log_dir=tmp_path)
        report = await gate.check(
            ticker="1846.HK",
            extracted_values=_FULL_EXTRACTED,
            period="FY2024",
        )
        op = next(m for m in report.metrics if m.metric == "operating_income")
        # 3.6% > default PASS (2%) but < metric-specific PASS (5%) → still PASS
        assert op.status == CrossCheckStatus.PASS

    @pytest.mark.asyncio
    async def test_override_json_applied(self, tmp_path: Path) -> None:
        """Operator's env-var override should tighten net_income to 0.5%."""
        override = json.dumps({"per_metric": {"net_income": {"PASS": "0.005", "WARN": "0.02"}}})
        fmp, yf = _make_providers(
            fmp_fund_data=_fmp_fund(net_income=75.5),  # 0.67% drift
            fmp_km_data=_fmp_km(),
            yf_fund_data=_yf_fund(net_income=75.6),
            yf_km_data=_yf_km(),
        )
        gate = CrossCheckGate(fmp, yf, thresholds_override_json=override, log_dir=tmp_path)
        report = await gate.check(
            ticker="1846.HK",
            extracted_values=_FULL_EXTRACTED,
            period="FY2024",
        )
        ni = next(m for m in report.metrics if m.metric == "net_income")
        # Under stricter threshold, 0.67% drift → WARN (between 0.5% and 2%)
        assert ni.status == CrossCheckStatus.WARN


# ======================================================================
# Report persistence
# ======================================================================


class TestReportPersistence:
    @pytest.mark.asyncio
    async def test_log_file_written(self, tmp_path: Path) -> None:
        fmp, yf = _make_providers(
            fmp_fund_data=_fmp_fund(),
            fmp_km_data=_fmp_km(),
            yf_fund_data=_yf_fund(),
            yf_km_data=_yf_km(),
        )
        gate = CrossCheckGate(fmp, yf, log_dir=tmp_path)
        report = await gate.check(
            ticker="1846.HK",
            extracted_values=_FULL_EXTRACTED,
            period="FY2024",
        )
        assert report.log_path is not None
        path = Path(report.log_path)
        assert path.exists()
        # Ticker is normalised for filename safety
        assert path.name.startswith("1846-HK_")
        # Valid JSON with expected keys
        payload = json.loads(path.read_text())
        assert payload["ticker"] == "1846.HK"
        assert payload["overall_status"] == "PASS"
        assert len(payload["metrics"]) == 10

    @pytest.mark.asyncio
    async def test_log_failure_is_non_fatal(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If the log dir can't be written, the gate still returns the report."""
        # Point log_dir at a path where we make a file at the dir target
        blocker = tmp_path / "blocker"
        blocker.write_text("")  # file, not dir — mkdir will fail

        fmp, yf = _make_providers(
            fmp_fund_data=_fmp_fund(),
            fmp_km_data=_fmp_km(),
            yf_fund_data=_yf_fund(),
            yf_km_data=_yf_km(),
        )
        gate = CrossCheckGate(fmp, yf, log_dir=blocker)
        report = await gate.check(
            ticker="1846.HK",
            extracted_values=_FULL_EXTRACTED,
            period="FY2024",
        )
        assert report.log_path is None
        # The report itself still has its content
        assert report.overall_status == CrossCheckStatus.PASS


# ======================================================================
# Parallel fetch
# ======================================================================


class TestParallelFetch:
    @pytest.mark.asyncio
    async def test_all_four_providers_called_exactly_once(self, tmp_path: Path) -> None:
        fmp, yf = _make_providers(
            fmp_fund_data=_fmp_fund(),
            fmp_km_data=_fmp_km(),
            yf_fund_data=_yf_fund(),
            yf_km_data=_yf_km(),
        )
        gate = CrossCheckGate(fmp, yf, log_dir=tmp_path)
        await gate.check(
            ticker="1846.HK",
            extracted_values=_FULL_EXTRACTED,
            period="FY2024",
        )
        assert fmp.get_fundamentals.await_count == 1
        assert fmp.get_key_metrics.await_count == 1
        assert yf.get_fundamentals.await_count == 1
        assert yf.get_key_metrics.await_count == 1


# ======================================================================
# Provider errors
# ======================================================================


class TestProviderErrors:
    @pytest.mark.asyncio
    async def test_ticker_not_found_at_fmp_captured_on_report(self, tmp_path: Path) -> None:
        """FMP-side 404 shouldn't crash the gate — yfinance values still
        cross-check, FMP side reported as UNAVAILABLE for its metrics."""
        fmp, yf = _make_providers(
            fmp_fund_data=TickerNotFoundError("1846.HK not at FMP"),
            fmp_km_data=TickerNotFoundError("1846.HK not at FMP"),
            yf_fund_data=_yf_fund(),
            yf_km_data=_yf_km(),
        )
        gate = CrossCheckGate(fmp, yf, log_dir=tmp_path)
        report = await gate.check(
            ticker="1846.HK",
            extracted_values=_FULL_EXTRACTED,
            period="FY2024",
        )
        assert "fmp.fundamentals" in report.provider_errors
        assert "fmp.key_metrics" in report.provider_errors
        # yfinance side still cross-checked revenue: 580 vs 582 = 0.34% → PASS
        rev = next(m for m in report.metrics if m.metric == "revenue")
        assert rev.status == CrossCheckStatus.PASS
        assert rev.fmp_value is None
        assert rev.yfinance_value is not None

    @pytest.mark.asyncio
    async def test_both_providers_fail_yields_all_unavailable(self, tmp_path: Path) -> None:
        fmp, yf = _make_providers(
            fmp_fund_data=MarketDataError("FMP 500"),
            fmp_km_data=MarketDataError("FMP 500"),
            yf_fund_data=MarketDataError("yfinance 500"),
            yf_km_data=MarketDataError("yfinance 500"),
        )
        gate = CrossCheckGate(fmp, yf, log_dir=tmp_path)
        report = await gate.check(
            ticker="1846.HK",
            extracted_values=_FULL_EXTRACTED,
            period="FY2024",
        )
        assert all(m.status == CrossCheckStatus.UNAVAILABLE for m in report.metrics)
        # UNAVAILABLE throughout → overall PASS (can't fail what you can't check)
        assert report.overall_status == CrossCheckStatus.PASS
        assert report.blocking is False
        assert len(report.provider_errors) == 4


# ======================================================================
# Zero / edge-case inputs
# ======================================================================


class TestEdgeCases:
    @pytest.mark.asyncio
    async def test_zero_extracted_doesnt_divide_by_zero(self, tmp_path: Path) -> None:
        fmp, yf = _make_providers(
            fmp_fund_data=_fmp_fund(capex=0.1),
            fmp_km_data=_fmp_km(),
            yf_fund_data=_yf_fund(capex=0.1),
            yf_km_data=_yf_km(),
        )
        extracted = dict(_FULL_EXTRACTED)
        extracted["capex"] = Decimal("0")
        gate = CrossCheckGate(fmp, yf, log_dir=tmp_path)
        report = await gate.check(ticker="1846.HK", extracted_values=extracted, period="FY2024")
        capex = next(m for m in report.metrics if m.metric == "capex")
        # No ZeroDivisionError — scale defaults to 1 when extracted is 0
        assert capex.status != CrossCheckStatus.UNAVAILABLE
        assert capex.max_delta_pct is not None


# ======================================================================
# Sprint 4A-alpha.7 — fiscal_year parameter
# ======================================================================


def _make_period_providers(
    fmp_period_data: dict | BaseException | None = None,
    fmp_km_data: dict | BaseException | None = None,
    yf_period_data: dict | BaseException | None = None,
    yf_km_data: dict | BaseException | None = None,
) -> tuple[MagicMock, MagicMock]:
    """Build mocks exposing ``get_fundamentals_for_period`` only (the
    Sprint 4A-alpha.7 period-aware flow). ``get_fundamentals`` (legacy)
    is also defined so tests exercising the backward-compat path work."""
    fmp = MagicMock(spec=FMPProvider)
    fmp.get_fundamentals_for_period = AsyncMock(
        side_effect=fmp_period_data if isinstance(fmp_period_data, BaseException) else None,
        return_value=fmp_period_data if not isinstance(fmp_period_data, BaseException) else None,
    )
    fmp.get_fundamentals = AsyncMock(return_value={})
    fmp.get_key_metrics = AsyncMock(
        side_effect=fmp_km_data if isinstance(fmp_km_data, BaseException) else None,
        return_value=fmp_km_data if not isinstance(fmp_km_data, BaseException) else None,
    )
    yf = MagicMock(spec=YFinanceProvider)
    yf.get_fundamentals_for_period = AsyncMock(
        side_effect=yf_period_data if isinstance(yf_period_data, BaseException) else None,
        return_value=yf_period_data if not isinstance(yf_period_data, BaseException) else None,
    )
    yf.get_fundamentals = AsyncMock(return_value={})
    yf.get_key_metrics = AsyncMock(
        side_effect=yf_km_data if isinstance(yf_km_data, BaseException) else None,
        return_value=yf_km_data if not isinstance(yf_km_data, BaseException) else None,
    )
    return fmp, yf


class TestGatePeriodAware:
    @pytest.mark.asyncio
    async def test_P2_S4A_ALPHA_7_GATE_01_uses_period_method_when_year_provided(
        self, tmp_path: Path
    ) -> None:
        """Gate routes through ``get_fundamentals_for_period`` when
        ``fiscal_year`` is supplied."""
        fmp, yf = _make_period_providers(
            fmp_period_data=_fmp_fund(),
            fmp_km_data=_fmp_km(),
            yf_period_data=_yf_fund(),
            yf_km_data=_yf_km(),
        )
        gate = CrossCheckGate(fmp, yf, log_dir=tmp_path)
        report = await gate.check(
            ticker="1846.HK",
            extracted_values=_FULL_EXTRACTED,
            period="FY2024",
            fiscal_year=2024,
        )
        # Period-aware method called, legacy method NOT called.
        fmp.get_fundamentals_for_period.assert_awaited_once_with("1846.HK", 2024)
        yf.get_fundamentals_for_period.assert_awaited_once_with("1846.HK", 2024)
        fmp.get_fundamentals.assert_not_awaited()
        yf.get_fundamentals.assert_not_awaited()
        assert report.overall_status == CrossCheckStatus.PASS

    @pytest.mark.asyncio
    async def test_P2_S4A_ALPHA_7_GATE_02_uses_latest_when_no_year(
        self, tmp_path: Path
    ) -> None:
        """Backward compat — when ``fiscal_year`` omitted, legacy path
        runs and the period-aware method is not called."""
        fmp, yf = _make_providers(
            fmp_fund_data=_fmp_fund(),
            fmp_km_data=_fmp_km(),
            yf_fund_data=_yf_fund(),
            yf_km_data=_yf_km(),
        )
        fmp.get_fundamentals_for_period = AsyncMock()
        yf.get_fundamentals_for_period = AsyncMock()
        gate = CrossCheckGate(fmp, yf, log_dir=tmp_path)
        await gate.check(
            ticker="1846.HK",
            extracted_values=_FULL_EXTRACTED,
            period="FY2024",
            # No fiscal_year passed.
        )
        fmp.get_fundamentals.assert_awaited_once_with("1846.HK")
        yf.get_fundamentals.assert_awaited_once_with("1846.HK")
        fmp.get_fundamentals_for_period.assert_not_awaited()
        yf.get_fundamentals_for_period.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_P2_S4A_ALPHA_7_GATE_03_gracefully_handles_provider_none(
        self, tmp_path: Path
    ) -> None:
        """Provider returns ``None`` (no data for year) → metrics UNAVAILABLE,
        not FAIL; provider_errors records the missing-period reason."""
        fmp, yf = _make_period_providers(
            fmp_period_data=None,  # no FY2015 data
            fmp_km_data=_fmp_km(),
            yf_period_data=None,
            yf_km_data=_yf_km(),
        )
        gate = CrossCheckGate(fmp, yf, log_dir=tmp_path)
        report = await gate.check(
            ticker="1846.HK",
            extracted_values=_FULL_EXTRACTED,
            period="FY2015",
            fiscal_year=2015,
        )
        # Fundamentals metrics are UNAVAILABLE (neither source has period)
        revenue_metric = next(m for m in report.metrics if m.metric == "revenue")
        assert revenue_metric.status == CrossCheckStatus.UNAVAILABLE
        # Provider errors capture the None-result reason.
        assert "fmp.fundamentals" in report.provider_errors
        assert "2015" in report.provider_errors["fmp.fundamentals"]
        # Overall not blocking — key_metrics still present and match.
        assert not report.blocking

    @pytest.mark.asyncio
    async def test_P2_S4A_ALPHA_7_GATE_04_mixed_provider_availability(
        self, tmp_path: Path
    ) -> None:
        """One provider has period, the other doesn't — gate uses the
        one that does and marks the other's entry in provider_errors."""
        fmp, yf = _make_period_providers(
            fmp_period_data=_fmp_fund(),
            fmp_km_data=_fmp_km(),
            yf_period_data=None,  # yf lacks this period
            yf_km_data=_yf_km(),
        )
        gate = CrossCheckGate(fmp, yf, log_dir=tmp_path)
        report = await gate.check(
            ticker="1846.HK",
            extracted_values=_FULL_EXTRACTED,
            period="FY2021",
            fiscal_year=2021,
        )
        revenue_metric = next(m for m in report.metrics if m.metric == "revenue")
        # FMP value present → metric not UNAVAILABLE
        assert revenue_metric.fmp_value == Decimal("580")
        assert revenue_metric.yfinance_value is None
        # yf.fundamentals flagged in errors
        assert "yf.fundamentals" in report.provider_errors


class TestGateBackwardCompatibility:
    @pytest.mark.asyncio
    async def test_P2_S4A_ALPHA_7_BC_01_gate_works_without_fiscal_year(
        self, tmp_path: Path
    ) -> None:
        """``gate.check(ticker, extracted_values, period)`` — no fiscal_year
        kwarg — still works exactly as pre-Sprint 4A-alpha.7."""
        fmp, yf = _make_providers(
            fmp_fund_data=_fmp_fund(),
            fmp_km_data=_fmp_km(),
            yf_fund_data=_yf_fund(),
            yf_km_data=_yf_km(),
        )
        gate = CrossCheckGate(fmp, yf, log_dir=tmp_path)
        report = await gate.check(
            ticker="1846.HK",
            extracted_values=_FULL_EXTRACTED,
            period="FY2024",
        )
        assert report.overall_status == CrossCheckStatus.PASS
