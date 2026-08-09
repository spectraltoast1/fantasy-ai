"""The current NFL season, resolved from Sleeper — the time half of the visibility rule (P5/S2a).

Visibility is one predicate:

    visible(league) = (league_id == DEMO_LEAGUE_ID)  OR  (owned by caller AND season == current)

"Current" comes from Sleeper's ``/v1/state/nfl``, **not** a hardcoded constant, so it rolls over by
itself during the preseason — 2026 was already current in early August 2026. The demo is the
deliberate season-independent exception (a 2025 league in the 2026 season), which is why the demo
term is evaluated FIRST and separately: written as a global ``season = current`` filter the demo
would vanish, and that looks exactly like an auth bug.

**Resolution order, and it is the security-relevant part of this module:**

===========================================  ==================  ==================
condition                                    result              source
===========================================  ==================  ==================
``CURRENT_SEASON`` set in the process env    that value          ``env``
cached value younger than ``_TTL_S``         the cached value    ``cache``
Sleeper answers                              that value (cached) ``sleeper``
Sleeper fails, a cached value exists         the cached value    ``cache (stale)``
Sleeper fails, nothing cached                ``None``            ``unresolved``
===========================================  ==================  ==================

**It fails CLOSED.** ``None`` means "no league qualifies as current-season", so visibility collapses
to the demo. It must never degrade to "no season filter": an outage that costs a user their own
league for an hour is an availability bug, while one that shows every league to everyone is the
silent isolation failure this session exists to prevent. Every fallback here narrows.

Serving a STALE season during an outage is safe for the same directional reason — the season only
rolls forward, so a stale value can at worst hide a league that has just become current.

``CURRENT_SEASON`` is a **process environment variable only**: never a query parameter, header, or
cookie, and deliberately with no ``config.py`` fallback either. It is an operational override for
running the ownership proofs against real deployed code (the corpus tops out at 2025 while Sleeper
says 2026, so without it the owned half of the predicate has nothing to bite on), and an override
that can hide in a gitignored file is the failure mode. In ``fly.toml`` it is plain ``[env]``, not
a secret, for the same reason. ``check_ownership.py`` asserts the request-immunity.

Stdlib ``urllib`` on purpose — the same choice as ``signup.py`` and ``scripts/users.py``. The real
Sleeper client (``application/data/fetchers/sleeper.py``) imports polars and ``data_layer`` at
module top, and ``application/api/requirements.txt`` deliberately ships neither into the image.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request

from application.api import db

_LOG = logging.getLogger(__name__)

_STATE_URL = "https://api.sleeper.app/v1/state/nfl"

# Short: this sits in front of the catalog read, so a hung third party must not hold a request open.
_TIMEOUT_S = 5
# It changes once a year. Twelve hours is frequent enough to catch the preseason rollover the same
# day and rare enough that Sleeper is not in the hot path of ordinary traffic.
_TTL_S = 12 * 60 * 60

ENV_VAR = "CURRENT_SEASON"

_READ_CACHE = """
SELECT season, extract(epoch FROM (now() - fetched_at))::float AS age_s
FROM public.nfl_state_cache WHERE only_row
"""

_WRITE_CACHE = """
INSERT INTO public.nfl_state_cache (only_row, season, fetched_at)
VALUES (true, %(season)s, now())
ON CONFLICT (only_row) DO UPDATE SET season = EXCLUDED.season, fetched_at = EXCLUDED.fetched_at
"""


def env_override() -> int | None:
    """The ``CURRENT_SEASON`` override, or None. Reads ``os.environ`` and nothing else.

    A non-numeric value is refused rather than guessed at — a typo'd override must be loud, not a
    silently ignored one that leaves the operator believing the matrix ran under it.
    """
    raw = (os.environ.get(ENV_VAR) or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        _LOG.error("%s=%r is not an integer — ignoring the override", ENV_VAR, raw)
        return None


def read_cache() -> tuple[int, float] | None:
    """``(season, age_seconds)`` from the persisted last-known-good, or None.

    In Postgres rather than a module global because ``min_machines_running = 0`` means an
    in-process value is erased on every scale-to-zero — the same reasoning that put the signup
    rate limiter in a table. A cache that is empty on every cold start is not a last-known-good.
    """
    try:
        rows = db.fetch_all(_READ_CACHE)
    except Exception as exc:                      # noqa: BLE001 — an unreachable DB is not fatal here
        _LOG.warning("could not read nfl_state_cache: %s", exc)
        return None
    if not rows:
        return None
    return int(rows[0]["season"]), float(rows[0]["age_s"])


def write_cache(season: int) -> None:
    try:
        db.execute(_WRITE_CACHE, {"season": int(season)})
    except Exception as exc:                      # noqa: BLE001 — failing to cache must not fail the read
        _LOG.warning("could not write nfl_state_cache: %s", exc)


def fetch_from_sleeper() -> int:
    """The season Sleeper reports. Raises on any failure — callers decide what a failure means."""
    req = urllib.request.Request(_STATE_URL, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
        payload = json.loads(resp.read() or "{}")
    return int(payload["season"])


def resolve() -> tuple[int | None, str]:
    """``(season, source)`` per the table in the module docstring. Never raises."""
    override = env_override()
    if override is not None:
        return override, "env"

    cached = read_cache()
    if cached is not None and cached[1] < _TTL_S:
        return cached[0], "cache"

    try:
        season = fetch_from_sleeper()
    except Exception as exc:                      # noqa: BLE001 — every failure mode lands the same way
        if cached is not None:
            _LOG.warning("Sleeper /state/nfl unreachable (%s) — serving cached season %d "
                         "(%.0fh old). Stale narrows visibility; it never widens it.",
                         exc, cached[0], cached[1] / 3600)
            return cached[0], "cache (stale)"
        _LOG.error("Sleeper /state/nfl unreachable (%s) and nothing cached — the current season is "
                   "UNRESOLVED, so only the demo league is visible until it recovers.", exc)
        return None, "unresolved"

    write_cache(season)
    return season, "sleeper"


def current_season() -> int | None:
    """The current season, or None when it cannot be resolved (→ demo-only visibility)."""
    return resolve()[0]


def describe() -> str:
    """One line for a startup log or `users.py --list`, so an override left set cannot hide."""
    season, source = resolve()
    shown = season if season is not None else "UNRESOLVED"
    line = f"current NFL season: {shown} (source: {source})"
    if source == "env":
        line += f"  ⚠ {ENV_VAR} override is SET — unset it before this counts as production"
    return line
