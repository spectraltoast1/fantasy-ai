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
"""

from __future__ import annotations

import contextlib
import os
import signal
import socket
import sys
import time
import traceback

from application.data import data_layer as dl
from application.data.serve import job_queue as q
from application.data.serve import onboard_league

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


def _execute_onboard(conn, job, worker: str) -> None:
    onboard_league.onboard(job["league_id"], int(job["season"]),
                           stage=_stage_observer(conn, job, worker))


# One entry per job class. `kind` exists because S4d enqueues the weekly refresh; the Manager
# Dossier fan-out is a deferred class and belongs to S4c. An unknown kind is REJECTED, not a crash —
# which is also how the column earns its keep before a second executor exists.
_EXECUTORS = {"onboard": _execute_onboard}


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

    try:
        executor(conn, job, worker)
    except SystemExit as e:
        # THE TRAP. `SystemExit` is a BaseException, so this clause must come BEFORE `except
        # Exception` and cannot be folded into it. onboard_league raises it for every deliberate
        # refusal — out of scope, wrong season, not cold, first on its scoring key — and every one
        # of those is DETERMINISTIC: the same job would be refused identically for ever, so it is
        # terminal on the first attempt rather than retried to the cap.
        q.finish(conn, job["id"], "rejected", error=str(e) or repr(e))
        _log(f"REJECTED {label}: {str(e).splitlines()[0] if str(e) else e!r}")
    except (_Shutdown, _LeaseLost):
        raise
    except Exception as e:                                     # noqa: BLE001 — see the docstring
        # Everything else is a FAILURE, and failures are retryable: Sleeper timing out, the network,
        # a stale shared band (StoreBoundaryError), a bug. `reap` turns the last attempt into a
        # terminal `failed` so nothing sits in a running-looking state for ever.
        q.finish(conn, job["id"], "failed",
                 error=f"{type(e).__name__}: {e}"[:4000])
        _log(f"FAILED {label}: {type(e).__name__}: {e}")
        traceback.print_exc()
        return
    else:
        q.finish(conn, job["id"], "ready")
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
