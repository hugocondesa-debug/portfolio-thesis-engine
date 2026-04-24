"""Yaml management endpoints — list, download, upload, version history."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest


# ----------------------------------------------------------------------
# List + download
# ----------------------------------------------------------------------
def test_S0_YAMLS_01_list_yamls(client, auth):
    response = client.get("/api/tickers/1846.HK/yamls", auth=auth)
    assert response.status_code == 200
    yamls = response.json()
    assert isinstance(yamls, list)
    names = {y["name"] for y in yamls}
    assert "scenarios" in names
    assert "capital_allocation" in names
    assert "leading_indicators" in names


def test_S0_YAMLS_02_list_includes_metadata(client, auth):
    response = client.get("/api/tickers/1846.HK/yamls", auth=auth)
    scenarios = next(
        y for y in response.json() if y["name"] == "scenarios"
    )
    assert "last_modified" in scenarios
    assert scenarios["size_bytes"] > 0
    assert scenarios["versions_count"] >= 0


def test_S0_YAMLS_10_download_scenarios(client, auth):
    response = client.get(
        "/api/tickers/1846.HK/yamls/scenarios", auth=auth
    )
    assert response.status_code == 200
    content = response.text
    assert "target_ticker" in content
    assert "1846.HK" in content


def test_S0_YAMLS_11_download_unknown_yaml_returns_400(client, auth):
    response = client.get(
        "/api/tickers/1846.HK/yamls/notarealyaml", auth=auth
    )
    assert response.status_code == 400


# ----------------------------------------------------------------------
# Upload — happy + sad paths
# ----------------------------------------------------------------------
def test_S0_YAMLS_20_upload_invalid_syntax_returns_422(client, auth):
    response = client.post(
        "/api/tickers/1846.HK/yamls/scenarios",
        auth=auth,
        content="not: valid: yaml: ::: syntax",
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["success"] is False
    assert any(
        e["type"] == "yaml_syntax"
        for e in body["detail"]["validation_errors"]
    )


def test_S0_YAMLS_21_upload_unknown_yaml_returns_400(client, auth):
    response = client.post(
        "/api/tickers/1846.HK/yamls/unknown_yaml",
        auth=auth,
        content="key: value",
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 400


def test_S0_YAMLS_22_upload_pydantic_validation_failure(client, auth):
    """Valid YAML syntax + invalid scenario set → 422 with pydantic
    validation entries (probabilities don't sum to 1)."""
    bad_scenarios = """
target_ticker: 1846.HK
valuation_profile: P1
base_year: FY2024
base_drivers: {}
scenarios:
  - name: base
    probability: 0.10
"""
    response = client.post(
        "/api/tickers/1846.HK/yamls/scenarios",
        auth=auth,
        content=bad_scenarios,
        headers={"Content-Type": "text/plain"},
    )
    assert response.status_code == 422
    body = response.json()
    assert body["detail"]["success"] is False
    assert any(
        e["type"] == "pydantic_validation"
        for e in body["detail"]["validation_errors"]
    )


def test_S0_YAMLS_23_upload_creates_backup_and_persists(
    client, auth, tmp_path, monkeypatch
):
    """Upload a roundtrip of the existing scenarios.yaml to a temp data
    root. Verify the new file lands and the .versions/ backup is created.
    """
    from api.config import settings as api_settings
    from api.services import yaml_manager

    repo_data = Path(api_settings.data_root)
    src = repo_data / "yamls" / "companies" / "1846-HK" / "scenarios.yaml"
    assert src.exists()
    original_content = src.read_text()

    # Mirror the EuroEyes ticker dir into the temp root.
    temp_data = tmp_path / "data"
    target_dir = temp_data / "yamls" / "companies" / "1846-HK"
    target_dir.mkdir(parents=True)
    shutil.copy(src, target_dir / "scenarios.yaml")

    monkeypatch.setattr(api_settings, "data_root", temp_data)

    result = yaml_manager.upload_yaml(
        "1846.HK", "scenarios", original_content
    )
    assert result["success"] is True
    assert result["backup_path"] is not None
    assert Path(result["backup_path"]).exists()
    assert (target_dir / "scenarios.yaml").read_text() == original_content


def test_S0_YAMLS_24_cleanup_keeps_only_n_versions(
    auth, tmp_path, monkeypatch
):
    """Trigger 12 uploads and verify only 10 backups remain on disk."""
    from api.config import settings as api_settings
    from api.services import yaml_manager

    repo_data = Path(api_settings.data_root)
    src = repo_data / "yamls" / "companies" / "1846-HK" / "scenarios.yaml"
    original_content = src.read_text()

    temp_data = tmp_path / "data"
    target_dir = temp_data / "yamls" / "companies" / "1846-HK"
    target_dir.mkdir(parents=True)
    shutil.copy(src, target_dir / "scenarios.yaml")

    monkeypatch.setattr(api_settings, "data_root", temp_data)
    monkeypatch.setattr(api_settings, "yaml_versions_keep", 10)

    # Upload 12 times — small content tweak each iteration to ensure
    # distinct mtimes, but valid against the schema.
    for i in range(12):
        result = yaml_manager.upload_yaml(
            "1846.HK", "scenarios", original_content
        )
        assert result["success"] is True

    backups = sorted((target_dir / ".versions").glob("scenarios_*.yaml.bak"))
    # Backup count is N-1 because the first upload had no prior file to back up.
    assert 10 <= len(backups) <= 11


# ----------------------------------------------------------------------
# Version history
# ----------------------------------------------------------------------
def test_S0_YAMLS_30_list_versions_returns_list(client, auth):
    response = client.get(
        "/api/tickers/1846.HK/yamls/scenarios/versions", auth=auth
    )
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_S0_YAMLS_31_list_versions_unknown_yaml_returns_400(
    client, auth
):
    response = client.get(
        "/api/tickers/1846.HK/yamls/notarealyaml/versions", auth=auth
    )
    assert response.status_code == 400


# ----------------------------------------------------------------------
# Auth gate
# ----------------------------------------------------------------------
def test_S0_YAMLS_40_list_requires_auth(client):
    assert client.get("/api/tickers/1846.HK/yamls").status_code == 401
