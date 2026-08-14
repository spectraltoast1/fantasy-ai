"""The job queue — leasing work out of Postgres (P5/S4b).

`onboard_league.onboard()` has existed since P5/S4a and is proven. What did not exist was any way
to invoke it except a human typing `fly ssh console`. **The API cannot invoke it either:**
`api/requirements.txt` is deliberately fastapi-only and `fly.worker.toml` declares no
`[http_service]`, so the two machines cannot talk to each other — but both can talk to Postgres.
That, not latency, is why there is a queue: S0 measured a cold onboard at 8.4-10.3s, which would
comfortably fit inside a request.

**The correctness is in the SQL, not in this module.** `SELECT ... FOR UPDATE SKIP LOCKED` is the
primitive; everything here is a thin, named wrapper so the statements have one home and the gate has
something to drive. The DDL lives in `api/auth_schema.sql` — NOT in `serve/schema.sql`, which
`build_db --load` DROPs wholesale.

**Built as if a second worker existed, because one soon will.** A Fly volume attaches to exactly one
machine, so `fantasy-ai-worker` is a stateful singleton and two concurrent leasers are impossible
today. S4d adds a second producer and the GitHub Actions runner is a third machine that already
exists, so `SKIP LOCKED`, the lease expiry and the one-active-job-per-league index are all here now
rather than retrofitted onto live data later.
"""

from __future__ import annotations

import psycopg
from psycopg.rows import dict_row

from application.api import db

# The states a job passes through. `validating` is a SLOT — S5 owns preflight scope validation and
# the graceful rejection copy; today it covers the coldness/scope/season checks `onboard()` already
# does. There are deliberately NO per-stage semantics beyond "which one is it in now".
RUNNING_STATES = ("validating", "fetching", "building", "loading")
TERMINAL_STATES = ("ready", "rejected", "failed")

# How long a lease is good for, RENEWED AT EVERY STATE TRANSITION (see `advance`). Because it is
# renewed, this only ever has to exceed the longest single STAGE, not the whole job — so it can be
# short enough that a dead worker's league is reclaimed quickly. S0 measured the whole onboard at
# 8.4-10.3s end to end, so 120s is ~12x the entire run and no ordinary Sleeper slowness comes near
# it, while a killed worker's job is leasable again within two minutes with nobody intervening —
# which is the thing this queue exists to remove.
#
# The brief said to size this against "the 80s dossier fan-out". That fan-out is NOT on this path:
# `run_chain(dossiers=...)` defaults to False and `onboard()` never passes it, so the Manager
# Dossier stage is unreachable from here (it is a deferred job class — S4c). If it ever does run on
# a queued job, renewal at each transition already covers it.
LEASE_SECONDS = 120

# A poison job must not loop for ever: a crash on one malformed row is an outage for every other
# user's league. `rejected` jobs never retry at all (retrying a deterministic refusal cannot change
# the answer); this bounds the `failed` ones.
MAX_ATTEMPTS = 3

# Postgres LISTEN/NOTIFY channel. The worker listens; producers notify on insert. See `connect()`
# for why this forecloses the transaction pooler.
CHANNEL = "jobs_new"


def connect() -> psycopg.Connection:
    """A connection shaped for a long-lived leaser. Resolution still goes through `db.database_url`.

    Three differences from `db.connect()`, each earned:

    * **autocommit** — required for LISTEN to deliver notifications as they arrive rather than at a
      transaction boundary. It costs nothing here: `lease()` is a SINGLE `UPDATE ... WHERE id IN
      (SELECT ... FOR UPDATE SKIP LOCKED)` statement, and a single statement is atomic on its own.
    * **TCP keepalives** — this connection idles between jobs, and the Supabase session pooler (or
      any NAT in between) will eventually drop a silent socket. `db.connect()` sets only
      `connect_timeout`, which covers dialling and nothing after it, so a half-open socket would
      make the next statement block FOR EVER: no crash, no log line, and the worker has no
      `[http_service]` and therefore no health check to fail. A silently wedged worker is strictly
      worse than a crash-looping one, because nothing reports it.
    * **statement_timeout** — the same hazard from the server side, and the reason nothing here can
      hang indefinitely on a lock.

    **LISTEN/NOTIFY requires the SESSION pooler** (port 5432), which is what the worker's
    DATABASE_URL already is (P5/S3). It does not survive the transaction pooler (6543), where a
    connection is handed back after every statement and a LISTEN registration goes with it. That is
    a real constraint this design accepts: moving the worker to the transaction pooler would
    silently stop it ever being woken, leaving only the safety-net poll.
    """
    conn = psycopg.connect(
        db.database_url(),
        row_factory=dict_row,
        connect_timeout=10,
        keepalives=1, keepalives_idle=30, keepalives_interval=10, keepalives_count=3,
        options="-c statement_timeout=30000",
    )
    conn.autocommit = True
    return conn


_ENQUEUE = """
INSERT INTO public.jobs (kind, league_id, season, requested_by)
VALUES (%(kind)s, %(league_id)s, %(season)s, %(requested_by)s)
RETURNING id, kind, league_id, season, state, created_at
"""

# The lease. Every clause is doing work:
#
#   * `state = 'queued'`                    — new work.
#   * `OR (running AND lease_expires_at <)` — RECLAIM. A worker that died holding a lease must not
#                                             strand its league; this is what makes the expiry mean
#                                             something rather than just be recorded.
#   * `AND attempts < max`                  — the poison-job cap. THE PARENTHESES AROUND THE
#                                             DISJUNCTION ARE LOAD-BEARING: `AND` binds tighter than
#                                             `OR`, so without them the cap would apply only to the
#                                             reclaim branch and a `queued` row could be leased
#                                             without limit — which is precisely the row a graceful
#                                             SIGTERM release puts back.
#   * `ORDER BY created_at`                 — never `ORDER BY id`. The id is a uuid on purpose (see
#                                             auth_schema.sql), and ordering by insertion identity
#                                             breaks silently the moment a priority column exists.
#   * `FOR UPDATE SKIP LOCKED`              — the primitive. Two leasers each get a different row
#                                             instead of one blocking on the other.
_LEASE = f"""
UPDATE public.jobs SET
    state            = 'validating',
    attempts         = attempts + 1,
    leased_by        = %(worker)s,
    lease_expires_at = now() + (%(secs)s || ' seconds')::interval,
    started_at       = coalesce(started_at, now()),
    updated_at       = now()
WHERE id = (
    SELECT id FROM public.jobs
     WHERE (state = 'queued'
            OR (state = ANY(%(running)s) AND lease_expires_at < now()))
       AND attempts < %(max)s
     ORDER BY created_at
     LIMIT 1
     FOR UPDATE SKIP LOCKED)
RETURNING id, kind, league_id, season, state, attempts, leased_by, lease_expires_at
"""

# Renews the lease as a side effect of advancing — see LEASE_SECONDS. Guarded on `leased_by` so a
# worker whose lease was already reclaimed by somebody else cannot keep writing to the row.
_ADVANCE = """
UPDATE public.jobs SET
    state            = %(state)s,
    lease_expires_at = now() + (%(secs)s || ' seconds')::interval,
    updated_at       = now()
WHERE id = %(id)s AND leased_by = %(worker)s
RETURNING id, state, lease_expires_at
"""

_FINISH = """
UPDATE public.jobs SET
    state            = %(state)s,
    error            = %(error)s,
    finished_at      = now(),
    updated_at       = now(),
    leased_by        = NULL,
    lease_expires_at = NULL
WHERE id = %(id)s
RETURNING id, state, error, attempts, finished_at
"""

# Graceful shutdown (SIGTERM, i.e. every `fly deploy`). `attempts` is DECREMENTED: a redeploy is not
# a failed attempt, and without this every deploy would burn one of a job's three lives on a job
# that never actually went wrong.
_RELEASE = """
UPDATE public.jobs SET
    state            = 'queued',
    leased_by        = NULL,
    lease_expires_at = NULL,
    attempts         = greatest(attempts - 1, 0),
    updated_at       = now()
WHERE id = %(id)s AND state = ANY(%(running)s)
RETURNING id, attempts
"""

# A job whose lease expired and which has no attempts left is not "running" — it is finished, badly,
# and nothing is coming back for it. Without this it would sit in a running-looking state for ever,
# which is the silent half of "neither is silent".
_REAP = """
UPDATE public.jobs SET
    state            = 'failed',
    error            = coalesce(error || ' | ', '')
                       || 'lease expired with no attempts left ('
                       || attempts || '/' || %(max)s || ') — last held by '
                       || coalesce(leased_by, 'nobody'),
    finished_at      = now(),
    updated_at       = now(),
    leased_by        = NULL,
    lease_expires_at = NULL
WHERE state = ANY(%(running)s) AND lease_expires_at < now() AND attempts >= %(max)s
RETURNING id, league_id, season, attempts
"""


def enqueue(league_id: str, season: int, *, kind: str = "onboard",
            requested_by: str | None = None, conn: psycopg.Connection | None = None) -> dict:
    """Insert a job and wake a listening worker. Returns the new row.

    The NOTIFY is issued HERE, in reviewable code, rather than by a database trigger — the same
    choice `app_users` made by writing its row from `/api/me` instead of from invisible DDL. S4c's
    `POST /api/connect` and S4d's weekly cadence both call this; a row inserted by raw SQL without
    the NOTIFY is not lost, it is just picked up on the next safety-net poll.
    """
    own = conn is None
    conn = conn or connect()
    try:
        with conn.cursor() as cur:
            cur.execute(_ENQUEUE, {"kind": kind, "league_id": str(league_id),
                                   "season": int(season), "requested_by": requested_by})
            row = cur.fetchone()
            cur.execute("SELECT pg_notify(%(chan)s, %(payload)s)",
                        {"chan": CHANNEL, "payload": str(row["id"])})
        return row
    finally:
        if own:
            conn.close()


def lease(conn: psycopg.Connection, *, worker: str) -> dict | None:
    """Claim the oldest leasable job for `worker`, or None if there is nothing to do."""
    with conn.cursor() as cur:
        cur.execute(_LEASE, {"worker": worker, "secs": LEASE_SECONDS,
                             "running": list(RUNNING_STATES), "max": MAX_ATTEMPTS})
        return cur.fetchone()


def advance(conn: psycopg.Connection, job_id, state: str, *, worker: str) -> dict | None:
    """Move a held job to `state` and renew its lease. None means the lease was lost."""
    with conn.cursor() as cur:
        cur.execute(_ADVANCE, {"id": job_id, "state": state,
                               "secs": LEASE_SECONDS, "worker": worker})
        return cur.fetchone()


def finish(conn: psycopg.Connection, job_id, state: str, *, error: str | None = None) -> dict | None:
    """Land a job in a terminal state. `error` is what makes `failed` and `rejected` legible."""
    if state not in TERMINAL_STATES:
        raise ValueError(f"{state!r} is not terminal — expected one of {TERMINAL_STATES}")
    with conn.cursor() as cur:
        cur.execute(_FINISH, {"id": job_id, "state": state, "error": error})
        return cur.fetchone()


def release(conn: psycopg.Connection, job_id) -> dict | None:
    """Hand a held job back to the queue on graceful shutdown, without spending an attempt."""
    with conn.cursor() as cur:
        cur.execute(_RELEASE, {"id": job_id, "running": list(RUNNING_STATES)})
        return cur.fetchone()


def reap(conn: psycopg.Connection) -> list[dict]:
    """Fail every job whose lease expired with no attempts left. Returns what it buried."""
    with conn.cursor() as cur:
        cur.execute(_REAP, {"running": list(RUNNING_STATES), "max": MAX_ATTEMPTS})
        return cur.fetchall()
