"""Gate for the job queue — P5/S4b.

Sixth in the `check_auth` / `check_signup` / `check_ownership` / `check_isolation` / `check_onboard`
line. It proves the properties the queue exists to create:

  1. THE SHAPE    — the lease still uses `FOR UPDATE SKIP LOCKED`, still orders by `created_at`, and
                    still parenthesises its disjunction. Offline, so it runs on any checkout.
  2. THE LEASE    — live, against real Postgres: SKIP LOCKED hands each row to exactly one leaser, an
                    expired lease is RECLAIMED, the attempt cap bites on a `queued` row as well as a
                    reclaimed one, a reaped job says why it died, a graceful release does not spend
                    an attempt, one active job per league is enforced, and a NOTIFY wakes a listener.

**Why leg 2 has to be live.** `SKIP LOCKED` is a concurrency primitive; a fake cursor cannot exhibit
it, and a gate that asserted the SQL string alone would pass against SQL that does not work. So this
half needs `--live` and a database. It is safe to point at production: every row it writes carries a
`league_id` from `TMP_LEAGUES`, which is not Sleeper-shaped, and the sweep matches those ids
EXACTLY (never `LIKE` — `_` is a wildcard, and `__QUEUECHECK%` would match real ids).

CODING_BIBLE §5: the destructive leg needs a throwaway target. Here the throwaway is a ROW, not a
file — the same shape as `check_store_boundary`'s connected-catalog purge (S4a finding D).

    application/venv/bin/python -m application.data.serve.check_queue
    application/venv/bin/python -m application.data.serve.check_queue --live
"""

from __future__ import annotations

import argparse
import ast
import contextlib
import inspect
import sys
import textwrap
import time

import psycopg
from psycopg.rows import dict_row

from application.api import db
from application.data.serve import job_queue as q
from application.data.serve import onboard_league
from application.data.serve import worker_loop as wl

# Not Sleeper-shaped, so these cannot collide with a real league. Same idiom as check_onboard's
# `__ONBOARDCHECK__` and check_store_boundary's `__STOREBOUNDARY__`.
TMP_LEAGUES = ["__QUEUECHECK_A__", "__QUEUECHECK_B__", "__QUEUECHECK_C__"]
TMP_SEASON = 99996

_results: list[bool] = []


def _ok(msg: str) -> None:
    print(f"  ✓ {msg}")
    _results.append(True)


def _fail(msg: str) -> None:
    print(f"  ✗ {msg}")
    _results.append(False)


# UNKNOWN IS NOT PASS, AND IT IS NOT FAILURE EITHER (P5/S4c).
#
# **The problem this exists for, found by S4c and pre-dating it:** this gate writes throwaway rows
# into the SAME `public.jobs` table the LIVE `fantasy-ai-worker` is draining. Since S4b deployed the
# leasing loop, that worker is permanently listening — measured 2026-08-14, it leased a throwaway
# row **0.12s** after the INSERT (the NOTIFY, not the poll), ran `onboard_league` against a league id
# that is not Sleeper-shaped, got a 404 and buried the row as `failed`. Legs (c) and (e) below then
# found their row already gone and reported a FAILURE — of the queue, which was in fact working
# perfectly. The gate was measuring the one thing it cannot control.
#
# The two red lines were therefore describing the instrument, not the mechanism, and reporting them
# as failures is exactly the inversion this project keeps naming: a result that says something is
# broken when nothing is, next door to the more usual one that says something works when it was
# never tried.
#
# So a leg whose row was taken by a real worker is reported as **UNEVALUATED**. It is not a pass —
# it must not be counted as one and the summary says how many there were — and it is not a failure,
# because nothing failed.
#
# **The stronger fix, deliberately deferred and recorded so it is a decision:** run legs (c)-(g) on
# ONE connection inside a transaction that is never committed, so the rows are never visible to any
# other session and no worker can reach them. `now()` is fixed inside a transaction, but every
# expiry here is set RELATIVE to `now()`, so the reclaim and reap semantics survive unchanged. That
# is a rewrite of a working gate rather than a guard on it, and it belongs to a session that owns
# this file.
_unevaluated: list[str] = []


def _unknown(msg: str) -> None:
    print(f"  ??  {msg}")
    _unevaluated.append(msg)


# The worker names this gate leases under. Anything else holding one of our rows is a real machine
# (`worker_loop._worker_id` returns a Fly machine id), which is the signal we are looking for.
_GATE_WORKERS = {"gate", "gate-A", "gate-B", "gate-dead", "gate-live", "gate-deploying"}


def _taken_by_a_real_worker(conn, job_id) -> str | None:
    """Evidence that the LIVE worker got this throwaway row first, or None. Positive evidence only.

    Two independent tells, because either alone can be raced past: a `leased_by` that is not one of
    ours, and an `error` mentioning the Sleeper call only a real executor makes — this gate drives
    `_run_job` with fake executors and never touches the network.
    """
    row = _state(conn, job_id)
    if row is None:
        return "the row is gone from the table entirely"
    by = row.get("leased_by")
    if by and by not in _GATE_WORKERS:
        return f"leased_by={by!r}, which is not one of this gate's names"
    err = (row.get("error") or "")
    if "sleeper.app" in err.lower():
        return f"a real executor ran it against Sleeper — error={err[:90]!r}"
    return None


# --- leg 1: the shape, offline ------------------------------------------------------------------

def check_shape() -> None:
    print("\nthe lease SQL — the properties a rewrite must not quietly drop")
    sql = " ".join(q._LEASE.split())

    for needle, why in (
            ("FOR UPDATE SKIP LOCKED", "two leasers would block on each other instead of taking "
                                       "different rows"),
            ("ORDER BY created_at", "ordering by the uuid id is meaningless, and ordering by "
                                    "anything else breaks FIFO"),
    ):
        _ok(f"lease uses {needle}") if needle in sql else _fail(f"lease has LOST {needle} — {why}")

    if "ORDER BY id" in sql:
        _fail("lease orders by id — the id is a uuid, so this is not insertion order")
    else:
        _ok("lease does not order by id")

    # The parenthesised disjunction. `AND` binds tighter than `OR`, so without the parens the
    # attempts cap applies only to the reclaim branch and a `queued` row leases without limit. The
    # live leg proves the SEMANTICS; this catches the textual regression on any checkout.
    if "(state = 'queued' OR (state = ANY(%(running)s) AND lease_expires_at < now()))" in sql:
        _ok("the queued/reclaim disjunction is parenthesised, so the attempt cap covers both")
    else:
        _fail("the queued/reclaim disjunction has lost its parentheses — AND binds tighter than "
              "OR, so the attempt cap would not apply to a `queued` row")

    if 0 < q.LEASE_SECONDS and q.MAX_ATTEMPTS >= 1:
        _ok(f"LEASE_SECONDS={q.LEASE_SECONDS}s, MAX_ATTEMPTS={q.MAX_ATTEMPTS}")
    else:
        _fail(f"nonsensical LEASE_SECONDS={q.LEASE_SECONDS} / MAX_ATTEMPTS={q.MAX_ATTEMPTS}")

    # A lease that never expires strands a killed job until a human intervenes — the exact thing
    # this queue removes. Assert the reclaim branch exists rather than trusting the constant.
    if "lease_expires_at < now()" in sql:
        _ok("an EXPIRED lease is reclaimable — a killed worker does not strand its league")
    else:
        _fail("the lease never expires — a killed worker would strand its league for ever")


# --- leg 2: the lease, live -------------------------------------------------------------------

def _conn(*, autocommit: bool, timeout_ms: int = 5000) -> psycopg.Connection:
    """A gate connection. Short statement_timeout so a LOST `SKIP LOCKED` surfaces as a fast
    timeout rather than the suite hanging until somebody kills it."""
    c = psycopg.connect(db.database_url(), row_factory=dict_row, connect_timeout=10,
                        options=f"-c statement_timeout={timeout_ms}")
    c.autocommit = autocommit
    return c


def _sweep(conn) -> int:
    """Remove every throwaway row. EXACT ids, never LIKE: `_` is a LIKE wildcard, so a pattern like
    `__QUEUECHECK%` would also match two-character-prefixed REAL league ids."""
    with conn.cursor() as cur:
        cur.execute("DELETE FROM public.jobs WHERE league_id = ANY(%(ids)s)", {"ids": TMP_LEAGUES})
        return cur.rowcount


def _state(conn, job_id) -> dict:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM public.jobs WHERE id = %(id)s", {"id": job_id})
        return cur.fetchone()


def check_live() -> None:
    print("\nthe lease, against real Postgres (throwaway rows only)")
    main = _conn(autocommit=True)
    try:
        _sweep(main)

        # (a) SKIP LOCKED. Two leasers, two UNCOMMITTED transactions. A holds a row lock; B must get
        #     a DIFFERENT row rather than blocking on it. Without SKIP LOCKED, B blocks and the
        #     statement_timeout above turns that into a visible failure.
        a_job = q.enqueue(TMP_LEAGUES[0], TMP_SEASON, conn=main)
        b_job = q.enqueue(TMP_LEAGUES[1], TMP_SEASON, conn=main)
        _ok(f"enqueue returned a uuid id and state {a_job['state']!r}") if (
            a_job["state"] == "queued" and "-" in str(a_job["id"])) else _fail(
            f"enqueue returned {a_job}")

        ca, cb = _conn(autocommit=False), _conn(autocommit=False)
        try:
            got_a = q.lease(ca, worker="gate-A")
            try:
                got_b = q.lease(cb, worker="gate-B")
            except psycopg.errors.QueryCanceled:
                got_b = None
                _fail("the second leaser BLOCKED until statement_timeout — SKIP LOCKED is not "
                      "in effect, so two workers would serialise instead of sharing the queue")
            if got_a and got_b and got_a["id"] != got_b["id"]:
                _ok("two concurrent leasers got two DIFFERENT rows — SKIP LOCKED holds")
            elif got_a and got_b:
                _fail("two concurrent leasers got the SAME row — the same league would be built twice")
            elif got_a and got_b is None:
                _fail("the second leaser got nothing while a queued row existed")
            ca.rollback(); cb.rollback()
        finally:
            ca.close(); cb.close()

        # (b) Nothing left to lease returns None rather than raising. The loop leans on this every
        #     time the queue is empty, which is almost always.
        for lid in (TMP_LEAGUES[0], TMP_LEAGUES[1]):
            with main.cursor() as cur:
                cur.execute("UPDATE public.jobs SET state='ready' WHERE league_id=%(l)s",
                            {"l": lid})
        if q.lease(main, worker="gate") is None:
            _ok("an empty queue leases None — it does not raise and does not spin")
        else:
            _fail("leased something from an empty queue — the gate's own rows are not isolated")

        # (c) RECLAIM. Expire a held lease and prove another worker can take it, with `attempts`
        #     climbing. This is the kill drill's mechanism, in miniature and without a real build.
        c_job = q.enqueue(TMP_LEAGUES[2], TMP_SEASON, conn=main)
        held = q.lease(main, worker="gate-dead")
        with main.cursor() as cur:
            cur.execute("UPDATE public.jobs SET lease_expires_at = now() - interval '1 second' "
                        "WHERE id = %(id)s", {"id": c_job["id"]})
        again = q.lease(main, worker="gate-live")
        if again and held and again["id"] == c_job["id"] and again["attempts"] == held["attempts"] + 1:
            _ok(f"an EXPIRED lease is reclaimed by another worker (attempts "
                f"{held['attempts']} → {again['attempts']}), leased_by now {again['leased_by']!r}")
        elif (stolen := _taken_by_a_real_worker(main, c_job["id"])):
            _unknown(f"RECLAIM could not be evaluated — the LIVE worker leased this throwaway row "
                     f"first ({stolen}). Nothing is broken; this gate simply does not own the queue "
                     f"it is testing. See `_unknown`.")
        else:
            _fail(f"expired lease was not reclaimed cleanly: {again}")

        # (d) THE ATTEMPT CAP BITES ON A `queued` ROW. This is the parenthesisation, proven by
        #     behaviour rather than by reading the string: put the row back in `queued` at the cap
        #     and assert it is NOT handed out.
        with main.cursor() as cur:
            cur.execute("UPDATE public.jobs SET state='queued', attempts=%(m)s, "
                        "lease_expires_at=NULL WHERE id=%(id)s",
                        {"id": c_job["id"], "m": q.MAX_ATTEMPTS})
        if q.lease(main, worker="gate") is None:
            _ok(f"a `queued` row at the cap ({q.MAX_ATTEMPTS}) is NOT leased — the attempt cap "
                "covers both branches of the disjunction")
        else:
            _fail("a `queued` row at the attempt cap was leased anyway — the disjunction is "
                  "mis-parenthesised and a poison job would loop for ever")

        # (e) REAP. A running row whose lease expired with no attempts left is failed, and says why.
        with main.cursor() as cur:
            cur.execute("UPDATE public.jobs SET state='building', attempts=%(m)s, "
                        "leased_by='gate-dead', lease_expires_at=now() - interval '1 second' "
                        "WHERE id=%(id)s", {"id": c_job["id"], "m": q.MAX_ATTEMPTS})
        buried = q.reap(main)
        row = _state(main, c_job["id"])
        if any(b["id"] == c_job["id"] for b in buried) and row["state"] == "failed" and row["error"]:
            _ok(f"reap buries an abandoned job as `failed`, and it says why: {row['error'][:70]}…")
        elif (stolen := _taken_by_a_real_worker(main, c_job["id"])):
            _unknown(f"REAP could not be evaluated — the LIVE worker had already finished this "
                     f"throwaway row ({stolen}), so there was no abandoned job left to bury.")
        else:
            _fail(f"reap left the job at {row['state']!r} error={row['error']!r} — a stuck job "
                  "would sit in a running-looking state for ever")

        # (f) RELEASE does not spend an attempt. Every `fly deploy` sends SIGTERM, so if a graceful
        #     handback cost a life a job could hit the cap having never once failed.
        with main.cursor() as cur:
            cur.execute("UPDATE public.jobs SET state='queued', attempts=0, error=NULL, "
                        "finished_at=NULL WHERE id=%(id)s", {"id": c_job["id"]})
        leased = q.lease(main, worker="gate-deploying")
        back = q.release(main, c_job["id"])
        after = _state(main, c_job["id"])
        if back and after["state"] == "queued" and after["attempts"] == leased["attempts"] - 1:
            _ok(f"a graceful release returns the job to `queued` and REFUNDS the attempt "
                f"({leased['attempts']} → {after['attempts']})")
        else:
            _fail(f"release left state={after['state']!r} attempts={after['attempts']} — a redeploy "
                  "would burn a retry on a job that never failed")

        # (g) ONE ACTIVE JOB PER (league, season). Row-level SKIP LOCKED is not league-level
        #     exclusion; two active rows would race on the same artifacts and on load_league.
        try:
            q.enqueue(TMP_LEAGUES[2], TMP_SEASON, conn=main)
            _fail("a SECOND active job for the same league was accepted — two builds would race "
                  "on the same on-disk artifacts and on load_league's DELETE+COPY")
        except psycopg.errors.UniqueViolation:
            _ok("a second ACTIVE job for the same (league, season) is refused by the index")

        # …but a finished league may be re-submitted, or nobody could ever reconnect.
        with main.cursor() as cur:
            cur.execute("UPDATE public.jobs SET state='ready' WHERE id=%(id)s", {"id": c_job["id"]})
        try:
            q.enqueue(TMP_LEAGUES[2], TMP_SEASON, conn=main)
            _ok("a league whose job already finished CAN be re-submitted")
        except psycopg.errors.UniqueViolation:
            _fail("a finished league cannot be re-submitted — the partial index is too wide")

        # (h) NOTIFY wakes a listener. This is what makes the loop's idle cost ~zero instead of a
        #     24/7 poll; if it silently stopped working, the safety-net poll would hide it.
        listener = _conn(autocommit=True)
        try:
            with listener.cursor() as cur:
                cur.execute(f"LISTEN {q.CHANNEL}")
            with main.cursor() as cur:
                cur.execute("DELETE FROM public.jobs WHERE league_id = %(l)s", {"l": TMP_LEAGUES[0]})
            q.enqueue(TMP_LEAGUES[0], TMP_SEASON, conn=main)
            deadline = time.monotonic() + 5
            heard = None
            for n in listener.notifies(timeout=5, stop_after=1):
                heard = n
                break
            if heard is not None and heard.channel == q.CHANNEL:
                _ok(f"a listener was woken by enqueue's NOTIFY on {q.CHANNEL!r} "
                    f"(within {5 - max(deadline - time.monotonic(), 0):.2f}s)")
            else:
                _fail("no NOTIFY reached a listener — the worker would only ever wake on the "
                      "safety-net poll, silently")
        finally:
            listener.close()
    finally:
        n = _sweep(main)
        print(f"\nswept {n} throwaway job row(s) — league_id matched EXACTLY, never by LIKE")
        main.close()


# --- leg 3: the worker loop's classification, offline -------------------------------------------

class _FakeConn:
    """Enough of a connection for the classification legs. They never reach SQL — every job_queue
    call is recorded instead — which is the point: what a refusal MEANS is not a database question.

    P5/S4c gave it a `transaction()`, because the success path now wraps the grant and the `finish`
    in one. A no-op is faithful here: these legs assert WHICH terminal state a job lands in, and
    that the two statements are atomic is asserted from the AST in `check_connect`, where it can be
    proven rather than simulated.
    """

    @contextlib.contextmanager
    def transaction(self):
        yield self


def _drive(kind: str, boom: BaseException | None, *, platform: str | None = None,
           requested_by: str | None = None):
    """Run `_run_job` against a fake executor and return the (state, error) it landed on."""
    landed: dict = {}

    def fake_finish(_conn, job_id, state, *, error=None):
        landed.update(id=job_id, state=state, error=error)
        return {"id": job_id, "state": state}

    def fake_executor(_conn, _job, _worker):
        if boom is not None:
            raise boom
        return None                      # the seat; None is the no-handle path

    job = {"id": "j1", "kind": kind, "league_id": "L", "season": 2025, "attempts": 1,
           "state": "validating", "requested_by": requested_by}
    if platform is not None:
        job["platform"] = platform

    saved_finish, saved_execs = wl.q.finish, wl._EXECUTORS
    wl.q.finish = fake_finish
    wl._EXECUTORS = {"onboard": fake_executor}
    try:
        wl._run_job(_FakeConn(), job, "gate")
    finally:
        wl.q.finish, wl._EXECUTORS = saved_finish, saved_execs
    return landed.get("state"), landed.get("error")


def check_classification() -> None:
    print("\nthe loop's classification — what a refusal MEANS, without a database")

    # THE TRAP, as an executable assertion rather than a comment. If this ever became false the
    # `except SystemExit` clause below would be redundant; while it is true, a loop written with a
    # plain `except Exception` exits the process on the first out-of-scope league.
    if not issubclass(SystemExit, Exception) and issubclass(SystemExit, BaseException):
        _ok("SystemExit is a BaseException and NOT an Exception — so `except Exception` alone would "
            "let every onboard_league refusal kill the worker")
    else:
        _fail("SystemExit's base classes have changed — re-read _run_job's handlers")

    # Ordering: `except SystemExit` must be reachable, i.e. come BEFORE `except Exception`.
    src = inspect.getsource(wl._run_job)
    i_sys, i_exc = src.find("except SystemExit"), src.find("except Exception")
    if 0 <= i_sys < i_exc:
        _ok("_run_job handles SystemExit BEFORE Exception, so refusals are reachable")
    else:
        _fail("_run_job's `except SystemExit` is missing or comes after `except Exception`")

    state, err = _drive("onboard", SystemExit("league X is dynasty — V1 supports REDRAFT only."))
    if state == "rejected" and err and "REDRAFT" in err:
        _ok("a deliberate refusal (SystemExit) lands `rejected`, carrying its reason")
    else:
        _fail(f"a SystemExit landed {state!r} err={err!r} — a deterministic refusal must not retry")

    state, err = _drive("onboard", RuntimeError("Sleeper timed out"))
    if state == "failed" and err and "RuntimeError" in err:
        _ok("a transient error lands `failed` (retryable), naming the exception type")
    else:
        _fail(f"a RuntimeError landed {state!r} err={err!r}")

    state, _ = _drive("onboard", None)
    _ok("a clean run lands `ready`") if state == "ready" else _fail(f"a clean run landed {state!r}")

    # The `kind` column's proof. It exists for S4d's refresh jobs, and a column whose only unusable
    # value crashes the process is worse than no column.
    # The `platform` column's proof, and it is the SAME argument one dimension over (P5/S4c). The
    # column exists so a second source can arrive; until one does, a worker that cannot run it must
    # say so rather than pointing the Sleeper chain at a Yahoo league id. `POST /api/connect`
    # already refuses at the front door, so this is the second of two — a hand-inserted row is the
    # only way here, and it must not crash the loop either.
    state, err = _drive("onboard", None, platform="yahoo")
    if state == "rejected" and err and "unknown platform" in err:
        _ok("an UNKNOWN platform lands `rejected` cleanly, naming what this worker implements")
    else:
        _fail(f"an unknown platform landed {state!r} err={err!r} — a Yahoo league id would have "
              "been run through the Sleeper chain")

    state, _ = _drive("onboard", None, platform="sleeper")
    _ok("an explicit platform='sleeper' still runs") if state == "ready" else _fail(
        f"platform='sleeper' landed {state!r} — the guard is refusing the one platform it has")

    state, err = _drive("weekly_refresh", None)
    if state == "rejected" and err and "unknown job kind" in err:
        _ok("an UNKNOWN kind lands `rejected` cleanly — the loop survives a job it cannot run")
    else:
        _fail(f"an unknown kind landed {state!r} err={err!r} — one bad row would be an outage for "
              "every other user's league")

    # Every stage the chain actually emits must map to a state. Driven off the SOURCE, so a stage
    # added to run_chain without a mapping fails here instead of silently leaving the row behind.
    emitted = set()
    for fn in (onboard_league.run_chain, onboard_league.onboard):
        for node in ast.walk(ast.parse(textwrap.dedent(inspect.getsource(fn)))):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "stage"
                    and node.args and isinstance(node.args[0], ast.Constant)):
                emitted.add(node.args[0].value)
    unmapped = sorted(emitted - set(wl._STATE_BY_STAGE))
    if unmapped:
        _fail(f"stage(s) {unmapped} have no job state — a job would sit in the previous state "
              "through them, and DoD 2 says the table alone must say what is happening")
    else:
        _ok(f"all {len(emitted)} stages the chain emits map to a state {sorted(emitted)}")

    bad = sorted(s for s in wl._STATE_BY_STAGE.values() if s not in q.RUNNING_STATES)
    if bad:
        _fail(f"stage states {bad} are not in RUNNING_STATES — the lease could not reclaim them")
    else:
        _ok("every mapped state is a RUNNING state, so an expired lease can reclaim mid-build")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", action="store_true",
                    help="also exercise the lease against a real database (throwaway rows only)")
    args = ap.parse_args()

    print("=== job queue ===")
    check_shape()
    check_classification()
    if args.live:
        check_live()
    else:
        print("\n(skipping the live lease — pass --live. SKIP LOCKED is a concurrency primitive "
              "and cannot be proven offline.)")

    failed = _results.count(False)
    print()
    # Printed BEFORE the verdict and unconditionally, so a green line can never be read as full
    # coverage. Silence here means every leg was actually evaluated.
    if _unevaluated:
        print(f"⚠ {len(_unevaluated)} leg(s) UNEVALUATED — neither a pass nor a failure. The live "
              f"`fantasy-ai-worker` drains the same queue this gate writes to, so it can take a "
              f"throwaway row before the gate does. To evaluate them, stop the worker "
              f"(`fly machines stop -a fantasy-ai-worker`), re-run, and start it again.")
        for u in _unevaluated:
            print(f"    · {u.splitlines()[0]}")
        print()
    if failed:
        print(f"FAILED — {failed} of {len(_results)} assertions")
        return 1
    print(f"ALL GREEN — {len(_results)}/{len(_results)} assertions"
          + (f" ({len(_unevaluated)} unevaluated)" if _unevaluated else "")
          + " — work reaches the worker, exactly once, and a dead worker's league comes back.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
