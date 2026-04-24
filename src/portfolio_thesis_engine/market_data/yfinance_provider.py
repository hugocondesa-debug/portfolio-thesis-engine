"""yfinance implementation of :class:`MarketDataProvider`.

Uses the :mod:`yfinance` library, which scrapes Yahoo Finance. Good for
cross-checks against FMP and for tickers FMP doesn't cover (some
international listings).

Limitations (documented here, and worth re-reading before enabling this
provider in production):

- **Scraping-based.** Depends on Yahoo Finance's HTML / JSON APIs which
  are not officially documented or supported. Breaks when Yahoo changes
  its frontend.
- **Rate limiting is implicit.** No documented quota; aggressive usage
  invites 429s and IP bans. Keep call rates conservative.
- **No authentication.** Any caller can hit Yahoo; no API key means no
  rate-limit tiers.
- **Use at your own risk.** No SLA, no stability guarantees.

yfinance is synchronous; every async method wraps the blocking call with
:func:`asyncio.to_thread` so this provider composes with the rest of our
async pipeline.
"""

from __future__ import annotations

import asyncio
import re
from typing import Any

import yfinance as yf

from portfolio_thesis_engine.market_data.base import (
    MarketDataError,
    MarketDataProvider,
    TickerNotFoundError,
)

_TICKER_RE = re.compile(r"^[A-Z0-9._\-\^=]{1,20}$", re.IGNORECASE)


class YFinanceProvider(MarketDataProvider):
    """Yahoo Finance via :mod:`yfinance`. No API key required."""

    def __init__(self) -> None:  # noqa: D401 (no kwargs on purpose)
        pass

    # ------------------------------------------------------------------
    def validate_ticker(self, ticker: str) -> bool:
        """Cheap shape check. yfinance is permissive — accepts ``^GSPC``
        style indices so the regex is slightly wider than FMP's."""
        return bool(ticker) and bool(_TICKER_RE.match(ticker))

    # ------------------------------------------------------------------
    async def get_quote(self, ticker: str) -> dict[str, Any]:
        def _sync() -> dict[str, Any]:
            try:
                t = yf.Ticker(ticker)
                info = t.info or {}
            except Exception as e:  # noqa: BLE001 — yfinance wraps many error types
                raise MarketDataError(f"yfinance quote failed for {ticker!r}: {e}") from e

            price = info.get("currentPrice") or info.get("regularMarketPrice")
            symbol = info.get("symbol")
            if not symbol or price is None:
                raise TickerNotFoundError(f"yfinance: no quote for {ticker!r}")
            return {
                "symbol": symbol,
                "name": info.get("shortName") or info.get("longName"),
                "price": price,
                "currency": info.get("currency"),
                "marketCap": info.get("marketCap"),
                "volume": info.get("volume") or info.get("regularMarketVolume"),
                "previousClose": info.get("previousClose"),
                "dayHigh": info.get("dayHigh"),
                "dayLow": info.get("dayLow"),
            }

        return await asyncio.to_thread(_sync)

    # ------------------------------------------------------------------
    async def get_price_history(
        self,
        ticker: str,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        def _sync() -> list[dict[str, Any]]:
            try:
                t = yf.Ticker(ticker)
                df = t.history(start=start_date, end=end_date, auto_adjust=False)
            except Exception as e:  # noqa: BLE001
                raise MarketDataError(f"yfinance history failed for {ticker!r}: {e}") from e

            if df is None or df.empty:
                raise TickerNotFoundError(
                    f"yfinance: no history for {ticker!r} in {start_date}..{end_date}"
                )
            rows: list[dict[str, Any]] = []
            for idx, row in df.iterrows():
                rows.append(
                    {
                        "date": idx.date().isoformat(),
                        "open": float(row["Open"]),
                        "high": float(row["High"]),
                        "low": float(row["Low"]),
                        "close": float(row["Close"]),
                        "volume": int(row["Volume"]),
                    }
                )
            return rows

        return await asyncio.to_thread(_sync)

    # ------------------------------------------------------------------
    async def get_fundamentals(self, ticker: str) -> dict[str, Any]:
        def _sync() -> dict[str, Any]:
            try:
                t = yf.Ticker(ticker)
                income = _df_to_records(t.financials)
                balance = _df_to_records(t.balance_sheet)
                cashflow = _df_to_records(t.cashflow)
            except Exception as e:  # noqa: BLE001
                raise MarketDataError(f"yfinance fundamentals failed for {ticker!r}: {e}") from e
            if not (income or balance or cashflow):
                raise TickerNotFoundError(f"yfinance: no fundamentals for {ticker!r}")
            return {
                "income_statement": income,
                "balance_sheet": balance,
                "cash_flow": cashflow,
            }

        return await asyncio.to_thread(_sync)

    async def get_fundamentals_for_period(
        self,
        ticker: str,
        fiscal_year: int,
    ) -> dict[str, Any] | None:
        """Sprint 4A-alpha.7 — period-aware fundamentals via yfinance.

        yfinance ``Ticker.financials`` / ``.balance_sheet`` / ``.cashflow``
        return DataFrames with :class:`pandas.Timestamp` columns whose
        ``.year`` attribute carries the fiscal year (calendar-year
        reporters map directly; non-calendar reporters map by the year
        the FY ends in — e.g. FY ending June 2024 → ``.year == 2024``).

        Returns a bundle shaped like :meth:`get_fundamentals` but with
        single-element lists (bundle-shape compatibility with the
        cross-check gate extractors). ``None`` when no DataFrame has a
        column matching the year.
        """

        def _sync() -> dict[str, Any] | None:
            try:
                t = yf.Ticker(ticker)
                income = _df_to_period_record(t.financials, fiscal_year)
                balance = _df_to_period_record(t.balance_sheet, fiscal_year)
                cashflow = _df_to_period_record(t.cashflow, fiscal_year)
            except Exception as e:  # noqa: BLE001
                raise MarketDataError(
                    f"yfinance fundamentals_for_period failed for "
                    f"{ticker!r} / {fiscal_year}: {e}"
                ) from e

            if income is None and balance is None and cashflow is None:
                return None

            return {
                "income_statement": [income] if income is not None else [],
                "balance_sheet": [balance] if balance is not None else [],
                "cash_flow": [cashflow] if cashflow is not None else [],
            }

        return await asyncio.to_thread(_sync)

    # ------------------------------------------------------------------
    async def get_key_metrics(self, ticker: str) -> dict[str, Any]:
        """Derive a compact metrics record from :attr:`Ticker.info`."""

        def _sync() -> dict[str, Any]:
            try:
                t = yf.Ticker(ticker)
                info = t.info or {}
            except Exception as e:  # noqa: BLE001
                raise MarketDataError(f"yfinance key-metrics failed for {ticker!r}: {e}") from e
            if not info.get("symbol"):
                raise TickerNotFoundError(f"yfinance: no key metrics for {ticker!r}")
            record = {
                "symbol": info.get("symbol"),
                "trailingPE": info.get("trailingPE"),
                "forwardPE": info.get("forwardPE"),
                "priceToBook": info.get("priceToBook"),
                "priceToSalesTrailing12Months": info.get("priceToSalesTrailing12Months"),
                "enterpriseValue": info.get("enterpriseValue"),
                "enterpriseToRevenue": info.get("enterpriseToRevenue"),
                "enterpriseToEbitda": info.get("enterpriseToEbitda"),
                "dividendYield": info.get("dividendYield"),
                "beta": info.get("beta"),
                # Exposed for the cross-check gate (Sprint 5 Phase 1).
                "sharesOutstanding": info.get("sharesOutstanding"),
                "marketCap": info.get("marketCap"),
            }
            return {"records": [record]}

        return await asyncio.to_thread(_sync)

    # ------------------------------------------------------------------
    async def search_tickers(self, query: str) -> list[dict[str, Any]]:
        def _sync() -> list[dict[str, Any]]:
            try:
                hits = yf.Search(query, max_results=20).quotes
            except Exception as e:  # noqa: BLE001
                raise MarketDataError(f"yfinance search failed for {query!r}: {e}") from e
            if not isinstance(hits, list):
                return []
            return [
                {
                    "symbol": h.get("symbol"),
                    "name": h.get("shortname") or h.get("longname"),
                    "exchange": h.get("exchange"),
                    "quoteType": h.get("quoteType"),
                }
                for h in hits
                if h.get("symbol")
            ]

        return await asyncio.to_thread(_sync)


# ----------------------------------------------------------------------
def _df_to_records(df: Any) -> list[dict[str, Any]]:
    """Convert a yfinance financials-style DataFrame to ``list[dict]``.

    yfinance returns periods as columns and line items as rows. We
    transpose: one dict per period with ``{"period": ISO-date, ...items}``.
    Returns ``[]`` for a missing or empty DataFrame (some tickers, e.g.
    indices, have no financials).
    """
    if df is None:
        return []
    try:
        if df.empty:
            return []
    except AttributeError:
        return []

    records: list[dict[str, Any]] = []
    for col in df.columns:
        period_label = col.date().isoformat() if hasattr(col, "date") else str(col)
        row: dict[str, Any] = {"period": period_label}
        for item, value in df[col].items():
            # Cast numpy scalars to python native; skip NaN
            try:
                if value != value:  # NaN != NaN
                    continue
            except Exception:  # noqa: BLE001
                pass
            row[str(item)] = float(value) if hasattr(value, "__float__") else value
        records.append(row)
    return records


def _df_to_period_record(df: Any, fiscal_year: int) -> dict[str, Any] | None:
    """Sprint 4A-alpha.7 — return a single period's record from a
    yfinance DataFrame, filtered by ``fiscal_year``.

    Matches the first column whose ``.year`` attribute equals
    ``fiscal_year``. Returns ``None`` when the DataFrame is empty,
    missing, or has no matching column. Output shape matches a single
    element of :func:`_df_to_records` so downstream extractors can use
    ``records[0]`` uniformly.
    """
    if df is None:
        return None
    try:
        if df.empty:
            return None
    except AttributeError:
        return None

    matching_col = None
    for col in df.columns:
        col_year = getattr(col, "year", None)
        if col_year == fiscal_year:
            matching_col = col
            break
    if matching_col is None:
        return None

    period_label = (
        matching_col.date().isoformat()
        if hasattr(matching_col, "date")
        else str(matching_col)
    )
    row: dict[str, Any] = {"period": period_label}
    for item, value in df[matching_col].items():
        try:
            if value != value:  # NaN != NaN
                continue
        except Exception:  # noqa: BLE001
            pass
        row[str(item)] = float(value) if hasattr(value, "__float__") else value
    return row
