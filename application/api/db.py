"""Database access for the API skeleton.

One job this session: open a connection to the Supabase Postgres database using
the ``DATABASE_URL`` environment variable and run a trivial ``SELECT 1``.

Secrets are never hardcoded. ``DATABASE_URL`` comes from the environment:
- locally, from a gitignored ``application/api/.env`` (loaded here via python-dotenv);
- on Fly.io, from a Fly secret injected into the environment.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from dotenv import load_dotenv

# Load application/api/.env if present (local dev). On Fly the env var is already
# set as a secret, so a missing .env is fine — load_dotenv is a no-op then.
_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH)


class DatabaseNotConfigured(RuntimeError):
    """Raised when DATABASE_URL is not set in the environment."""


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise DatabaseNotConfigured(
            "DATABASE_URL is not set. Locally, create application/api/.env with "
            "DATABASE_URL=<your Supabase session-pooler string>. On Fly, set it with "
            "`fly secrets import < application/api/.env`."
        )
    return url


def check_db() -> int:
    """Open a connection and run ``SELECT 1``. Returns the scalar (1) on success.

    Raises on any failure (unset URL, unreachable DB, auth error) so callers can
    surface it as an unhealthy status.
    """
    with psycopg.connect(_database_url(), connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            row = cur.fetchone()
    return int(row[0]) if row else 0
