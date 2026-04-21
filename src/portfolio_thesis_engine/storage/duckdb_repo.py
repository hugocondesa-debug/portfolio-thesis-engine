"""DuckDB repository for analytical time series.

Single DuckDB file holds four tables:

- ``prices_eod``           — end-of-day OHLCV per ticker
- ``factor_series``        — macro/factor time series
- ``peer_metrics_history`` — peer metrics snapshotted over time
- ``computed_betas``       — cached rolling betas

Writes use ``INSERT ... ON CONFLICT`` upserts so ingestion is idempotent.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import duckdb

from portfolio_thesis_engine.shared.config import settings
from portfolio_thesis_engine.storage.base import StorageError

_SCHEMA_SQL = [
    """
    CREATE TABLE IF NOT EXISTS prices_eod (
        ticker VARCHAR NOT NULL,
        date DATE NOT NULL,
        open DECIMAL(18,6),
        high DECIMAL(18,6),
        low DECIMAL(18,6),
        close DECIMAL(18,6) NOT NULL,
        volume BIGINT,
        currency VARCHAR NOT NULL,
        source VARCHAR NOT NULL,
        PRIMARY KEY (ticker, date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS factor_series (
        factor_id VARCHAR NOT NULL,
        date DATE NOT NULL,
        value DECIMAL(18,6) NOT NULL,
        source VARCHAR,
        PRIMARY KEY (factor_id, date)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS peer_metrics_history (
        ticker VARCHAR NOT NULL,
        period_label VARCHAR NOT NULL,
        metric VARCHAR NOT NULL,
        value DECIMAL(20,6),
        unit VARCHAR,
        is_adjusted BOOLEAN DEFAULT FALSE,
        extracted_at TIMESTAMP,
        PRIMARY KEY (ticker, period_label, metric)
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS computed_betas (
        ticker VARCHAR NOT NULL,
        factor_id VARCHAR NOT NULL,
        window_months INTEGER NOT NULL,
        as_of_date DATE NOT NULL,
        beta DECIMAL(10,6) NOT NULL,
        r_squared DECIMAL(10,6),
        PRIMARY KEY (ticker, factor_id, window_months, as_of_date)
    )
    """,
]


class DuckDBRepository:
    """Time-series analytics store backed by a single DuckDB file.

    Not a :class:`Repository` subclass because the access pattern is set- and
    SQL-based rather than single-entity CRUD. Downstream callers query it via
    :meth:`query` or insert batches via the typed helpers.
    """

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (settings.data_dir / "timeseries.duckdb")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    # ------------------------------------------------------------------
    def _init_schema(self) -> None:
        with self.connect() as conn:
            for stmt in _SCHEMA_SQL:
                conn.execute(stmt)

    @contextmanager
    def connect(self) -> Iterator[duckdb.DuckDBPyConnection]:
        conn = duckdb.connect(str(self.db_path))
        try:
            yield conn
        finally:
            conn.close()

    # ------------------------------------------------------------------
    # Typed inserts
    # ------------------------------------------------------------------
    def insert_prices(self, rows: list[dict[str, Any]]) -> None:
        """Upsert EOD price rows. Keys: ticker, date, open, high, low, close,
        volume, currency, source. Missing optional columns default to NULL.
        """
        if not rows:
            return
        sql = """
            INSERT INTO prices_eod
                (ticker, date, open, high, low, close, volume, currency, source)
            VALUES ($ticker, $date, $open, $high, $low, $close,
                    $volume, $currency, $source)
            ON CONFLICT (ticker, date) DO UPDATE SET
                open=EXCLUDED.open,
                high=EXCLUDED.high,
                low=EXCLUDED.low,
                close=EXCLUDED.close,
                volume=EXCLUDED.volume,
                currency=EXCLUDED.currency,
                source=EXCLUDED.source
        """
        self._executemany(
            sql,
            rows,
            defaults={"open": None, "high": None, "low": None, "volume": None},
        )

    def insert_factor_series(self, rows: list[dict[str, Any]]) -> None:
        """Upsert factor time series rows."""
        if not rows:
            return
        sql = """
            INSERT INTO factor_series (factor_id, date, value, source)
            VALUES ($factor_id, $date, $value, $source)
            ON CONFLICT (factor_id, date) DO UPDATE SET
                value=EXCLUDED.value,
                source=EXCLUDED.source
        """
        self._executemany(sql, rows, defaults={"source": None})

    def insert_peer_metrics(self, rows: list[dict[str, Any]]) -> None:
        """Upsert peer metrics history rows."""
        if not rows:
            return
        sql = """
            INSERT INTO peer_metrics_history
                (ticker, period_label, metric, value, unit,
                 is_adjusted, extracted_at)
            VALUES ($ticker, $period_label, $metric, $value, $unit,
                    $is_adjusted, $extracted_at)
            ON CONFLICT (ticker, period_label, metric) DO UPDATE SET
                value=EXCLUDED.value,
                unit=EXCLUDED.unit,
                is_adjusted=EXCLUDED.is_adjusted,
                extracted_at=EXCLUDED.extracted_at
        """
        self._executemany(
            sql,
            rows,
            defaults={
                "value": None,
                "unit": None,
                "is_adjusted": False,
                "extracted_at": None,
            },
        )

    def insert_betas(self, rows: list[dict[str, Any]]) -> None:
        """Upsert computed beta rows."""
        if not rows:
            return
        sql = """
            INSERT INTO computed_betas
                (ticker, factor_id, window_months, as_of_date, beta, r_squared)
            VALUES ($ticker, $factor_id, $window_months, $as_of_date,
                    $beta, $r_squared)
            ON CONFLICT (ticker, factor_id, window_months, as_of_date)
            DO UPDATE SET
                beta=EXCLUDED.beta,
                r_squared=EXCLUDED.r_squared
        """
        self._executemany(sql, rows, defaults={"r_squared": None})

    # ------------------------------------------------------------------
    def _executemany(
        self,
        sql: str,
        rows: list[dict[str, Any]],
        defaults: Mapping[str, Any] | None = None,
    ) -> None:
        if not rows:
            return
        prepared = [{**(defaults or {}), **row} if defaults else row for row in rows]
        try:
            with self.connect() as conn:
                conn.executemany(sql, prepared)
        except Exception as e:
            raise StorageError(f"DuckDB insert failed: {e}") from e

    def query(self, sql: str, params: Mapping[str, Any] | None = None) -> list[dict[str, Any]]:
        """Run a SQL query and return results as ``list[dict]``."""
        try:
            with self.connect() as conn:
                result = conn.execute(sql, dict(params) if params else {}).fetchall()
                description = conn.description or []
                columns = [col[0] for col in description]
                return [dict(zip(columns, row, strict=False)) for row in result]
        except Exception as e:
            raise StorageError(f"DuckDB query failed: {e}") from e
