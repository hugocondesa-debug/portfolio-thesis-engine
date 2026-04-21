"""Unit tests for storage/duckdb_repo.py."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from portfolio_thesis_engine.storage.base import StorageError
from portfolio_thesis_engine.storage.duckdb_repo import DuckDBRepository


@pytest.fixture
def repo(tmp_path: Path) -> DuckDBRepository:
    return DuckDBRepository(db_path=tmp_path / "ts.duckdb")


class TestSchemaBootstrap:
    def test_tables_created_on_init(self, repo: DuckDBRepository) -> None:
        tables = repo.query(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'main' ORDER BY table_name"
        )
        names = {r["table_name"] for r in tables}
        assert {
            "prices_eod",
            "factor_series",
            "peer_metrics_history",
            "computed_betas",
        }.issubset(names)


class TestPrices:
    def test_insert_and_query_prices(self, repo: DuckDBRepository) -> None:
        repo.insert_prices(
            [
                {
                    "ticker": "AAPL",
                    "date": date(2025, 1, 15),
                    "open": Decimal("180.00"),
                    "high": Decimal("182.00"),
                    "low": Decimal("179.00"),
                    "close": Decimal("181.50"),
                    "volume": 1_000_000,
                    "currency": "USD",
                    "source": "FMP",
                }
            ]
        )
        out = repo.query(
            "SELECT close FROM prices_eod WHERE ticker = $t",
            {"t": "AAPL"},
        )
        assert out == [{"close": Decimal("181.500000")}]

    def test_upsert_on_conflict_updates_close(self, repo: DuckDBRepository) -> None:
        row = {
            "ticker": "AAPL",
            "date": date(2025, 1, 15),
            "open": None,
            "high": None,
            "low": None,
            "close": Decimal("181.50"),
            "volume": None,
            "currency": "USD",
            "source": "FMP",
        }
        repo.insert_prices([row])
        repo.insert_prices([{**row, "close": Decimal("183.00")}])
        out = repo.query(
            "SELECT close FROM prices_eod WHERE ticker = $t AND date = $d",
            {"t": "AAPL", "d": date(2025, 1, 15)},
        )
        assert out == [{"close": Decimal("183.000000")}]

    def test_empty_list_is_noop(self, repo: DuckDBRepository) -> None:
        repo.insert_prices([])  # must not raise
        assert repo.query("SELECT COUNT(*) AS n FROM prices_eod") == [{"n": 0}]

    def test_missing_required_column_raises_storage_error(self, repo: DuckDBRepository) -> None:
        bad_row = {"ticker": "AAPL"}  # missing many required fields
        with pytest.raises(StorageError):
            repo.insert_prices([bad_row])


class TestFactorSeries:
    def test_insert_and_upsert(self, repo: DuckDBRepository) -> None:
        repo.insert_factor_series(
            [
                {
                    "factor_id": "ftse_250",
                    "date": date(2025, 1, 1),
                    "value": Decimal("12345.67"),
                    "source": "EODHD",
                }
            ]
        )
        repo.insert_factor_series(
            [
                {
                    "factor_id": "ftse_250",
                    "date": date(2025, 1, 1),
                    "value": Decimal("12400.00"),
                    "source": "EODHD",
                }
            ]
        )
        out = repo.query("SELECT value FROM factor_series")
        assert out == [{"value": Decimal("12400.000000")}]


class TestPeerMetricsHistory:
    def test_insert_with_defaults(self, repo: DuckDBRepository) -> None:
        repo.insert_peer_metrics(
            [
                {
                    "ticker": "PEER",
                    "period_label": "FY2024",
                    "metric": "revenue",
                    "value": Decimal("2500.00"),
                    "unit": "USD_m",
                    "is_adjusted": False,
                    "extracted_at": datetime(2025, 1, 15, 12, 0),
                }
            ]
        )
        out = repo.query("SELECT metric, value FROM peer_metrics_history")
        assert out == [{"metric": "revenue", "value": Decimal("2500.000000")}]


class TestComputedBetas:
    def test_insert_and_query_beta(self, repo: DuckDBRepository) -> None:
        repo.insert_betas(
            [
                {
                    "ticker": "ACME",
                    "factor_id": "ftse_250",
                    "window_months": 24,
                    "as_of_date": date(2025, 1, 15),
                    "beta": Decimal("1.123456"),
                    "r_squared": Decimal("0.78"),
                }
            ]
        )
        out = repo.query(
            "SELECT beta, r_squared FROM computed_betas WHERE ticker = $t",
            {"t": "ACME"},
        )
        assert out == [{"beta": Decimal("1.123456"), "r_squared": Decimal("0.780000")}]


class TestQueryErrors:
    def test_malformed_sql_raises_storage_error(self, repo: DuckDBRepository) -> None:
        with pytest.raises(StorageError):
            repo.query("SELECT * FROM no_such_table_ever")
