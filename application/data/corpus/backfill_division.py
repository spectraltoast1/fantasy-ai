"""
backfill_division.py — Session 3d commit 2: activate division-aware playoff seeding on the corpus.

3a's teams fetcher dropped `settings.division` (the per-roster division assignment lives only on the
/rosters endpoint), so every harvested division league was silently seeded FLAT — `_division_map` returns
None, `_seed_table` never receives a division array, and division winners are not lifted ahead of wildcards.
The measurement reads still computed and passed mass-integrity (flat seeding still seats exactly
`playoff_teams`), but the seed ORDER — hence the whole made-playoffs distribution — was wrong for a division
league (standing instruction 7: "artifact exists" ≠ "consumer correct").

This is the ONE sanctioned fetch of Session 3d (a static historical fact for a completed league — near-zero
drift). It is SCOPED TO THE GENERALIZATION STRATUM (`never_tune`): the 14 generalization division leagues are
where the any-league division path is CERTIFIED. The 11 matched division leagues are deliberately LEFT FLAT —
their frozen 3b/3c spine must not move (standing instruction 2); backfilling division onto them would change
their bracket_odds. So this driver only ever touches generalization teams, and `_division_map` returns None
for the (untouched, division-column-less) matched teams — matched bracket_odds stays byte-identical.

Per league: additively persist `division` onto the existing teams entity (sleeper.backfill_division — a
left-join that preserves the name columns byte-identical) → recompute `bracket_odds` with the league-stable
seed, now division-aware. Idempotent + per-league failure isolated + budget reported.

Usage:
    python3 -m application.data.corpus.backfill_division --dry-run   # fetch + activate, no bracket recompute
    python3 -m application.data.corpus.backfill_division             # the 14 generalization division leagues
"""
import argparse
import contextlib
import io
import sys
import time
from collections import defaultdict

import polars as pl

from application.data import data_layer
from application.data.fetchers import sleeper
from application.data.transforms import compute_bracket_sim


@contextlib.contextmanager
def _quiet():
    with contextlib.redirect_stdout(io.StringIO()):
        yield


def targets(limit=None) -> list[dict]:
    """The generalization division leagues (manifest has_divisions ∧ stratum==generalization), deterministic
    order. Scoped to generalization on purpose — matched division leagues stay frozen-flat (see module doc)."""
    man = data_layer.read_corpus_manifest()
    rows = [r for r in man.iter_rows(named=True)
            if r["stratum"] == "generalization" and bool(r["has_divisions"])]
    rows.sort(key=lambda r: (int(r["season"]), str(r["league_id"])))
    return rows[:limit] if limit else rows


def _mass_ok(masses, playoff_teams, tol=0.02) -> bool:
    """Spent playoff mass at every as-of week equals the slot count (holds under flat OR division seeding —
    both seat exactly `playoff_teams`; this guards that the recompute didn't break the invariant)."""
    return all(abs(m - playoff_teams) <= tol for m in masses)


def run(limit=None, dry_run=False, throttle: float = 0.1) -> dict:
    sleeper.set_throttle(throttle)
    tgts = targets(limit)
    t0 = time.time()
    div_status = defaultdict(int)      # added/refreshed/unchanged/no-divisions/absent
    recomputed = 0
    activated, mass_bad, errored = [], [], []
    timing = defaultdict(float)

    for i, r in enumerate(tgts, 1):
        lid, season, sk = str(r["league_id"]), int(r["season"]), str(r["scoring_key"])
        tag = f"[{i}/{len(tgts)}] {lid} {season} {sk}"
        try:
            t = time.time()
            st = sleeper.backfill_division(lid, season)
            timing["fetch_division"] += time.time() - t
            div_status[st] += 1

            dm = compute_bracket_sim._division_map(season, league_id=lid)
            ndiv = len(set(dm.values())) if dm else 0
            if dm:
                activated.append((lid, season, ndiv))

            if dry_run:
                print(f"  {tag}  division:{st:11}  _division_map={ndiv} divisions (dry-run, no recompute)")
                continue

            t = time.time()
            with _quiet():
                compute_bracket_sim.run(season, league_id=lid, scoring_key=sk)
            timing["bracket_odds"] += time.time() - t
            recomputed += 1

            # Verify the spent-mass invariant survived the division-aware recompute.
            bo = data_layer.read_bracket_odds(season, league_id=lid, as_of_week="all")
            _reg, pt = compute_bracket_sim._playoff_config(season, league_id=lid)
            masses = bo.group_by("as_of_week").agg(pl.col("playoff_odds").sum().alias("m"))["m"].to_list()
            ok = _mass_ok(masses, pt)
            if not ok:
                mass_bad.append((lid, season, pt, [round(m, 3) for m in masses[:3]]))
            print(f"  {tag}  division:{st:11}  {ndiv} divisions  bracket recomputed  "
                  f"mass==slots:{'ok' if ok else 'BAD'}")
        except Exception as exc:   # noqa: BLE001 — isolate one league; a re-run retries it
            errored.append((lid, season, str(exc)[:160]))
            print(f"      ✗ ERROR (isolated, will retry on re-run): {str(exc)[:160]}")

    report = {
        "targets": len(tgts), "division_status": dict(div_status),
        "activated": activated, "bracket_recomputed": recomputed,
        "mass_bad": mass_bad, "errored": errored,
        "elapsed_s": round(time.time() - t0, 1),
        "timing": {k: round(v, 1) for k, v in timing.items()},
    }
    _print_report(report)
    return report


def _print_report(rep: dict) -> None:
    print("\n=== division backfill report (generalization stratum) ===")
    print(f"  targets={rep['targets']}  division={rep['division_status']}  "
          f"activated={len(rep['activated'])}  bracket recomputed={rep['bracket_recomputed']}")
    print(f"  wall-clock={rep['elapsed_s']}s  timing={rep['timing']}")
    for lid, season, ndiv in rep["activated"]:
        print(f"    activated: {lid} {season} — {ndiv} divisions")
    if rep["mass_bad"]:
        print(f"  ⚠ MASS != slot count (should be empty): {rep['mass_bad']}")
    if rep["errored"]:
        print(f"  errored leagues (isolated; retried on re-run): {len(rep['errored'])}")
        for lid, season, err in rep["errored"]:
            print(f"    {lid} {season}: {err}")


def main():
    ap = argparse.ArgumentParser(description="Activate division-aware seeding on the gen division leagues (3d C2).")
    ap.add_argument("--limit", type=int, default=None, help="first N targets (deterministic order)")
    ap.add_argument("--dry-run", action="store_true", help="fetch + activate _division_map, skip bracket recompute")
    ap.add_argument("--throttle", type=float, default=0.1, help="min gap between Sleeper calls (s)")
    a = ap.parse_args()
    run(limit=a.limit, dry_run=a.dry_run, throttle=a.throttle)


if __name__ == "__main__":
    main()
    sys.exit(0)
