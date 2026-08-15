"""The weekly cadence's PRODUCER — enqueue one refresh job per connected league (P5/S4d).

This is what `.github/workflows/weekly_refresh.yml` runs. It is the whole job: enumerate the
leagues somebody owns in the current season, and put a `refresh` row on the queue for each. The
worker does the rest.

**Why this is Python and not one `INSERT … SELECT` in the workflow YAML.** The obvious version is
smaller — no checkout, no interpreter, one `psql` call — and it is wrong for three reasons, the
third of which is the one that settles it:

  1. A raw INSERT **forgets the NOTIFY**. `jobs.enqueue` sends `pg_notify('jobs_new', …)` and the
     worker's whole responsiveness is built on it; without it a refresh row waits on the 60s safety
     poll. Not fatal for a weekly cron — and exactly the kind of quiet divergence that makes two
     producers drift.
  2. It would re-derive the season. `settings.current_season()` is the ONE home for the calendar
     rule (S2c deleted the alternative deliberately); an `EXTRACT(YEAR …)` with an August boundary
     in SQL is a second copy that rots in January.
  3. **It would have left the gate GREEN.** `check_connect`'s ONE SEAM leg asserts
     `INSERT INTO public.jobs` executes from exactly one place — and it scans
     `application/**/*.py`. SQL embedded in YAML is invisible to that scan, so the second producer
     would arrive through the one door the gate cannot see. The gate's own failure text names the
     hazard: *"the one that drifts is the one that forgets the NOTIFY."*

So the workflow keeps a checkout and calls this. The cost is deliberately bounded: it installs
`api/requirements.txt`, NOT `application/requirements.txt` — no polars, no numpy, no pipeline. It
imports only from `application/api/`, which is why the workflow also drops `STORE_ROLE`: this
process cannot reach a store writer at all, and that is not an observation but an enforced
invariant (`check_connect`'s ONE IMAGE leg fails on any `application.data` import under `api/`).

**Why the source is `user_leagues ⋈ league_catalog` and not the catalog alone.** Two reasons, and
the second is a live hazard rather than a preference:

  * The catalog holds the 31 frozen corpus slices and the generated demo clone as well as real
    connected leagues. Nobody OWNS those, so joining through `user_leagues` selects exactly the
    leagues a human is waiting on.
  * `DEMO-2025` is SYNTHETIC, and `weekly_refresh` raises on a synthetic league by design (S2d's
    producer-side rule: the clone does not exist on Sleeper, so fetching it is incoherent). Driving
    from `league_catalog` would therefore enqueue a guaranteed refusal **every single week**.
    Through `user_leagues` it falls out twice over — nobody owns it, and it is a 2025 league.

**On the season filter.** `user_leagues` has no `season` column, deliberately
(`auth_schema.sql`: "the current-season term is applied at read time by joining the catalog"), so
the season comes from the catalog row. This is the same shape `reads.visible` applies to its owned
term, which is what keeps the cadence from refreshing a league its own owner cannot see.
"""

from __future__ import annotations

import argparse
import sys

import psycopg

from application.api import db, jobs, settings

# Current-season leagues that somebody owns, minus anything already in flight.
#
# DISTINCT is load-bearing, not tidiness: `user_leagues`' primary key is (user_id, league_id), so a
# league with two owners returns two rows — the designed case, proven in S4c with two accounts
# holding seats 1 and 2 of the same league. Without it the second row hits `jobs_active_league_idx`
# and the run reports a failure for a league that is perfectly fine.
#
# NOT EXISTS rather than ON CONFLICT DO NOTHING, for a reason worth stating. The index is UNIQUE
# PARTIAL on (league_id, season) WHERE state is non-terminal, and it does NOT include `kind` — so a
# refresh collides with an in-flight ONBOARD too, which is correct (a league being built for the
# first time does not also need advancing). Filtering here makes that collision a row that was
# never inserted, rather than an exception to catch and explain away. Wednesday's catch-up run
# skipping a league Tuesday is still working on is the DESIGNED outcome, and it must not read as an
# error — see the run summary below, which counts it separately.
_CONNECTED = """
SELECT DISTINCT c.league_id, c.season
FROM public.league_catalog c
JOIN public.user_leagues u ON u.league_id = c.league_id
WHERE c.season = %(season)s
ORDER BY c.league_id
"""

_ACTIVE = """
SELECT league_id, season FROM public.jobs
WHERE state NOT IN ('ready', 'rejected', 'failed')
"""


def enumerate_due(conn, season: int) -> tuple[list[dict], list[dict]]:
    """`(due, skipped)` — the connected leagues for `season`, split on whether one is already active.

    Returned rather than enqueued here so the decision is separable from the side effect: the
    workflow's `--dry-run` prints exactly what a real run would do, against the real database.
    """
    with conn.cursor() as cur:
        cur.execute(_CONNECTED, {"season": int(season)})
        connected = [dict(r) for r in cur.fetchall()]
        cur.execute(_ACTIVE)
        active = {(str(r["league_id"]), int(r["season"])) for r in cur.fetchall()}

    due, skipped = [], []
    for row in connected:
        key = (str(row["league_id"]), int(row["season"]))
        (skipped if key in active else due).append(row)
    return due, skipped


def run(*, season: int | None = None, dry_run: bool = False) -> dict:
    """Enqueue one `refresh` job per connected league. Returns a report of what it did."""
    season = int(season if season is not None else settings.current_season())
    report: dict = {"season": season, "enqueued": [], "skipped": [], "errors": []}

    # ONE connection for the whole run, shared with every `enqueue` call. `jobs.enqueue` commits and
    # closes only a connection it opened ITSELF, so passing `conn` leaves the lifecycle here.
    with db.connect() as conn:
        due, skipped = enumerate_due(conn, season)
        report["skipped"] = [r["league_id"] for r in skipped]

        print(f"=== weekly cadence: {len(due) + len(skipped)} connected league(s) for {season} "
              f"— {len(due)} due, {len(skipped)} already in flight ===")
        for r in skipped:
            print(f"  · {r['league_id']} — a job is already active; skipping (this is not an error)")

        if dry_run:
            for r in due:
                print(f"  · {r['league_id']} — WOULD enqueue refresh ({season})")
            report["enqueued"] = [r["league_id"] for r in due]
            return report

        for r in due:
            lid = str(r["league_id"])
            try:
                job = jobs.enqueue(lid, int(r["season"]), kind="refresh", conn=conn)
            except psycopg.Error as exc:
                # A league that lost the race between our SELECT and our INSERT — the worker or a
                # concurrent run claimed it. Report it, do not fail the workflow over it: the whole
                # point of the catch-up cron is that a second run is harmless.
                report["errors"].append({"league_id": lid, "error": str(exc).strip()})
                print(f"  ✗ {lid} — {type(exc).__name__}: {str(exc).strip().splitlines()[0]}")
                continue
            report["enqueued"].append(lid)
            print(f"  ✓ {lid} — enqueued refresh, job {job['id']}")

    # The workflow's exit code. A run that enqueued nothing because nothing was due is a SUCCESS —
    # trap (a) of this session's brief: for a catch-up cron a no-op is the correct outcome, and
    # treating it as a failure would email an alert every Wednesday for ever. A run that could not
    # enqueue something it meant to is a real failure and exits non-zero, which is how the
    # collectors' coverage gate already turns a problem into GitHub's built-in failure email.
    print(f"\nenqueued {len(report['enqueued'])}, skipped {len(report['skipped'])} "
          f"(already active), {len(report['errors'])} error(s)")
    return report


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Enqueue a weekly refresh job for every connected league (P5/S4d).")
    ap.add_argument("--season", type=int, default=None,
                    help="override the derived current season (testing; the cron never passes it)")
    ap.add_argument("--dry-run", action="store_true",
                    help="enumerate and print, enqueue nothing — runs the REAL query")
    args = ap.parse_args()

    report = run(season=args.season, dry_run=args.dry_run)
    sys.exit(1 if report["errors"] else 0)


if __name__ == "__main__":
    main()
