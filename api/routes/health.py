"""Health endpoint — no auth, used by Docker healthcheck."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter

from api import __version__
from api.schemas.responses import HealthResponse

router = APIRouter()


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    return HealthResponse(
        status="ok",
        version=__version__,
        timestamp=datetime.now(UTC),
    )
