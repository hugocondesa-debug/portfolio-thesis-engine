"""Pipeline trigger + status endpoints."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status

from api.auth import AuthDep
from api.schemas.responses import (
    PipelineRunRequest,
    PipelineRunResponse,
    PipelineRunStatus,
)
from api.services import pipeline_runner

router = APIRouter()


@router.post(
    "/pipelines/{ticker}/run",
    response_model=PipelineRunResponse,
)
async def trigger_full_pipeline(
    ticker: str,
    request: PipelineRunRequest,
    _: AuthDep,
) -> PipelineRunResponse:
    """Spawn ``pte process <ticker>`` in the background."""
    meta = await pipeline_runner.trigger_pipeline(
        ticker=ticker,
        command="process",
        extraction_path=request.extraction_path,
        base_period=request.base_period,
        skip_cross_check=request.skip_cross_check,
    )
    return PipelineRunResponse(**meta)


@router.post(
    "/pipelines/{ticker}/forecast",
    response_model=PipelineRunResponse,
)
async def trigger_forecast(ticker: str, _: AuthDep) -> PipelineRunResponse:
    meta = await pipeline_runner.trigger_pipeline(
        ticker=ticker, command="forecast"
    )
    return PipelineRunResponse(**meta)


@router.post(
    "/pipelines/{ticker}/valuation",
    response_model=PipelineRunResponse,
)
async def trigger_valuation(ticker: str, _: AuthDep) -> PipelineRunResponse:
    meta = await pipeline_runner.trigger_pipeline(
        ticker=ticker, command="valuation"
    )
    return PipelineRunResponse(**meta)


@router.get(
    "/pipelines/{ticker}/runs/{run_id}",
    response_model=PipelineRunStatus,
)
async def get_run(
    ticker: str, run_id: str, _: AuthDep, tail: int = 30
) -> PipelineRunStatus:
    """Status + log-tail for a previously triggered run."""
    _ = ticker  # Path symmetry; status is keyed by run_id only.
    try:
        meta = pipeline_runner.get_run_status(run_id, tail_lines=tail)
    except FileNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return PipelineRunStatus(**meta)
