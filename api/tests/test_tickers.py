"""Ticker endpoints — discovery + per-ticker artefacts."""

from __future__ import annotations


# ----------------------------------------------------------------------
# Auth
# ----------------------------------------------------------------------
def test_S0_TICKERS_01_list_requires_auth(client):
    assert client.get("/api/tickers").status_code == 401


def test_S0_TICKERS_02_canonical_requires_auth(client):
    assert client.get("/api/tickers/1846.HK/canonical").status_code == 401


def test_S0_TICKERS_03_invalid_credentials_rejected(client):
    response = client.get("/api/tickers", auth=("wrong", "wrong"))
    assert response.status_code == 401


# ----------------------------------------------------------------------
# List + detail
# ----------------------------------------------------------------------
def test_S0_TICKERS_10_list_returns_euroeyes(client, auth):
    response = client.get("/api/tickers", auth=auth)
    assert response.status_code == 200
    tickers = response.json()
    assert isinstance(tickers, list)
    euroeyes = next((t for t in tickers if t["ticker"] == "1846.HK"), None)
    assert euroeyes is not None
    assert euroeyes["profile"] == "P1"
    # Currency enriched from canonical state when SQLite has placeholders.
    assert euroeyes["currency"] in {"HKD", "?"}


def test_S0_TICKERS_11_list_includes_artifact_flags(client, auth):
    response = client.get("/api/tickers", auth=auth)
    euroeyes = next(t for t in response.json() if t["ticker"] == "1846.HK")
    # All artefacts exist in the repo fixture data.
    assert euroeyes["has_extraction"] is True
    assert euroeyes["has_forecast"] is True
    assert euroeyes["has_ficha"] is True


def test_S0_TICKERS_12_get_detail_known_ticker(client, auth):
    response = client.get("/api/tickers/1846.HK", auth=auth)
    assert response.status_code == 200
    body = response.json()
    assert body["ticker"] == "1846.HK"
    assert body["profile"] == "P1"


def test_S0_TICKERS_13_get_detail_unknown_returns_404(client, auth):
    response = client.get("/api/tickers/UNKNOWN.US", auth=auth)
    assert response.status_code == 404


# ----------------------------------------------------------------------
# Artefact endpoints
# ----------------------------------------------------------------------
def test_S0_TICKERS_20_canonical_loads(client, auth):
    response = client.get("/api/tickers/1846.HK/canonical", auth=auth)
    assert response.status_code == 200
    body = response.json()
    # Canonical state has either ticker (Phase 1.5) or extraction_id at top.
    assert "extraction_id" in body or "identity" in body


def test_S0_TICKERS_21_valuation_loads(client, auth):
    response = client.get("/api/tickers/1846.HK/valuation", auth=auth)
    assert response.status_code == 200


def test_S0_TICKERS_22_ficha_loads(client, auth):
    response = client.get("/api/tickers/1846.HK/ficha", auth=auth)
    assert response.status_code == 200


def test_S0_TICKERS_23_forecast_loads(client, auth):
    response = client.get("/api/tickers/1846.HK/forecast", auth=auth)
    assert response.status_code == 200
    body = response.json()
    assert "projections" in body
    assert len(body["projections"]) >= 1


def test_S0_TICKERS_24_peers_combines_yaml_and_sqlite(client, auth):
    response = client.get("/api/tickers/1846.HK/peers", auth=auth)
    assert response.status_code == 200
    body = response.json()
    assert "yaml" in body
    assert "sqlite_peers" in body


def test_S0_TICKERS_25_cross_check_loads(client, auth):
    response = client.get("/api/tickers/1846.HK/cross-check", auth=auth)
    assert response.status_code == 200


def test_S0_TICKERS_26_pipeline_runs_returns_list(client, auth):
    response = client.get("/api/tickers/1846.HK/pipeline-runs", auth=auth)
    assert response.status_code == 200
    assert isinstance(response.json(), list)
