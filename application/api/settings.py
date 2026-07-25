"""Server-side config seam for the read endpoints.

Two values the ported reads need, resolved with the same precedence as
``db.database_url()`` — environment variable first (a Fly secret in production), then a
fallback to ``application/config.py`` (the durable, gitignored secret home that
``scripts/worktree-setup.sh`` symlinks into every worktree). The config import is guarded
so the deployed image — which ships only the ``api`` package, not ``config.py`` — never
depends on it (the env var wins there).

- ``my_username()`` — who "you" are in the league. Mirrors ``queries.js``'s ``MY_USERNAME``
  (matched against ``teams.owner_name`` for ``isMe``/``onYours``/``myOwner``). Stage-A only;
  the ``viewer_roster_id`` refactor is Stage B.
- ``league_id()`` — the single active league, stamped on every store row. Used to scope every
  query (a no-op filter today with one league; the seam Stage B parameterizes).
"""

from __future__ import annotations

import os


def _config_attr(name: str):
    """Return ``application.config.<name>`` if importable, else ``None``."""
    try:
        from application import config
    except Exception:
        return None
    return getattr(config, name, None)


def my_username() -> str | None:
    """The logged-in user's Sleeper handle (env ``MY_USERNAME`` → config ``SLEEPER_USERNAME``)."""
    return os.environ.get("MY_USERNAME") or _config_attr("SLEEPER_USERNAME")


def league_id() -> str | None:
    """The active league id (env ``LEAGUE_ID`` → config ``SLEEPER_LEAGUE_ID``), as a string."""
    env = os.environ.get("LEAGUE_ID")
    if env:
        return env
    cfg = _config_attr("SLEEPER_LEAGUE_ID")
    return str(cfg) if cfg is not None else None
