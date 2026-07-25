# Minimal image for the API skeleton.
#
# Build context = this directory (application/api/), so the context stays tiny and
# the heavy data pipeline / snapshots / node_modules can never be sent to the builder
# or leaked into the image. The parent `application` package is recreated as an empty
# namespace so the repo-standard import path `application.api.main` still resolves.
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app

WORKDIR /app

# Install dependencies first for layer caching.
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Recreate the package skeleton: application/ (empty namespace) + application/api/ (code).
# NOTE: MY_USERNAME and LEAGUE_ID must be set as env/secrets on Fly — the image ships only
# the api package (no config.py), so settings.py falls back to nothing there.
RUN mkdir -p /app/application/api && touch /app/application/__init__.py
COPY __init__.py db.py settings.py calcs.py reads.py routes.py main.py /app/application/api/

# Fly injects PORT; default 8080 matches fly.toml internal_port.
EXPOSE 8080
CMD ["sh", "-c", "uvicorn application.api.main:app --host 0.0.0.0 --port ${PORT:-8080}"]
