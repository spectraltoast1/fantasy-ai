"""The worker's process — `sleep infinity` becomes a leasing loop (P5/S4b).

`Dockerfile.worker` used to end `CMD ["sleep", "infinity"]`: the machine was always on (that is the
~$7/mo) and did nothing, waiting for a human to `fly ssh console` into it. This is what replaces it.
It stays a JOB BOX — no HTTP, no health check, nothing listening.

**The shape of the thing:** wait for work (LISTEN, with a slow safety-net poll), lease one job, run
it, land it in a terminal state, repeat. The interesting parts are all failure handling, because the
whole point of removing the human is that nobody is watching:

* **A bad job must not be an outage.** One malformed row that crash-looped this process would stop
  every other user's league from being built. Every executor call is contained, and the loop's own
  errors are logged and slept over rather than raised.
* **`SystemExit` IS NOT AN `Exception`.** `onboard_league` signals every refusal with `SystemExit`
  (five of them), and `SystemExit` inherits from `BaseException` — so a plain `except Exception`
  would not catch a single one and this process would simply exit on the first out-of-scope league.
  That is the highest-value trap in this file; see `_run_job`.
* **A misconfigured box must stay reachable.** The startup assertions log and sleep instead of
  exiting, because a process that exits immediately makes the machine crash-loop, and you cannot
  `fly ssh` into a crash-looping machine to fix the config that caused it. The worker has no other
  door: no `[http_service]`, no health check.

**Observability lives in the `jobs` row, not here.** DoD 2 is that a reader can tell what happened
from the TABLE ALONE. stdout is for a human tailing `fly logs`; it is not the record.

**P5/S4c gave this loop the other half of a connect.** A job now carries who asked for it and which
platform identity to resolve a seat from, and reaching `ready` WRITES THE OWNERSHIP ROW — in the
same transaction as the state change, for the reasons spelled out in `_run_job`'s `else:` branch.
Until that commit, a league being built belongs to nobody, which is exactly what stops a user
landing on a half-built league of their own.
"""

from __future__ import annotations

import contextlib
import os
import signal
import socket
import sys
import time
import traceback

from application.api import jobs, platforms
from application.data import data_layer as dl
from application.data.fetchers import sleeper
from application.data.serve import job_queue as q
from application.data.serve import onboard_league, weekly_refresh

# How long to block waiting for a NOTIFY before waking up anyway. The wakeup is a SAFETY NET, not
# the mechanism: NOTIFY is fire-and-forget, so one sent while this process was reconnecting is LOST,
# and without a periodic poll that job would sit in `queued` for ever. It also runs `reap`, and it
# is what turns a dead socket into a visible error rather than an indefinite block (see
# job_queue.connect). 60s means a lost notification costs a minute, not a stuck league.
IDLE_WAKE_SECONDS = 60

# How long to sleep after an error in the LOOP itself (not in a job) before trying again. Long
# enough not to hammer a database that is down, short enough that recovery is unattended.
ERROR_BACKOFF_SECONDS = 30

# `onboard_league`'s stage names → the job states in `auth_schema.sql`. Four build stages collapse
# into one state on purpose: the brief is explicit that there are no per-stage semantics and no
# per-stage UI, and S4c decides what a person actually sees. This mapping is the ONLY place the two
# vocabularies meet.
_STATE_BY_STAGE = {
    "validating": "validating",
    "fetch": "fetching",
    "join": "building",
    "band": "building",
    "spine": "building",
    "schedule": "building",
    "manager_activity": "building",
    "manager_features": "building",
    "loading": "loading",
}

_STOP = False


class _Shutdown(BaseException):
    """SIGTERM arrived while a job was running. BaseException so nothing in the pipeline's own
    `except Exception:` handlers can swallow it and carry on into the next stage."""


class _LeaseLost(BaseException):
    """Another worker reclaimed this job while we were building it. Also BaseException, and for a
    sharper reason: continuing would mean two machines writing one league's artifacts."""


def _log(msg: str) -> None:
    # print(), not logging: the pipeline's convention, and PYTHONUNBUFFERED=1 is already set in the
    # image, so this streams straight into `fly logs` with no flush plumbing.
    print(f"[worker] {msg}", flush=True)


def _worker_id() -> str:
    """Which machine holds a lease. Fly's machine id when there is one — after a kill drill this is
    what tells you who was holding the job."""
    return os.environ.get("FLY_MACHINE_ID") or os.environ.get("FLY_ALLOC_ID") or socket.gethostname()


def _on_sigterm(_signum, _frame) -> None:
    """Set the flag and return. DELIBERATELY does not raise and does not touch the database.

    A signal handler runs between bytecodes, which could be in the middle of a psycopg statement on
    the very connection we would need — so the handback happens at the next STAGE BOUNDARY, in
    `_stage_observer`, where nothing is in flight. If a stage is long enough that Fly's kill_timeout
    expires first, the lease expiry is the backstop and the job is retried; that is slower, not
    wrong.
    """
    global _STOP
    _STOP = True
    _log("SIGTERM — finishing the current stage, then releasing the lease and exiting")


def _stage_observer(conn, job, worker: str):
    """Build the `stage=` observer `onboard_league.onboard` takes, writing state into the job row.

    The states a reader sees therefore come from THE chain, not from a second description of it —
    the same argument S4a made for having one `run_chain` instead of two.
    """
    last = {"state": job["state"]}

    @contextlib.contextmanager
    def observe(name: str):
        if _STOP:
            raise _Shutdown(name)
        state = _STATE_BY_STAGE.get(name)
        if state and state != last["state"]:
            # `advance` also RENEWS the lease, which is why LEASE_SECONDS only has to cover the
            # longest single stage rather than the whole job.
            if q.advance(conn, job["id"], state, worker=worker) is None:
                raise _LeaseLost(f"lease on {job['id']} is no longer ours (at stage {name!r})")
            last["state"] = state
        print(f"\n--- {name} ---", flush=True)
        yield

    return observe


def _execute_onboard(conn, job, worker: str) -> int | None:
    """Build the league, then work out which roster is the requester's. Returns the seat, or None.

    **The seat is resolved here and GRANTED by the caller**, which is not an arbitrary split: the
    grant has to happen in the same transaction as `finish`, and only `_run_job` owns that boundary.
    See its `else:` branch for why.
    """
    onboard_league.onboard(job["league_id"], int(job["season"]),
                           stage=_stage_observer(conn, job, worker))
    return onboard_league.resolve_seat(job["league_id"], int(job["season"]),
                                       job.get("platform_user_id"))


def _execute_refresh(conn, job, worker: str) -> int | None:
    """Advance one already-connected league to the current week. Grants nothing — it is already owned.

    **`lid` is passed EXPLICITLY and that is the point of the whole job class.**
    `weekly_refresh.refresh_league` opens with `lid = lid or league_resolver.resolve_league_id(season)`,
    and that resolver is the is_mine one: with `lid=None` it reads `MY_USERNAME`/`LEAGUE_ID` and
    refreshes THE OPERATOR'S OWN LEAGUE, whichever league the job was actually for. A job that
    carries its own `league_id` never touches it — which is what RETIRES those two variables rather
    than relocating them into a new machine's environment.

    **The season is checked, not assumed.** `refresh_league(..., live=True)` OVERWRITES both season
    and target week from Sleeper's NFL state, so it would ignore the job's own `season` entirely —
    and a job enqueued before a season rollover would then be run against the new season under the
    old season's league id. That is not hypothetical: the enumeration selects on the catalog's
    season and Sleeper's flips in late August, so the two straddle a real boundary every year.

    A stale job is REFUSED rather than retargeted. Terminal is right: a finished season has nothing
    left to advance to, and next week's enumeration selects the current season's leagues on its own.
    """
    live_season = int(sleeper._get_nfl_state()["season"])
    if int(job["season"]) != live_season:
        raise SystemExit(
            f"this job is for the {job['season']} season and the NFL is now in {live_season}, so "
            f"there is nothing left to advance. The season rolled over after this job was queued; "
            f"the next weekly run enumerates the current season by itself.")

    weekly_refresh.refresh_league(job["league_id"], live_season, live=True,
                                  stage=_stage_observer(conn, job, worker))
    return None


# One entry per job class. The Manager Dossier fan-out is a deferred class and belongs to S4e.
# An unknown kind is REJECTED, not a crash.
#
# `refresh` (P5/S4d) is what stops the app being frozen in-season. It is the SAME queue, the same
# lease, the same reaper and the same terminal states as `onboard` — the only thing that differs is
# which function runs and that nobody is waiting on the result, so nothing about the worker had to
# change to accept it. That is the column earning its keep exactly as it was built to.
_EXECUTORS = {"onboard": _execute_onboard, "refresh": _execute_refresh}

# What a job row says when the text it would otherwise carry is not fit for a human to read.
# Two different situations, so two different sentences — "try again" is wrong for the first.
_OPERATOR_HALT = ("This league could not be refreshed because the shared projection substrate on "
                  "this machine is out of date. Nothing was changed. This needs an operator, not a "
                  "retry — the details are in the worker log.")
_CRASH_HALT = ("Something went wrong while building this league. Nothing about your account or "
               "your league was changed, and the details have been logged. It is worth trying "
               "again; if it keeps happening, this is ours to fix, not yours.")


def _run_job(conn, job, worker: str) -> None:
    """Run one job and land it in a terminal state. Never raises except to shut down."""
    label = f"{job['kind']} {job['league_id']}/{job['season']} (job {job['id']}, "\
            f"attempt {job['attempts']}/{q.MAX_ATTEMPTS})"
    _log(f"leased {label}")
    started = time.monotonic()

    executor = _EXECUTORS.get(job["kind"])
    if executor is None:
        q.finish(conn, job["id"], "rejected",
                 error=f"unknown job kind {job['kind']!r} — this worker implements "
                       f"{sorted(_EXECUTORS)}. Nothing will change on a retry.")
        _log(f"REJECTED {label}: unknown kind")
        return

    # The platform dimension, refused the same way an unknown `kind` is (P5/S4c). `POST /api/connect`
    # already declines anything unimplemented, so reaching this needs a hand-inserted row — but the
    # column exists precisely so a second platform can arrive, and the day it does, a worker that
    # cannot do it must say so rather than running the Sleeper chain against a Yahoo league id.
    # `platforms.IMPLEMENTED` is the one list, shared with the route that refuses at the front door.
    platform = job.get("platform") or platforms.IMPLEMENTED[0]
    if platform not in platforms.IMPLEMENTED:
        q.finish(conn, job["id"], "rejected",
                 error=f"unknown platform {platform!r} — this worker implements "
                       f"{list(platforms.IMPLEMENTED)}. Nothing will change on a retry.")
        _log(f"REJECTED {label}: unknown platform {platform!r}")
        return

    try:
        seat = executor(conn, job, worker)
    except SystemExit as e:
        # THE TRAP. `SystemExit` is a BaseException, so this clause must come BEFORE `except
        # Exception` and cannot be folded into it. onboard_league raises it for every deliberate
        # refusal — out of scope, wrong season, not cold, not drafted yet, played no weeks, first on
        # its scoring key — and every one of those is DETERMINISTIC: the same job would be refused
        # identically for ever, so it is terminal on the first attempt rather than retried to the cap.
        #
        # THIS IS THE ONE BRANCH WHOSE TEXT REACHES A HUMAN VERBATIM, and that is deliberate
        # (S4c: "end the screen with whatever words the refusal already carries"). It is safe
        # because an authored refusal is WRITTEN to be read — see `assert_in_scope` and the
        # zero-week refusal, which say what happened and what to do about it.
        #
        # `weekly_refresh` also raises SystemExit with OPERATOR-aimed text that names shell
        # commands (`is_synthetic`, `_resolve_scoring_key`). Those cannot reach a user: a refresh
        # job carries `requested_by = NULL`, and both `active_job_for_user` and
        # `job_for_owner` filter on it, so no banner and no `GET /api/connect/{id}` can return one.
        q.finish(conn, job["id"], "rejected", error=str(e) or repr(e))
        _log(f"REJECTED {label}: {str(e).splitlines()[0] if str(e) else e!r}")
    except (_Shutdown, _LeaseLost):
        raise
    except dl.StoreBoundaryError as e:
        # TERMINAL, BUT NOT USER-FACING — the one case that is neither of the other two (P5/S4d).
        # A stale or missing shared band is DETERMINISTIC (attempts 2 and 3 recompute the identical
        # frame and refuse identically), so retrying it to the cap was wrong; it belongs with the
        # refusals. But its message is written for the OPERATOR — it names a laptop command line and
        # OPERATIONS.md — so it is sanitised like a crash rather than shown like a refusal.
        q.finish(conn, job["id"], "rejected", error=_OPERATOR_HALT)
        _log(f"REJECTED {label}: StoreBoundaryError (terminal — the shared band needs the laptop)")
        traceback.print_exc()
        return
    except Exception as e:                                     # noqa: BLE001 — see the docstring
        # Everything else is a CRASH, and crashes are retryable: Sleeper timing out, the network, a
        # bug. `reap` turns the last attempt into a terminal `failed` so nothing sits in a
        # running-looking state for ever.
        #
        # THE EXCEPTION TEXT DOES NOT GO IN THE JOB ROW. `routes._job_payload` passes `error`
        # through unchanged and `App.jsx` renders it raw, so whatever lands here is on somebody's
        # screen — and on 2026-08-14 that was a `FileNotFoundError` carrying an absolute path into
        # this repo's snapshot store. An UNHANDLED exception has not been written for anyone to
        # read; only an authored refusal has. So the row gets a sentence somebody can act on and
        # the logs keep everything, which is what `traceback.print_exc()` below is for.
        #
        # The class name is the one internal kept, deliberately: it is a Python identifier, never a
        # path, an id or user data, and it is the single most useful triage token for whoever reads
        # the `jobs` table instead of the worker's logs — which §6 of this session's brief requires
        # to be possible.
        q.finish(conn, job["id"], "failed", error=f"{_CRASH_HALT} ({type(e).__name__})")
        _log(f"FAILED {label}: {type(e).__name__}: {e}")
        traceback.print_exc()
        return
    else:
        # THE OWNERSHIP ROW IS WRITTEN HERE — AT `ready`, NOT AT ENQUEUE — AND IN ONE TRANSACTION
        # WITH IT (P5/S4c). Two separate failures are being prevented and neither announces itself:
        #
        #   * WRITTEN EARLY. `reads.visible` is `demo OR (owned AND season == current)` and
        #     `build_catalog` sorts OWNED FIRST, and the SPA lands on `leagues[0]` — so a row that
        #     exists while the build is still running drops the user onto THEIR OWN LEAGUE WITH
        #     EVERY PANEL EMPTY for ten seconds, with no error raised anywhere. That is the worst
        #     first impression this product can make and nothing would report it.
        #   * WRITTEN SEPARATELY. A crash between the grant and the `finish` leaves a job that is
        #     `ready` — terminal, so no retry ever revisits it — over a league nobody owns. The
        #     league would be built, catalogued, loaded, and invisible to the person who asked for
        #     it, for ever.
        #
        # `conn` is autocommit (see `job_queue.connect`), so this opens an EXPLICIT block: both
        # statements land together or neither does.
        with conn.transaction():
            granted = jobs.grant_ownership(conn, user_id=job.get("requested_by"),
                                           league_id=job["league_id"], roster_id=seat)
            q.finish(conn, job["id"], "ready")
        if granted:
            _log(f"granted {job['league_id']} to {granted['user_id']} "
                 f"(seat {granted['roster_id']!r})")
        elif job.get("requested_by"):
            _log(f"NO GRANT for {label} — requested_by set but the insert returned nothing")
        _log(f"READY {label} in {time.monotonic() - started:.1f}s")


# The idle wait is served in slices so SIGTERM is noticed promptly. A single
# `notifies(timeout=IDLE_WAKE_SECONDS)` is NOT interruptible by a signal handler that only sets a
# flag — measured, not assumed: the first version of this loop sat in a 60s wait after SIGTERM and
# had to be SIGKILLed, which would have made every `fly deploy` hang to `kill_timeout` and strand
# the lease it was supposed to hand back. Slicing costs nothing: `notifies` waits on the socket and
# issues no SQL, so this is the same one LISTEN either way and a real notification still wakes it
# instantly.
_WAIT_SLICE_SECONDS = 5


def _wait_for_work(conn) -> None:
    """Block until a NOTIFY arrives, the safety net fires, or we are asked to stop."""
    with conn.cursor() as cur:
        cur.execute(f"LISTEN {q.CHANNEL}")
    waited = 0.0
    while waited < IDLE_WAKE_SECONDS and not _STOP:
        slice_s = min(_WAIT_SLICE_SECONDS, IDLE_WAKE_SECONDS - waited)
        for _ in conn.notifies(timeout=slice_s, stop_after=1):
            return
        waited += slice_s


def _startup_problems() -> list[str]:
    """Everything that must hold before this process may lease anything."""
    problems = []
    # A long-running process is a new way to lose an env var, and losing THIS one would let the
    # worker author the shared substrate every other league reads. It is set in both
    # fly.worker.toml [env] and the image, deliberately — belt and braces — so if it is missing here
    # something is badly wrong and leasing would be the worst possible response.
    role = dl.store_role()
    if role != "worker":
        problems.append(f"STORE_ROLE is {role!r}, not 'worker' — this process would be allowed to "
                        "write laptop-owned artifacts (context/appendices/store-boundary.md). It is "
                        "set in BOTH fly.worker.toml [env] and Dockerfile.worker; check both.")
    try:
        from application.api import db
        db.database_url()
    except Exception as e:                                     # noqa: BLE001
        problems.append(f"DATABASE_URL does not resolve ({type(e).__name__}: {e}) — it is a Fly "
                        "SECRET on this app, not an [env] value: `fly secrets list -a "
                        "fantasy-ai-worker`.")
    return problems


def main() -> int:
    signal.signal(signal.SIGTERM, _on_sigterm)
    signal.signal(signal.SIGINT, _on_sigterm)
    worker = _worker_id()
    _log(f"starting — worker={worker} lease={q.LEASE_SECONDS}s "
         f"max_attempts={q.MAX_ATTEMPTS} idle_wake={IDLE_WAKE_SECONDS}s")

    # REFUSE TO LEASE, but do not exit: an exiting process makes the machine crash-loop, and you
    # cannot `fly ssh` into a crash-looping machine to fix the very config that caused it.
    while not _STOP and (problems := _startup_problems()):
        for p in problems:
            _log(f"REFUSING TO LEASE: {p}")
        _log(f"idling {ERROR_BACKOFF_SECONDS}s — the machine stays reachable; fix the config and "
             "this will pick it up without a redeploy")
        time.sleep(ERROR_BACKOFF_SECONDS)

    conn = None
    held = None
    while not _STOP:
        try:
            if conn is None or conn.closed:
                conn = q.connect()
                _log("connected (LISTEN + safety-net poll)")
            for dead in q.reap(conn):
                _log(f"reaped {dead['league_id']}/{dead['season']} (job {dead['id']}) — lease "
                     f"expired with {dead['attempts']} attempts spent")
            held = q.lease(conn, worker=worker)
            if held is None:
                _wait_for_work(conn)
                continue
            _run_job(conn, held, worker)
            held = None
        except (_Shutdown, _LeaseLost) as e:
            if isinstance(e, _LeaseLost):
                _log(f"{e} — dropping it; the worker that holds it will finish it")
            elif held is not None and conn is not None:
                back = q.release(conn, held["id"])
                _log(f"released job {held['id']} back to `queued` "
                     f"(attempts refunded to {back['attempts'] if back else '?'}) — a redeploy is "
                     "not a failed attempt")
            held = None
            if isinstance(e, _Shutdown):
                break
        except Exception as e:                                 # noqa: BLE001
            # The LOOP failed, not a job — the database went away, the socket died, the pooler
            # dropped us. Never exit: log it, drop the connection so the next pass redials, and
            # sleep. An unattended worker that gives up is the same outage as no worker at all.
            _log(f"loop error ({type(e).__name__}: {e}) — reconnecting in {ERROR_BACKOFF_SECONDS}s")
            traceback.print_exc()
            with contextlib.suppress(Exception):
                if conn is not None:
                    conn.close()
            conn = None
            held = None
            time.sleep(ERROR_BACKOFF_SECONDS)

    with contextlib.suppress(Exception):
        if conn is not None:
            conn.close()
    _log("stopped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
