"""Yaml management endpoints — list, download, upload, version history."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Body, HTTPException, status
from fastapi.responses import PlainTextResponse

from api.auth import AuthDep
from api.services import yaml_manager

router = APIRouter()


@router.get("/tickers/{ticker}/yamls")
async def list_yamls(ticker: str, _: AuthDep) -> list[dict[str, Any]]:
    """List the analyst-editable yamls present for ``ticker``."""
    return yaml_manager.list_available_yamls(ticker)


@router.get(
    "/tickers/{ticker}/yamls/{yaml_name}",
    response_class=PlainTextResponse,
)
async def download_yaml(
    ticker: str, yaml_name: str, _: AuthDep
) -> str:
    """Raw yaml text for the requested file."""
    return yaml_manager.read_yaml(ticker, yaml_name)


@router.post("/tickers/{ticker}/yamls/{yaml_name}")
async def upload_yaml(
    ticker: str,
    yaml_name: str,
    _: AuthDep,
    content: str = Body(..., media_type="text/plain"),
) -> dict[str, Any]:
    """Upload yaml content. 422 with structured errors on validation
    failure; 200 with backup path + new filename on success."""
    result = yaml_manager.upload_yaml(ticker, yaml_name, content)
    if not result["success"]:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=result,
        )
    return result


@router.get("/tickers/{ticker}/yamls/{yaml_name}/versions")
async def list_versions(
    ticker: str, yaml_name: str, _: AuthDep
) -> list[dict[str, Any]]:
    """Backup history for a yaml — most recent first."""
    return yaml_manager.list_yaml_versions(ticker, yaml_name)
