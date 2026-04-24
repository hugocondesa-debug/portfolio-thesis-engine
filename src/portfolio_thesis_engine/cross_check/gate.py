"""CrossCheckGate — validates extracted values against FMP + yfinance.

Usage::

    gate = CrossCheckGate(fmp, yfinance)
    report = await gate.check(
        ticker="1846.HK",
        extracted_values={"revenue": Decimal("580"), ...},
        period="FY2024",
    )
    if report.blocking:
        raise SystemExit(1)

The gate is stateless — one instance can handle multiple tickers. Logs
are persisted under ``settings.data_dir / "logs/cross_check"`` as JSON
per run.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from portfolio_thesis_engine.cross_check.base import (
    CrossCheckMetric,
    CrossCheckReport,
    CrossCheckStatus,
)
from portfolio_thesis_engine.cross_check.thresholds import (
    load_thresholds,
    thresholds_for,
)
from portfolio_thesis_engine.market_data.fmp_provider import FMPProvider
from portfolio_thesis_engine.market_data.yfinance_provider import YFinanceProvider
from portfolio_thesis_engine.shared.config import settings

# ----------------------------------------------------------------------
# Per-metric extraction functions
# ----------------------------------------------------------------------
Extractor = Callable[[dict[str, Any]], Decimal | None]


def _coerce(value: Any) -> Decimal | None:
    """Turn an arbitrary provider value into a Decimal or ``None``."""
    if value is None:
        return None
    try:
        d = Decimal(str(value))
    except Exception:  # noqa: BLE001
        return None
    # Zero is a legitimate reported value; only reject if we couldn't
    # parse. NaN-like extreme values are caught at delta time.
    return d


def _first(records: Any) -> dict[str, Any] | None:
    """Return the first record from a list, or None if empty."""
    if not isinstance(records, list) or not records:
        return None
    first = records[0]
    return first if isinstance(first, dict) else None


# --- FMP extractors ---------------------------------------------------
def _fmp_is_field(field: str) -> Extractor:
    def extract(fund: dict[str, Any]) -> Decimal | None:
        rec = _first(fund.get("income_statement"))
        return _coerce(rec.get(field)) if rec else None

    return extract


def _fmp_bs_field(field: str) -> Extractor:
    def extract(fund: dict[str, Any]) -> Decimal | None:
        rec = _first(fund.get("balance_sheet"))
        return _coerce(rec.get(field)) if rec else None

    return extract


def _fmp_cf_field(field: str) -> Extractor:
    def extract(fund: dict[str, Any]) -> Decimal | None:
        rec = _first(fund.get("cash_flow"))
        return _coerce(rec.get(field)) if rec else None

    return extract


def _fmp_km_field(field: str) -> Extractor:
    def extract(km: dict[str, Any]) -> Decimal | None:
        rec = _first(km.get("records"))
        return _coerce(rec.get(field)) if rec else None

    return extract


# --- yfinance extractors ----------------------------------------------
def _yf_is_field(field: str) -> Extractor:
    def extract(fund: dict[str, Any]) -> Decimal | None:
        rec = _first(fund.get("income_statement"))
        return _coerce(rec.get(field)) if rec else None

    return extract


def _yf_bs_field(field: str) -> Extractor:
    def extract(fund: dict[str, Any]) -> Decimal | None:
        rec = _first(fund.get("balance_sheet"))
        return _coerce(rec.get(field)) if rec else None

    return extract


def _yf_cf_field(field: str) -> Extractor:
    def extract(fund: dict[str, Any]) -> Decimal | None:
        rec = _first(fund.get("cash_flow"))
        return _coerce(rec.get(field)) if rec else None

    return extract


def _yf_km_field(field: str) -> Extractor:
    def extract(km: dict[str, Any]) -> Decimal | None:
        rec = _first(km.get("records"))
        return _coerce(rec.get(field)) if rec else None

    return extract


# ----------------------------------------------------------------------
# Metric catalogue — one entry per cross-checkable metric.
# Each extractor reads from a specific bundle (fundamentals / key-metrics).
# The bundle name is stored so the gate knows which fetched dict to pass.
# ----------------------------------------------------------------------
_FUNDAMENTALS = "fundamentals"
_KEY_METRICS = "key_metrics"


_METRIC_CATALOGUE: dict[str, tuple[str, Extractor, str, Extractor]] = {
    # metric → (fmp_bundle, fmp_extractor, yf_bundle, yf_extractor)
    "revenue": (
        _FUNDAMENTALS,
        _fmp_is_field("revenue"),
        _FUNDAMENTALS,
        _yf_is_field("Total Revenue"),
    ),
    "operating_income": (
        _FUNDAMENTALS,
        _fmp_is_field("operatingIncome"),
        _FUNDAMENTALS,
        _yf_is_field("Operating Income"),
    ),
    "net_income": (
        _FUNDAMENTALS,
        _fmp_is_field("netIncome"),
        _FUNDAMENTALS,
        _yf_is_field("Net Income"),
    ),
    "total_assets": (
        _FUNDAMENTALS,
        _fmp_bs_field("totalAssets"),
        _FUNDAMENTALS,
        _yf_bs_field("Total Assets"),
    ),
    "total_equity": (
        _FUNDAMENTALS,
        _fmp_bs_field("totalStockholdersEquity"),
        _FUNDAMENTALS,
        _yf_bs_field("Stockholders Equity"),
    ),
    "cash": (
        _FUNDAMENTALS,
        _fmp_bs_field("cashAndCashEquivalents"),
        _FUNDAMENTALS,
        _yf_bs_field("Cash And Cash Equivalents"),
    ),
    "operating_cash_flow": (
        _FUNDAMENTALS,
        _fmp_cf_field("operatingCashFlow"),
        _FUNDAMENTALS,
        _yf_cf_field("Operating Cash Flow"),
    ),
    "capex": (
        _FUNDAMENTALS,
        _fmp_cf_field("capitalExpenditure"),
        _FUNDAMENTALS,
        _yf_cf_field("Capital Expenditure"),
    ),
    "shares_outstanding": (
        _KEY_METRICS,
        _fmp_km_field("sharesOutstanding"),
        _KEY_METRICS,
        _yf_km_field("sharesOutstanding"),
    ),
    "market_cap": (
        _KEY_METRICS,
        _fmp_km_field("marketCap"),
        _KEY_METRICS,
        _yf_km_field("marketCap"),
    ),
}


# ----------------------------------------------------------------------
# Status precedence for overall roll-up
# ----------------------------------------------------------------------
_STATUS_PRIORITY: dict[CrossCheckStatus, int] = {
    CrossCheckStatus.FAIL: 5,
    CrossCheckStatus.SOURCES_DISAGREE: 4,
    CrossCheckStatus.WARN: 3,
    CrossCheckStatus.PASS: 1,
    # UNAVAILABLE is neutral — doesn't elevate overall status
    CrossCheckStatus.UNAVAILABLE: 0,
}


def _worst_status(
    metrics: list[CrossCheckMetric],
) -> CrossCheckStatus:
    contenders = [m.status for m in metrics if m.status != CrossCheckStatus.UNAVAILABLE]
    if not contenders:
        return CrossCheckStatus.PASS
    return max(contenders, key=lambda s: _STATUS_PRIORITY[s])


# ======================================================================
# Gate
# ======================================================================


class CrossCheckGate:
    """Validates extracted values against FMP + yfinance."""

    def __init__(
        self,
        fmp: FMPProvider,
        yfinance: YFinanceProvider,
        thresholds_override_json: str | None = None,
        log_dir: Path | None = None,
    ) -> None:
        self.fmp = fmp
        self.yfinance = yfinance
        self.defaults, self.per_metric = load_thresholds(
            thresholds_override_json
            if thresholds_override_json is not None
            else settings.cross_check_thresholds_json
        )
        self.log_dir = log_dir or (settings.data_dir / "logs" / "cross_check")

    # ------------------------------------------------------------------
    async def check(
        self,
        ticker: str,
        extracted_values: dict[str, Decimal],
        period: str,
        fiscal_year: int | None = None,
    ) -> CrossCheckReport:
        """Run the check end-to-end. Never raises for network failures —
        falls back to UNAVAILABLE and records the error on the report.

        Sprint 4A-alpha.7 — when ``fiscal_year`` is provided, the gate
        uses the period-aware provider methods so the comparison is
        against the correct historical year instead of the latest
        annual snapshot. Omit (or pass ``None``) for the legacy
        latest-annual path (preserved for peers / historical analysis).
        """
        if fiscal_year is not None:
            fmp_data, yf_data, provider_errors = await self._fetch_all_for_period(
                ticker, fiscal_year
            )
        else:
            fmp_data, yf_data, provider_errors = await self._fetch_all(ticker)

        metrics: list[CrossCheckMetric] = []
        for metric_name in _METRIC_CATALOGUE:
            metric = self._check_metric(
                metric_name=metric_name,
                extracted=extracted_values.get(metric_name),
                fmp_data=fmp_data,
                yf_data=yf_data,
            )
            metrics.append(metric)

        overall = _worst_status(metrics)
        blocking = overall == CrossCheckStatus.FAIL
        report = CrossCheckReport(
            ticker=ticker,
            period=period,
            metrics=metrics,
            overall_status=overall,
            blocking=blocking,
            generated_at=datetime.now(UTC),
            provider_errors=provider_errors,
        )
        log_path = self._persist_log(report)
        report.log_path = str(log_path) if log_path else None
        return report

    # ------------------------------------------------------------------
    async def _fetch_all(
        self, ticker: str
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
        dict[str, str],
    ]:
        """Fetch FMP + yfinance bundles in parallel.

        Per-provider errors are captured (not raised) so one flaky source
        doesn't tear down the whole cross-check.
        """
        fmp_jobs = [
            self.fmp.get_fundamentals(ticker),
            self.fmp.get_key_metrics(ticker),
        ]
        yf_jobs = [
            self.yfinance.get_fundamentals(ticker),
            self.yfinance.get_key_metrics(ticker),
        ]
        raw = await asyncio.gather(*fmp_jobs, *yf_jobs, return_exceptions=True)

        errors: dict[str, str] = {}
        fmp_data: dict[str, dict[str, Any]] = {}
        yf_data: dict[str, dict[str, Any]] = {}

        labels = ("fmp.fundamentals", "fmp.key_metrics", "yf.fundamentals", "yf.key_metrics")
        bundles_by_label = {
            "fmp.fundamentals": (_FUNDAMENTALS, fmp_data),
            "fmp.key_metrics": (_KEY_METRICS, fmp_data),
            "yf.fundamentals": (_FUNDAMENTALS, yf_data),
            "yf.key_metrics": (_KEY_METRICS, yf_data),
        }
        for label, result in zip(labels, raw, strict=True):
            bundle, target = bundles_by_label[label]
            if isinstance(result, BaseException):
                # TickerNotFound / MarketDataError → capture, leave bundle empty
                errors[label] = f"{type(result).__name__}: {result}"
                target[bundle] = {}
            elif isinstance(result, dict):
                target[bundle] = result
            else:
                target[bundle] = {}
        return fmp_data, yf_data, errors

    # ------------------------------------------------------------------
    async def _fetch_all_for_period(
        self, ticker: str, fiscal_year: int
    ) -> tuple[
        dict[str, dict[str, Any]],
        dict[str, dict[str, Any]],
        dict[str, str],
    ]:
        """Sprint 4A-alpha.7 — period-aware fetch.

        Uses :meth:`MarketDataProvider.get_fundamentals_for_period` for
        IS/BS/CF (filtered to ``fiscal_year``) but keeps
        :meth:`get_key_metrics` as-is. Key metrics are TTM-current
        (market cap, shares outstanding) and are intentionally
        period-agnostic — re-using the existing helper avoids false
        UNAVAILABLE markers for market-data-only metrics.

        A provider returning ``None`` (no data for the year) is captured
        as an error entry and the bundle is left empty; the gate then
        marks affected metrics UNAVAILABLE via the neutral status path.
        """
        fmp_jobs = [
            self.fmp.get_fundamentals_for_period(ticker, fiscal_year),
            self.fmp.get_key_metrics(ticker),
        ]
        yf_jobs = [
            self.yfinance.get_fundamentals_for_period(ticker, fiscal_year),
            self.yfinance.get_key_metrics(ticker),
        ]
        raw = await asyncio.gather(*fmp_jobs, *yf_jobs, return_exceptions=True)

        errors: dict[str, str] = {}
        fmp_data: dict[str, dict[str, Any]] = {}
        yf_data: dict[str, dict[str, Any]] = {}

        labels = (
            "fmp.fundamentals",
            "fmp.key_metrics",
            "yf.fundamentals",
            "yf.key_metrics",
        )
        bundles_by_label = {
            "fmp.fundamentals": (_FUNDAMENTALS, fmp_data),
            "fmp.key_metrics": (_KEY_METRICS, fmp_data),
            "yf.fundamentals": (_FUNDAMENTALS, yf_data),
            "yf.key_metrics": (_KEY_METRICS, yf_data),
        }
        for label, result in zip(labels, raw, strict=True):
            bundle, target = bundles_by_label[label]
            if isinstance(result, BaseException):
                errors[label] = f"{type(result).__name__}: {result}"
                target[bundle] = {}
            elif result is None:
                errors[label] = (
                    f"Period {fiscal_year} unavailable from provider"
                )
                target[bundle] = {}
            elif isinstance(result, dict):
                target[bundle] = result
            else:
                target[bundle] = {}
        return fmp_data, yf_data, errors

    # ------------------------------------------------------------------
    def _check_metric(
        self,
        *,
        metric_name: str,
        extracted: Decimal | None,
        fmp_data: dict[str, dict[str, Any]],
        yf_data: dict[str, dict[str, Any]],
    ) -> CrossCheckMetric:
        fmp_bundle, fmp_extract, yf_bundle, yf_extract = _METRIC_CATALOGUE[metric_name]
        fmp_value = fmp_extract(fmp_data.get(fmp_bundle) or {})
        yf_value = yf_extract(yf_data.get(yf_bundle) or {})

        notes_parts: list[str] = []

        # No external reference → UNAVAILABLE regardless of extracted value
        if fmp_value is None and yf_value is None:
            return CrossCheckMetric(
                metric=metric_name,
                extracted_value=extracted,
                fmp_value=None,
                yfinance_value=None,
                max_delta_pct=None,
                status=CrossCheckStatus.UNAVAILABLE,
                notes="Neither FMP nor yfinance published this metric.",
            )

        if extracted is None:
            return CrossCheckMetric(
                metric=metric_name,
                extracted_value=None,
                fmp_value=fmp_value,
                yfinance_value=yf_value,
                max_delta_pct=None,
                status=CrossCheckStatus.UNAVAILABLE,
                notes="Extraction did not produce this metric.",
            )

        # Compute delta vs each available source
        deltas: list[Decimal] = []
        scale = abs(extracted) if extracted else Decimal("1")
        if scale == 0:
            scale = Decimal("1")
        if fmp_value is not None:
            deltas.append(abs(extracted - fmp_value) / scale)
        if yf_value is not None:
            deltas.append(abs(extracted - yf_value) / scale)
        max_delta = max(deltas) if deltas else None

        # Sources-disagree check — only meaningful when both sources present
        sources_disagree = False
        if fmp_value is not None and yf_value is not None:
            src_scale = max(abs(fmp_value), abs(yf_value), Decimal("1"))
            src_diff = abs(fmp_value - yf_value) / src_scale
            if src_diff > self.defaults.get("sources_disagree", Decimal("0.05")):
                sources_disagree = True
                notes_parts.append(f"FMP and yfinance differ by {src_diff:.1%} between themselves")

        # Threshold lookup for this metric
        tol = thresholds_for(metric_name, self.defaults, self.per_metric)
        pass_threshold = tol.get("PASS", Decimal("0.02"))
        warn_threshold = tol.get("WARN", Decimal("0.10"))

        assert max_delta is not None  # both-None case handled above
        if max_delta < pass_threshold:
            status = CrossCheckStatus.PASS
        elif max_delta < warn_threshold:
            status = CrossCheckStatus.WARN
        else:
            status = CrossCheckStatus.FAIL

        # SOURCES_DISAGREE wins over WARN (cross-source inconsistency is
        # more diagnostic than a mild single-source drift) but FAIL still
        # dominates both.
        if sources_disagree and status == CrossCheckStatus.WARN:
            status = CrossCheckStatus.SOURCES_DISAGREE

        notes_parts.append(
            f"Δ={max_delta:.2%} (threshold PASS<{pass_threshold:.1%}, WARN<{warn_threshold:.1%})"
        )
        return CrossCheckMetric(
            metric=metric_name,
            extracted_value=extracted,
            fmp_value=fmp_value,
            yfinance_value=yf_value,
            max_delta_pct=max_delta,
            status=status,
            notes="; ".join(notes_parts),
        )

    # ------------------------------------------------------------------
    def _persist_log(self, report: CrossCheckReport) -> Path | None:
        """Write the report as JSON under ``log_dir``. Returns the path
        written, or ``None`` on I/O failure (we never let logging kill
        the gate)."""
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return None
        timestamp = report.generated_at.strftime("%Y%m%d_%H%M%S")
        filename = f"{report.ticker.replace('.', '-')}_{timestamp}.json"
        path = self.log_dir / filename
        try:
            path.write_text(_serialise_report(report), encoding="utf-8")
        except OSError:
            return None
        return path


def _serialise_report(report: CrossCheckReport) -> str:
    """Turn the report into a human-readable JSON string."""

    # Clone into primitives so Decimal / datetime serialise cleanly.
    def _encode(obj: Any) -> Any:
        if isinstance(obj, Decimal):
            return str(obj)
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, CrossCheckStatus):
            return obj.value
        raise TypeError(f"Unserialisable: {type(obj).__name__}")

    payload = asdict(report)
    return json.dumps(payload, default=_encode, indent=2, sort_keys=False)
