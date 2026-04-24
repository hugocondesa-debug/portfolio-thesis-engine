"""Ticker discovery + per-ticker artefact endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException, status

from api.auth import AuthDep
from api.schemas.responses import TickerDetail, TickerSummary
from api.services import filesystem_reader as fs
from api.services import sqlite_reader as db

router = APIRouter()


def _enrich_with_canonical(ticker: str, base: dict[str, Any]) -> dict[str, Any]:
    """Overlay placeholder SQLite columns with values from the
    canonical state's ``identity`` block when available. The SQLite
    registry currently stores `?` for currency/exchange on freshly
    ingested tickers; the canonical state has the real values.
    """
    identity = fs.canonical_identity(ticker)
    if identity is None:
        return base
    enriched = dict(base)
    if base.get("currency") in (None, "", "?"):
        currency = identity.get("reporting_currency")
        if isinstance(currency, dict):
            currency = currency.get("value") or currency.get("code")
        if currency:
            enriched["currency"] = str(currency)
    if base.get("exchange") in (None, "", "?"):
        exchange = identity.get("exchange")
        if exchange:
            enriched["exchange"] = str(exchange)
    if base.get("name") in (None, "", "?", ticker, ticker.replace(".", "-")):
        name = identity.get("name") or identity.get("legal_name")
        if name:
            enriched["name"] = str(name)
    if not enriched.get("isin"):
        isin = identity.get("isin")
        if isin:
            enriched["isin"] = str(isin)
    return enriched


@router.get("/tickers", response_model=list[TickerSummary])
async def list_tickers(_: AuthDep) -> list[TickerSummary]:
    """All tickers with artefact-availability summary."""
    companies = db.list_companies()
    summaries: list[TickerSummary] = []
    for company in companies:
        ticker = company["ticker"]
        enriched = _enrich_with_canonical(ticker, company)
        try:
            mtimes = fs.latest_artifact_metadata(ticker)
        except Exception:
            mtimes = {}
        summaries.append(
            TickerSummary(
                ticker=ticker,
                name=enriched.get("name") or ticker,
                profile=enriched.get("profile") or "P1",
                currency=enriched.get("currency") or "?",
                exchange=enriched.get("exchange") or "?",
                isin=enriched.get("isin"),
                has_extraction=mtimes.get("extraction") is not None,
                has_valuation=mtimes.get("valuation") is not None,
                has_forecast=mtimes.get("forecast") is not None,
                has_ficha=mtimes.get("ficha") is not None,
                latest_extraction_at=mtimes.get("extraction"),
                latest_valuation_at=mtimes.get("valuation"),
                latest_forecast_at=mtimes.get("forecast"),
            )
        )
    return summaries


@router.get("/tickers/{ticker}", response_model=TickerDetail)
async def get_ticker(ticker: str, _: AuthDep) -> TickerDetail:
    company = db.get_company(ticker)
    if not company:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Ticker not found: {ticker}",
        )
    enriched = _enrich_with_canonical(ticker, company)
    return TickerDetail(
        ticker=enriched["ticker"],
        name=enriched.get("name") or ticker,
        profile=enriched.get("profile") or "P1",
        currency=enriched.get("currency") or "?",
        exchange=enriched.get("exchange") or "?",
        isin=enriched.get("isin"),
    )


@router.get("/tickers/{ticker}/canonical")
async def get_canonical(ticker: str, _: AuthDep) -> dict[str, Any]:
    return fs.load_canonical(ticker)


@router.get("/tickers/{ticker}/valuation")
async def get_valuation(ticker: str, _: AuthDep) -> dict[str, Any]:
    return fs.load_valuation(ticker)


@router.get("/tickers/{ticker}/ficha")
async def get_ficha(ticker: str, _: AuthDep) -> dict[str, Any]:
    return fs.load_ficha(ticker)


@router.get("/tickers/{ticker}/forecast")
async def get_forecast(ticker: str, _: AuthDep) -> dict[str, Any]:
    return fs.load_forecast(ticker)


@router.get("/tickers/{ticker}/peers")
async def get_peers(ticker: str, _: AuthDep) -> dict[str, Any]:
    """Peers — combines yaml file + sqlite registry enrichment."""
    try:
        peers_yaml = fs.load_peers_yaml(ticker)
    except FileNotFoundError:
        peers_yaml = {"peers": []}
    sqlite_peers = db.get_company_peers(ticker)
    return {
        "ticker": ticker,
        "yaml": peers_yaml,
        "sqlite_peers": sqlite_peers,
    }


@router.get("/tickers/{ticker}/cross-check")
async def get_cross_check(ticker: str, _: AuthDep) -> dict[str, Any]:
    return fs.load_latest_cross_check(ticker)


@router.get("/tickers/{ticker}/pipeline-runs")
async def get_pipeline_runs(
    ticker: str, _: AuthDep, limit: int = 20
) -> list[dict[str, Any]]:
    return fs.list_pipeline_runs(ticker, limit=limit)
