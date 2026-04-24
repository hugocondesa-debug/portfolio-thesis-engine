"""Pytest fixtures for API tests.

Sets PTE_API_* env vars **before** importing the FastAPI app so the
:class:`APISettings` singleton picks them up. ``data_root`` points at
the live repo's ``data/`` directory — these are integration tests
against the EuroEyes fixture data, not pure unit tests with mocked
filesystems.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


# Set env vars BEFORE any api import (settings is a module-level singleton).
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
os.environ.setdefault("PTE_API_USER", "testuser")
os.environ.setdefault("PTE_API_PASSWORD", "testpass")
os.environ.setdefault("PTE_API_DATA_ROOT", str(_REPO_ROOT / "data"))
os.environ.setdefault("PTE_API_PTE_WORKDIR", str(_REPO_ROOT))


@pytest.fixture
def client():
    """FastAPI TestClient — re-imported per test so tweaks in dependent
    fixtures (env vars, monkeypatches) take effect."""
    from fastapi.testclient import TestClient

    from api.main import app

    return TestClient(app)


@pytest.fixture
def auth():
    """Basic Auth tuple matching the test env vars."""
    return ("testuser", "testpass")
