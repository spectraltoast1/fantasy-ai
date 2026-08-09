"""Server-side config seam for the read endpoints.

Values the API needs, resolved with the same precedence as ``db.database_url()`` —
environment variable first (a Fly secret in production), then a fallback to
``application/config.py`` (the durable, gitignored secret home that
``scripts/worktree-setup.sh`` symlinks into every worktree). The config import is guarded
so the deployed image — which ships only the ``api`` package, not ``config.py`` — never
depends on it (the env var wins there).

- ``my_username()`` — who "you" are in the league. Mirrors ``queries.js``'s ``MY_USERNAME``
  (matched against ``teams.owner_name`` for ``isMe``/``onYours``/``myOwner``). Stage-A only;
  the ``viewer_roster_id`` refactor is Stage B.
- ``league_id()`` — the single active league, stamped on every store row. Used to scope every
  query (a no-op filter today with one league; the seam Stage B parameterizes).
- ``supabase_url()`` — the project's base URL (P5/S1). The auth dependency derives both the
  JWKS endpoint and the expected token issuer from it. Not a secret; it is in every URL the
  browser already hits. Stored explicitly rather than parsed out of ``DATABASE_URL``'s pooler
  username, which is where the project ref happens to appear but is not a contract.
- ``supabase_secret_key()`` — admin-grade. **P5/S1b changed what this means.** S1 said "the API
  never calls an admin endpoint, so there is deliberately no Fly secret for it"; that is no
  longer true. The signup endpoint creates users on presentation of a valid access code, which
  *is* an admin action, so this key is now a Fly secret and lives in the deployed environment.
  That is a real posture change — an admin-grade credential is now reachable from the API — and
  it is the price of the gate being un-bypassable. The alternative (gating in the SPA) was
  measured to be no gate at all. Still never in git, the SPA bundle, or the image itself.
- ``demo_league_id()`` — the ONE public league (P5/S2a). Config rather than a table: one public
  league makes a table pure overhead, and a config value cannot be silently recreated-without-its
  properties by the next full loader run the way a `schema.sql` table can.
- ``current_season()`` — a thin seam over ``nfl_state``, which resolves Sleeper's ``/v1/state/nfl``
  with a persisted last-known-good and **fails closed** (unresolved → only the demo is visible).
  Its ``CURRENT_SEASON`` override is process-env-only, with **no config.py fallback on purpose** —
  it is a temporary operational override and one that could hide in a gitignored file is the
  failure mode.
- ``access_code()`` — the shared access code (P5/S1b). Required on **every** sign-in request,
  from everyone, which is what makes "no valid code, no email is ever sent" a hard property
  rather than a policy. Rotation is one config change: set it here (or the Fly secret) and the
  old value stops working immediately — there is no table to migrate.

Note the key names are Supabase's CURRENT ones — publishable / secret (``sb_publishable_…`` /
``sb_secret_…``), not the legacy ``anon`` / ``service_role`` JWTs they replace. The practical
difference for this code: the new keys are opaque strings rather than JWTs, so they go in the
``apikey`` header and NOT in ``Authorization`` (verified against the live project: ``apikey``
alone → 200, ``Authorization`` alone → 401). None of this touches token verification in
``auth.py`` — a user's access token is still an ES256 JWT checked against the project's JWKS.
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


def supabase_url() -> str | None:
    """The Supabase project base URL, e.g. ``https://<ref>.supabase.co`` (no trailing slash)."""
    url = os.environ.get("SUPABASE_URL") or _config_attr("SUPABASE_URL")
    return str(url).rstrip("/") if url else None


def supabase_secret_key() -> str | None:
    """The admin key (``sb_secret_…``). Needed in the deployed environment as of P5/S1b — the
    signup endpoint creates users, which is an admin call. See the module docstring."""
    return os.environ.get("SUPABASE_SECRET_KEY") or _config_attr("SUPABASE_SECRET_KEY")


def supabase_publishable_key() -> str | None:
    """The public key (``sb_publishable_…``). S1 left this out of the API on purpose — only the
    SPA needed it. S1b's signup endpoint sends the magic link the way a browser would, i.e. with
    the publishable key rather than the admin one, so the API needs it too."""
    return os.environ.get("SUPABASE_PUBLISHABLE_KEY") or _config_attr("SUPABASE_PUBLISHABLE_KEY")


def access_code() -> str | None:
    """The shared access code required on every sign-in request (P5/S1b)."""
    return os.environ.get("ACCESS_CODE") or _config_attr("ACCESS_CODE")


def demo_league_id() -> str | None:
    """The ONE public league (P5/S2a) — the league half of the visibility predicate.

    Config, not a table, and that is the decision rather than an implementation detail: with
    exactly one public league a table buys nothing, cannot drift from a loader-generated artifact,
    and needs no migration. It points at real LoRP 2025 today and gets repointed at the anonymized
    clone when that exists — one value, here or in ``fly.toml``'s ``[env]``.

    Note it happens to equal ``league_id()`` today (the demo IS the is_mine league), which is why
    making the signed-out default explicit is behaviour-identical right now. That coincidence is
    temporary and must not be relied on — see ``routes.slice_params``.
    """
    env = os.environ.get("DEMO_LEAGUE_ID")
    if env:
        return env
    cfg = _config_attr("DEMO_LEAGUE_ID")
    return str(cfg) if cfg is not None else None


def current_season() -> int | None:
    """The current NFL season, or None when it cannot be resolved (→ demo-only visibility).

    The resolution rules, the persisted last-known-good and the fail-closed behaviour live in
    ``nfl_state`` — this is only the seam so callers have one place to ask. Imported lazily
    because ``nfl_state`` reaches Postgres, and ``settings`` is imported by things that must stay
    DB-free at import time (``check_signup``, ``scripts/users.py``).
    """
    from application.api import nfl_state
    return nfl_state.current_season()
