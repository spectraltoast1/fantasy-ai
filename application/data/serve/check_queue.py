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
import sys
import time

import psycopg
from psycopg.rows import dict_row

from application.api import db
from application.data.serve import job_queue as q

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
        if again and again["id"] == c_job["id"] and again["attempts"] == held["attempts"] + 1:
            _ok(f"an EXPIRED lease is reclaimed by another worker (attempts "
                f"{held['attempts']} → {again['attempts']}), leased_by now {again['leased_by']!r}")
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


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--live", action="store_true",
                    help="also exercise the lease against a real database (throwaway rows only)")
    args = ap.parse_args()

    print("=== job queue ===")
    check_shape()
    if args.live:
        check_live()
    else:
        print("\n(skipping the live lease — pass --live. SKIP LOCKED is a concurrency primitive "
              "and cannot be proven offline.)")

    failed = _results.count(False)
    print()
    if failed:
        print(f"FAILED — {failed} of {len(_results)} assertions")
        return 1
    print(f"ALL GREEN — {len(_results)}/{len(_results)} assertions — work reaches the worker, "
          "exactly once, and a dead worker's league comes back.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
