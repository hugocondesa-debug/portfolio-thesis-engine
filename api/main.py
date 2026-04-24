"""PTE Backend Service Layer — FastAPI application.

Sprint 0 entry point. Wires CORS (Tailscale-aware), Basic Auth (via
the per-route :data:`AuthDep` dependency in :mod:`api.auth`), error
handlers (404 / 400) and the four route modules. The service binds to
``0.0.0.0`` inside the container; docker-compose constrains the host
side to the Tailscale interface (`100.70.51.18:8000`).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from api import __version__
from api.config import settings
from api.routes import health, pipelines, tickers, yamls

logger = logging.getLogger("pte.api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    logging.basicConfig(level=settings.log_level)
    logger.info(
        "PTE API starting — version=%s data_root=%s",
        __version__,
        settings.data_root,
    )
    if not settings.data_root.exists():
        # Loud on startup — better than dribbling 500s later.
        raise RuntimeError(f"Data root not found: {settings.data_root}")
    yield
    logger.info("PTE API shutting down")


app = FastAPI(
    title="Portfolio Thesis Engine API",
    description=(
        "Backend service layer exposing PTE artefacts (canonical state, "
        "valuation, forecast, ficha, peers, cross-check logs) and the "
        "yaml authoring + pipeline-trigger workflow."
    ),
    version=__version__,
    lifespan=lifespan,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)


# ----------------------------------------------------------------------
# CORS — Tailscale (100.x.x.x), localhost (Next.js dev), MagicDNS hosts.
# ----------------------------------------------------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=(
        r"http://(localhost|127\.0\.0\.1|100\.\d+\.\d+\.\d+|dataflow)(:\d+)?"
    ),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)


# ----------------------------------------------------------------------
# Error handlers — translate the two exceptions our services raise into
# clean JSON envelopes.
# ----------------------------------------------------------------------
@app.exception_handler(FileNotFoundError)
async def file_not_found_handler(request: Request, exc: FileNotFoundError):
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"error": "not_found", "detail": str(exc)},
    )


@app.exception_handler(ValueError)
async def value_error_handler(request: Request, exc: ValueError):
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": "bad_request", "detail": str(exc)},
    )


# ----------------------------------------------------------------------
# Routes — health is unauthenticated (Docker healthcheck); the other
# routers apply :data:`AuthDep` per endpoint.
# ----------------------------------------------------------------------
app.include_router(health.router, prefix="/api", tags=["health"])
app.include_router(tickers.router, prefix="/api", tags=["tickers"])
app.include_router(yamls.router, prefix="/api", tags=["yamls"])
app.include_router(pipelines.router, prefix="/api", tags=["pipelines"])
