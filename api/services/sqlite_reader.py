"""SQLite queries for the ticker registry + peer relationships.

The registry lives at ``<data_root>/metadata.sqlite``. Tickers are
stored in **filesystem form** (``1846-HK``); this module accepts either
form on input and normalises to the on-disk shape. Output ``ticker``
fields are returned in canonical Yahoo form (``1846.HK``) so the API
contract is stable regardless of storage convention.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from api.config import settings


def _to_fs(ticker: str) -> str:
    return ticker.replace(".", "-")


def _to_yahoo(ticker: str) -> str:
    """Filesystem-form back to canonical Yahoo-style: ``1846-HK`` → ``1846.HK``.

    Heuristic: replaces the **first** ``-`` with ``.`` only when the
    ticker contains exactly one dash (typical for `<symbol>-<exchange>`
    forms). Tickers already containing a dot, or with multiple dashes,
    pass through unchanged.
    """
    if "." in ticker or ticker.count("-") != 1:
        return ticker
    return ticker.replace("-", ".", 1)


@contextmanager
def _connection() -> Iterator[sqlite3.Connection]:
    db_path = settings.data_root / "metadata.sqlite"
    if not db_path.exists():
        raise FileNotFoundError(f"SQLite database not found: {db_path}")
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def list_companies() -> list[dict[str, Any]]:
    """Return all companies, ticker output normalised to Yahoo form."""
    with _connection() as conn:
        rows = conn.execute(
            "SELECT ticker, name, profile, currency, exchange, isin "
            "FROM companies ORDER BY ticker"
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        company = dict(row)
        company["ticker"] = _to_yahoo(company["ticker"])
        out.append(company)
    return out


def get_company(ticker: str) -> dict[str, Any] | None:
    fs_ticker = _to_fs(ticker)
    with _connection() as conn:
        row = conn.execute(
            "SELECT ticker, name, profile, currency, exchange, isin "
            "FROM companies WHERE ticker = ?",
            (fs_ticker,),
        ).fetchone()
    if not row:
        return None
    company = dict(row)
    company["ticker"] = _to_yahoo(company["ticker"])
    return company


def get_company_peers(ticker: str) -> list[dict[str, Any]]:
    """Peers via SQL JOIN. Output peer tickers are Yahoo-normalised."""
    fs_ticker = _to_fs(ticker)
    with _connection() as conn:
        rows = conn.execute(
            """
            SELECT cp.peer_ticker, cp.extraction_level,
                   c.name, c.profile, c.currency, c.exchange
            FROM company_peers cp
            LEFT JOIN companies c ON c.ticker = cp.peer_ticker
            WHERE cp.ticker = ?
            ORDER BY cp.peer_ticker
            """,
            (fs_ticker,),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        peer = dict(row)
        peer["peer_ticker"] = _to_yahoo(peer["peer_ticker"])
        out.append(peer)
    return out


__all__ = ["get_company", "get_company_peers", "list_companies"]
