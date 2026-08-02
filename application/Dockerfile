# Multi-stage image for the fantasy-ai app: ONE Fly app serves BOTH the built React
# SPA (at "/") and the /api read endpoints (same-origin — no CORS).
#
# Build context = application/ (so both api/ and frontend/ are visible to the builder).
# A tight .dockerignore keeps the heavy runtime out of the context and the image:
# data/ (snapshots+cache), node_modules, the symlinked parquet under frontend/public/data,
# config.py, and every venv. The parent `application` package is recreated as an empty
# namespace so the repo-standard import path `application.api.main` still resolves.

# ---- Stage 1: build the React SPA ----
FROM node:20-slim AS web
WORKDIR /web
# Install deps first for layer caching (lockfile-exact, reproducible).
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
# Supabase config for the SPA (P5/S1). These MUST be build args: Vite inlines
# `import.meta.env.VITE_*` at build time, .dockerignore strips every .env from the build
# context, and Fly *secrets* reach the running machine rather than the builder — so a .env or
# a secret would both yield a bundle with `undefined` config and a sign-in button that does
# nothing. Values live in fly.toml's [build.args] so a bare `fly deploy` stays correct.
# The publishable key is public by design (it ships in the bundle either way) and this
# project's Data API is disabled with RLS deny-by-default, so it opens nothing. The SECRET key
# must NEVER appear here — build args are readable in image history.
# Declared AFTER `npm ci` so changing a key doesn't invalidate the dependency-install layer.
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_PUBLISHABLE_KEY
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL \
    VITE_SUPABASE_PUBLISHABLE_KEY=$VITE_SUPABASE_PUBLISHABLE_KEY
# Build the SPA. frontend/public/data (the parquet symlinks) is excluded by
# .dockerignore, so `vite build` copies no parquet into dist — the image stays lean.
COPY frontend/ ./
RUN npm run build

# ---- Stage 2: Python API that also serves the built SPA ----
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install API dependencies first for layer caching.
COPY api/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Recreate the package: application/ (empty namespace) + application/api/ (code).
# COPY the api package as a DIRECTORY, not an enumerated file list, so a future new
# module can never be silently left out of the image (a Session-3 enumerated COPY
# dropped projections.py — added in Session 4, imported by reads.py — which built green
# then crashed on startup). The .dockerignore keeps Dockerfile/fly.toml/.env/.venv out.
# NOTE: MY_USERNAME + LEAGUE_ID must be set as Fly secrets — the image ships only the api
# package (no config.py), so settings.py has no local fallback there.
RUN mkdir -p /app/application && touch /app/application/__init__.py
COPY api/ /app/application/api/

# The built SPA becomes the static root FastAPI mounts at "/" (see main.py).
COPY --from=web /web/dist /app/static

# Fly injects PORT; default 8080 matches fly.toml internal_port.
EXPOSE 8080
CMD ["sh", "-c", "uvicorn application.api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
