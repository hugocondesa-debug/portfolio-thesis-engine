"""Health endpoint — no auth required (Docker healthcheck path)."""

from __future__ import annotations


def test_S0_HEALTH_01_no_auth(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert "version" in body
    assert "timestamp" in body


def test_S0_HEALTH_02_version_matches_package(client):
    from api import __version__

    response = client.get("/api/health")
    assert response.json()["version"] == __version__
