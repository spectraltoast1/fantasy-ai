"""Database access for the API + the store-migration loader.

Resolves the Supabase Postgres connection string and opens connections with
psycopg 3. This is the single home for connection resolution, reused by both the
FastAPI app (`application.api.main`) and the loader (`application.data.serve.build_db`).

``DATABASE_URL`` is resolved with this precedence:
1. the ``DATABASE_URL`` environment variable — a Fly secret in production, and also
   how a local ``application/api/.env`` (loaded below) surfaces;
2. ``DATABASE_URL`` in ``application/config.py`` — the durable, gitignored secret home
   that ``scripts/worktree-setup.sh`` symlinks into every worktree (where the rest of
   the project's secrets live).

The config.py import is guarded so the deployed Fly image — which ships only the api
package, not config.py — never depends on it (the env var wins there anyway).
Secrets are never hardcoded.
"""

from __future__ import annotations

import os
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from dotenv import load_dotenv

# Load a local application/api/.env if present (legacy Session-1 path). A no-op when
# absent — the durable local source is now config.py (below).
_ENV_PATH = Path(__file__).resolve().parent / ".env"
load_dotenv(_ENV_PATH)


class DatabaseNotConfigured(RuntimeError):
    """Raised when DATABASE_URL cannot be resolved from env or config.py."""


def database_url() -> str:
    """Return the Postgres connection string, or raise DatabaseNotConfigured."""
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    try:
        from application.config import DATABASE_URL as cfg_url
    except Exception:
        cfg_url = None
    if cfg_url:
        return cfg_url
    raise DatabaseNotConfigured(
        "DATABASE_URL is not set. Locally, add DATABASE_URL to application/config.py "
        "(the durable secret home — see config.example.py). On Fly it is a secret env var."
    )


def check_db() -> int:
    """Open a connection and run ``SELECT 1``. Returns the scalar (1) on success.

    Raises on any failure (unresolved URL, unreachable DB, auth error) so callers can
    surface it as an unhealthy status.
    """
    with psycopg.connect(database_url(), connect_timeout=10) as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT 1")
            row = cur.fetchone()
    return int(row[0]) if row else 0


def connect() -> psycopg.Connection:
    """Open a psycopg connection whose cursors yield ``dict`` rows.

    The read functions in ``reads.py`` each open one connection and run their handful of
    queries on it (mirroring a ``queries.js`` loader's ``Promise.all``), so identity/roster
    joins happen against a single consistent snapshot. The caller manages the ``with`` block.
    """
    return psycopg.connect(database_url(), row_factory=dict_row, connect_timeout=10)


def fetch_all(sql: str, params: dict | None = None) -> list[dict]:
    """Run one query on a fresh connection and return all rows as dicts.

    Parameters are passed through psycopg's server-side binding (``%(name)s`` placeholders)
    — never string-interpolated — so identifiers like the player id are injection-safe.
    """
    with connect() as conn, conn.cursor() as cur:
        cur.execute(sql, params or {})
        return cur.fetchall()
