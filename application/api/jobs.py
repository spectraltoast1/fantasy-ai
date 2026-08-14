"""The job queue's PRODUCER and READER half — the seam both images can reach (P5/S4c).

**Why this module exists, because it is not where you would first look for it.** S4b put the queue
in `application/data/serve/job_queue.py`, whose own docstring says *"S4c's `POST /api/connect` …
call this."* **It cannot.** The API image contains no `application/data/` at all — verified two
ways: `application/.dockerignore` excludes a bare `data`, and `application/Dockerfile` copies
`api/` only. That is also why `api/requirements.txt` has no polars, and why `data/fetchers/
sleeper.py` (which imports polars AND data_layer) is unreachable from a route.

So the seam moves UP, here, and `job_queue` RE-EXPORTS it. **One implementation, reachable from
both images** — the shape S4a used when `canonical_rows` moved down into `data_layer` and
`check_scoped_reload` kept a one-line re-export. The dependency direction was already established:
`job_queue` imports `application.api.db` today.

**There must never be a second INSERT.** Two enqueue paths that drift is how a job gets inserted
without its `NOTIFY` and then sits in `queued` until the 60s safety-net poll notices it.
`check_connect` asserts, from source, that `INSERT INTO public.jobs` appears exactly once in the
repository and that `job_queue.enqueue is jobs.enqueue`.

**What stays in `job_queue`:** the LEASE, `advance`, `finish`, `release` and `reap` — the consumer
half. Only the worker runs those, only the worker needs them, and the lease SQL is the one piece of
this system whose correctness is genuinely in the SQL.

**This module is api-image-safe and must stay that way:** psycopg and stdlib only. No polars, no
`application.data` import, at module level or inside a function.
"""

from __future__ import annotations

import psycopg

from application.api import db

# The states a job passes through, and their home. `job_queue` re-exports both names so the
# worker's lease SQL and this module cannot describe two different vocabularies.
#
# `validating` is a SLOT — S5 owns preflight scope validation and the graceful rejection copy.
# There are deliberately NO per-stage semantics; S4c's progress screen maps them to copy and that
# mapping is the only place a stage means anything to a person.
RUNNING_STATES = ("validating", "fetching", "building", "loading")
TERMINAL_STATES = ("ready", "rejected", "failed")

# The one platform with an implementation behind it. The COLUMN is the dimension (see
# `api/platforms.py` and `projects/post-v1/other-platforms.md`); this constant is what the worker
# checks so an unimplemented platform is a clean `rejected` rather than a crash — exactly how
# `kind` earned its keep before a second executor existed.
DEFAULT_PLATFORM = "sleeper"

# Postgres LISTEN/NOTIFY channel. It lives here because `enqueue` is the only thing that NOTIFIES;
# `job_queue` re-exports it for the worker, which is the only thing that LISTENs. See
# `job_queue.connect` for why this forecloses the transaction pooler.
CHANNEL = "jobs_new"


# THE one INSERT. `platform` carries the dimension; `handle` and `platform_user_id` are what let
# the worker resolve the caller's SEAT without re-discovering anything (P5/S4c §3).
#
# `platform_user_id`, NOT `sleeper_user_id`: naming a generic column after one vendor is the trench
# `other-platforms.md` exists to keep us out of.
_ENQUEUE = """
INSERT INTO public.jobs (kind, platform, league_id, season, requested_by, handle, platform_user_id)
VALUES (%(kind)s, %(platform)s, %(league_id)s, %(season)s, %(requested_by)s,
        %(handle)s, %(platform_user_id)s)
RETURNING id, kind, platform, league_id, season, state, created_at
"""

# The columns a CALLER may see of their own job. Enumerated rather than `SELECT *` on purpose:
# `leased_by` names a Fly machine and `lease_expires_at` describes our retry mechanics, and neither
# is any of the caller's business — a `SELECT *` would publish every column a later session adds,
# silently, the first time somebody adds one.
_JOB_FIELDS = ("id, kind, platform, league_id, season, state, error, attempts, "
               "created_at, started_at, finished_at, updated_at")

# Scoped to `requested_by`, and the scoping is the point. The uuid PK makes enumeration
# impractical; that is not a reason to skip the check. S2b's principle — an object you may not have
# answers exactly as one that does not exist — applies to every object, not just leagues, and the
# route turns a None from here into the SAME 404 body a nonexistent id gets.
#
# `requested_by = %(uid)s` also excludes the hand-enqueued rows S4b created (NULL requester) and
# S4d's refresh jobs, which is correct: nobody asked for those through a browser.
_JOB_FOR_OWNER = f"""
SELECT {_JOB_FIELDS} FROM public.jobs
 WHERE id = %(id)s::uuid AND requested_by = %(uid)s::uuid
"""

# "Do I have a job in flight?" — REQUIRED, not a convenience (P5/S4c §1). The ownership row is
# written at `ready`, so the progress screen cannot be driven by the catalog; it is driven by the
# job. A signed-in user who refreshes mid-build therefore has to be able to find their job again
# without an id held in browser memory.
#
# Newest first and LIMIT 1: `jobs_active_league_idx` already forbids two active jobs for one
# (league, season), but nothing forbids a caller having one active job for each of two leagues, and
# a progress banner can only describe one thing.
_ACTIVE_JOB_FOR_USER = f"""
SELECT {_JOB_FIELDS} FROM public.jobs
 WHERE requested_by = %(uid)s::uuid AND state <> ALL(%(terminal)s)
 ORDER BY created_at DESC
 LIMIT 1
"""

# How many jobs this account has asked for inside the window — the CONNECT rate limit's counter.
#
# Counted from `jobs` itself rather than from a second attempts table, and that is the decision:
# the record IS the thing being limited, so the two cannot drift. (Discovery has no such record of
# its own, which is why `connect_attempts` exists for that half and only that half.)
_RECENT_JOBS_FOR_USER = """
SELECT count(*)::int AS n FROM public.jobs
 WHERE requested_by = %(uid)s::uuid AND created_at > now() - (%(mins)s || ' minutes')::interval
"""

# The ownership row. `ON CONFLICT … DO UPDATE` rather than `DO NOTHING` so re-linking a league you
# already hold REFRESHES the seat — a manager who changed teams, or a first link that resolved no
# seat at all and a second that did.
#
# NOT a claim of control, and deliberately so (settled with Will, 2026-08-14): Sleeper offers no
# OAuth and no verification primitive, and anyone holding a league_id can already read that
# league's rosters and owners straight from api.sleeper.app — the id is the secret and we are not
# the weak link. Nor is `roster_id` unique per league, and that is also deliberate: it is a
# PER-USER DISPLAY property inside a league the user can already read (auth_schema.sql), two people
# in one league both linking it is the designed case, and enforcing first-claim-wins would create a
# griefing vector (claim a seat, lock the real owner out of their own highlight) that not enforcing
# it does not.
_GRANT = """
INSERT INTO public.user_leagues (user_id, league_id, roster_id)
VALUES (%(uid)s::uuid, %(lid)s, %(rid)s)
ON CONFLICT (user_id, league_id) DO UPDATE SET roster_id = EXCLUDED.roster_id
RETURNING user_id, league_id, roster_id
"""


def enqueue(league_id: str, season: int, *, kind: str = "onboard",
            platform: str = DEFAULT_PLATFORM, requested_by: str | None = None,
            handle: str | None = None, platform_user_id: str | None = None,
            conn: psycopg.Connection | None = None) -> dict:
    """Insert a job and wake a listening worker. Returns the new row.

    Moved here from `job_queue` in P5/S4c so `POST /api/connect` can reach it; `job_queue.enqueue`
    is now an alias for this function, so the positional signature is unchanged and
    `OPERATIONS.md`'s hand-enqueue one-liner keeps working.

    The NOTIFY is issued HERE, in reviewable code, rather than by a database trigger — the same
    choice `app_users` made by writing its row from `/api/me` instead of from invisible DDL. A row
    inserted by raw SQL without the NOTIFY is not lost, it is just picked up on the next
    safety-net poll.

    **Commits only a connection it opened.** `check_queue --live` passes an autocommit connection
    it manages, and the worker will eventually pass one inside an explicit transaction block;
    committing somebody else's connection would end their transaction under them. `pg_notify` is
    transactional — it fires at COMMIT — so on a caller-supplied connection the wakeup arrives when
    the caller commits, which is what you want: no worker is told about a job that might roll back.
    """
    own = conn is None
    conn = conn or db.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(_ENQUEUE, {"kind": kind, "platform": str(platform),
                                   "league_id": str(league_id), "season": int(season),
                                   "requested_by": requested_by, "handle": handle,
                                   "platform_user_id": platform_user_id})
            row = cur.fetchone()
            cur.execute("SELECT pg_notify(%(chan)s, %(payload)s)",
                        {"chan": CHANNEL, "payload": str(row["id"])})
        if own:
            conn.commit()
        return row
    finally:
        if own:
            conn.close()


def job_for_owner(job_id: str, user_id: str) -> dict | None:
    """One job, or None — where None means *not yours* and *does not exist* indistinguishably.

    Both cases return None on purpose and the route turns None into one 404 with one body. A 403
    (or a different message, or a different body length) would confirm a job exists, which is the
    same enumeration oracle `reads.SliceRefused` is one exception type to avoid.

    A malformed id is None too rather than a 500: `%(id)s::uuid` raises on garbage, so the cast is
    guarded by the caller. See `routes.connect_job`.
    """
    rows = db.fetch_all(_JOB_FOR_OWNER, {"id": str(job_id), "uid": str(user_id)})
    return rows[0] if rows else None


def active_job_for_user(user_id: str) -> dict | None:
    """The caller's newest job that has not finished, or None. What survives a mid-build refresh."""
    rows = db.fetch_all(_ACTIVE_JOB_FOR_USER,
                        {"uid": str(user_id), "terminal": list(TERMINAL_STATES)})
    return rows[0] if rows else None


def recent_job_count(user_id: str, *, minutes: int) -> int:
    """How many jobs this account has asked for in the last `minutes` — the connect budget."""
    return db.fetch_all(_RECENT_JOBS_FOR_USER,
                        {"uid": str(user_id), "mins": int(minutes)})[0]["n"] or 0


def grant_ownership(conn: psycopg.Connection, *, user_id, league_id, roster_id) -> dict | None:
    """Record that `user_id` owns `league_id`, with `roster_id` as their seat. None when unowned.

    **Called at `ready`, never at enqueue, and never on its own connection.** The caller wraps this
    and `job_queue.finish` in ONE transaction — see `worker_loop._run_job`. The reason is that
    `reads.visible` is `demo OR (owned AND season == current)` and `build_catalog` sorts owned
    first, so an ownership row that exists before the build finishes lands the user on THEIR OWN
    LEAGUE WITH EVERY PANEL EMPTY, for the ~10s the build takes, with no error anywhere. And a
    crash between a grant and its `ready` would leave a terminal job whose league nobody owns —
    terminal, so no retry ever revisits it.

    `user_id` None is a no-op, not an error: S4b's hand-enqueued rows and S4d's refresh jobs have
    no requester, and there is nobody to grant anything to.
    """
    if not user_id:
        return None
    with conn.cursor() as cur:
        cur.execute(_GRANT, {"uid": str(user_id), "lid": str(league_id),
                             "rid": int(roster_id) if roster_id is not None else None})
        return cur.fetchone()
