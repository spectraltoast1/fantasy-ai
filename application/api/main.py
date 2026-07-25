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
from application.api.routes import router as api_router

app = FastAPI(
    title="fantasy-ai API",
    description="Store-migration API — Fly.io <-> Supabase. /health plumbing + /api read endpoints.",
    version="0.2.0",
)

# The Players + Teams read endpoints (Session 3), backed by the Session-2 Postgres tables.
app.include_router(api_router)


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
