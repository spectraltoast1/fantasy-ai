"""FastAPI entrypoint for the store-migration skeleton.

Run locally:
    uvicorn application.api.main:app --port 8000    # from the repo root

Endpoints:
    GET /          -> tiny index describing the skeleton
    GET /health    -> pure liveness (no DB). Always 200 while the process is up.
    GET /health/db -> opens a Supabase connection and runs SELECT 1.
                      200 {"db": "ok", "result": 1} on success, 503 on failure.

/health is intentionally DB-free so the platform health check does not flap if the
(free-tier) Supabase project pauses. /health/db is the explicit connectivity probe.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from application.api import db

app = FastAPI(
    title="fantasy-ai API",
    description="Store-migration Session 1 skeleton — Fly.io <-> Supabase plumbing.",
    version="0.1.0",
)


@app.get("/")
def index() -> dict:
    return {
        "service": "fantasy-ai-api",
        "status": "skeleton",
        "note": "Session 1 store-migration foundation. See /health and /health/db.",
    }


@app.get("/health")
def health() -> dict:
    """Liveness only — does not touch the database."""
    return {"status": "ok"}


@app.get("/health/db")
def health_db() -> JSONResponse:
    """Readiness — proves the app can reach the Supabase database."""
    try:
        result = db.check_db()
        return JSONResponse(status_code=200, content={"db": "ok", "result": result})
    except Exception as exc:  # noqa: BLE001 — report any failure as unhealthy
        return JSONResponse(
            status_code=503,
            content={"db": "error", "detail": f"{type(exc).__name__}: {exc}"},
        )
