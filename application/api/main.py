"""FastAPI entrypoint for the fantasy-ai app (store-migration go-live).

ONE same-origin app: it serves the built React SPA at ``/`` AND the ``/api`` read
endpoints, so the frontend's relative ``fetch('/api/…')`` calls just work — no CORS.

Run locally:
    uvicorn application.api.main:app --port 8000    # from the repo root

    In dev there is no built SPA (Vite serves it on :5173 and proxies /api here), so the
    static mount below is skipped and ``/`` simply 404s on this process — that's fine.
    In the image the built SPA lives at /app/static, so ``/`` serves index.html.

Endpoints:
    GET /health    -> pure liveness (no DB). Always 200 while the process is up.
    GET /health/db -> opens a Supabase connection and runs SELECT 1.
                      200 {"db": "ok", "result": 1} on success, 503 on failure.
    GET /api/*     -> the ported read endpoints (Sessions 3-4).
    GET /*         -> the built SPA (StaticFiles, mounted LAST as the catch-all).

/health is intentionally DB-free so the platform health check does not flap if the
(free-tier) Supabase project pauses. /health/db is the explicit connectivity probe.
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from application.api import db, nfl_state, settings
from application.api.routes import router as api_router

_LOG = logging.getLogger(__name__)

@contextlib.asynccontextmanager
async def _lifespan(_app: FastAPI):
    """State the two values the visibility rule turns on, once, at boot (P5/S2a).

    An operator override that nobody can see is the failure mode `nfl_state` is written around, so
    the resolved season AND its source go in the log — a `CURRENT_SEASON` left set after a proof
    run is then one grep away instead of a silent policy change.

    Wrapped, because this reaches Sleeper and Postgres: a config/third-party problem must be LOUD
    but never FATAL. A startup that died here would take the public demo down with it, which is
    the same rule S1 wrote for auth misconfiguration.
    """
    try:
        demo = settings.demo_league_id()
        _LOG.warning("demo league: %s", demo or "UNSET — the public catalog will be EMPTY")
        _LOG.warning("%s", nfl_state.describe())
    except Exception as exc:  # noqa: BLE001 — never let a log line stop the app booting
        _LOG.error("could not resolve the visibility config at startup: %s", exc)
    yield


app = FastAPI(
    title="fantasy-ai",
    description="Same-origin app on Fly.io <-> Supabase: serves the SPA at / and /api read endpoints.",
    version="1.0.0",
    lifespan=_lifespan,
)

# The Players + Teams + League + Matchups read endpoints (Sessions 3-4), backed by the
# Session-2 Postgres tables.
app.include_router(api_router)


@app.middleware("http")
async def _no_shared_caching_of_api(request, call_next):
    """Keep a cache from serving one caller's league to another (P5/S2b).

    Until S2b every ``/api`` response was the same bytes for everyone, so caching was a non-issue.
    It isn't now: the *same URL* returns data to its owner and a 404 to everyone else, and the only
    thing that distinguishes them is a request header. Any intermediary that caches on URL alone —
    a browser's bfcache, a corporate proxy, or the Cloudflare layer already planned for P6/S4 —
    would eventually hand a cached league to the wrong person. That is the failure this session
    exists to prevent, arriving through the one door the API layer doesn't control.

    Cheaper to declare now than to remember when the CDN lands. Applied uniformly, so the unowned
    and nonexistent 404s still carry byte-identical headers.
    """
    response = await call_next(request)
    if request.url.path.startswith("/api"):
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Vary"] = "Authorization"
    return response


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


# Serve the built SPA at "/" — mounted LAST so the explicit /api + /health routes above
# win and this catch-all only handles everything else. In the image the SPA is baked in
# at /app/static (main.py lives at /app/application/api/main.py -> parents[2] == /app).
# The is_dir() guard makes this a no-op in local dev (no build present), where Vite serves
# the SPA and proxies /api to this process — so importing the app never requires a build.
_STATIC_DIR = Path(__file__).resolve().parents[2] / "static"
if _STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=_STATIC_DIR, html=True), name="spa")
