"""
compute_spine.py — the corpus measurement-spine compute (Improvement-Loop Session 3b, commit 2).

Reads the FROZEN `corpus_manifest` + the FROZEN scoring-scoped substrate (2.5) + 3a's harvested per-league
`join_season`, and computes the **5 measurement reads** for every matched league, league-keyed. It computes;
it does not fetch, re-select, or re-tune (standing instruction 8). The narrative reads (`ros_league_view`,
`manager_features`) are descoped from the corpus — this driver does not touch them.

Per league-season, in dependency order:
  1. production_vor   (scoring_key for the consensus; league_id for the join/slots/write)  → the VOR foundation
  2. true_rank        (reads production_vor)
  3. positional_depth (reads production_vor)
  4. bracket_odds     (scoring_key for the consensus; league_id for roster/matchups/slots; league-stable seed)
  5. player_signal    (league_id for the join; independent of VOR)

Idempotent + resumable per league (the 3a precedent): a league whose 5 reads are all on disk is skipped, so
a long run resumes rather than restarts (incremental re-run ≈ 0). Per-league failure is ISOLATED, not fatal —
a re-run retries it. Determinism is the load-bearing property (this is the ledger's substrate): every new
sort carries a unique tie-break and `bracket_sim` uses a league-stable seed, so re-computing a league is
byte-identical (verified by check_spine).

Budget: `bracket_sim` is SIMS=10_000 Monte-Carlo per league per as-of week — the heavy step by far; the wall
clock is reported per read family + total.

Usage:
    python3 -m application.data.corpus.compute_spine --pilot 3     # small matched sample + budget
    python3 -m application.data.corpus.compute_spine               # the full 221 matched leagues
    python3 -m application.data.corpus.compute_spine --strata matched --limit N
"""
import argparse
import contextlib
import io
import os
import sys
import time
from collections import defaultdict

from application.data import data_layer
from application.data.transforms import (
    compute_bracket_sim,
    compute_player_signal,
    compute_positional_depth,
    compute_production_vor,
    compute_true_rank,
)

# The tuning corpus is the matched stratum (221); the 48 never_tune generalization leagues are Session 3c
# (they hit the synthetic-gated shape paths). `mine`/`generalization` are allowed via --strata for
# validation / 3c, but matched is the default.
SPINE_STRATA = ("matched",)
READS = ("production_vor", "true_rank", "positional_depth", "bracket_odds", "player_signal")


@contextlib.contextmanager
def _quiet():
    """Silence a compute's own per-league summary prints (1105 blocks over 221×5 reads would bury the
    driver's report). The driver prints its own concise per-league line + the budget."""
    with contextlib.redirect_stdout(io.StringIO()):
        yield


# --- targets (mirror harvest.targets: manifest-driven, deterministic order) ----------------------------

def targets(strata=SPINE_STRATA, limit=None) -> list[dict]:
    """The manifest rows to compute, in a deterministic order (season, then league_id). Each row already
    carries `scoring_key` (the frozen classification) — resolved once here, not re-derived per read."""
    man = data_layer.read_corpus_manifest()
    rows = [r for r in man.iter_rows(named=True) if r["stratum"] in strata]
    rows.sort(key=lambda r: (int(r["season"]), str(r["league_id"])))
    return rows[:limit] if limit else rows


def pilot_targets(n: int, strata=SPINE_STRATA) -> list[dict]:
    """A small cross-stratum sample (~n/len(strata) each, deterministic) to validate the plumbing +
    budget before the full run — don't discover a compute bug on league 200 of 221."""
    per = max(1, n // len(strata))
    picked = []
    for st in strata:
        picked.extend(targets((st,))[:per])
    return picked[:n] if n else picked


# --- per-league resumability + compute ----------------------------------------------------------------

_PATH = {
    "production_vor": data_layer._production_vor_path,
    "true_rank": data_layer._true_rank_path,
    "positional_depth": data_layer._positional_depth_path,
    "bracket_odds": data_layer._bracket_odds_path,
    "player_signal": data_layer._player_signal_path,
}


def _spine_present(lid: str, season: int) -> bool:
    """A league's spine is complete when all 5 reads exist under its league-keyed derived paths."""
    return all(_PATH[r](season, lid).exists() for r in READS)


def _degenerate_reason(lid: str, season: int):
    """A NAMED reason (flag, don't drop — the 3a discipline) if the league's raw harvest can't support a
    valid measurement spine, else None. The measurement reads need a real regular season to grade against;
    a league whose `playoff_week_start` is unset (0) resolves reg_season_end<2, and a bracket over no
    schedule would be a clean-zero (standing instruction 1). Cheap pre-flight (reads only the small
    playoff-settings) so a degenerate league is flagged rather than half-computed into a partial spine."""
    try:
        reg_end, _ = compute_bracket_sim._playoff_config(season, league_id=lid)
    except Exception as e:   # noqa: BLE001 — missing/garbled config is itself a degeneracy
        return f"no_playoff_config ({str(e)[:50]})"
    if reg_end < 2:
        return f"reg_season_end={reg_end} (playoff_week_start unset/degenerate → no season to simulate)"
    return None


def _compute_league(lid: str, season: int, scoring_key: str, timing: dict) -> None:
    """Compute + persist the 5 reads for one league-season in dependency order, accumulating per-read
    wall-clock into `timing`. Writes go through the keyed data_layer writers (production_vor → league dir)."""
    def _timed(name, fn):
        t = time.time()
        with _quiet():
            fn()
        timing[name] += time.time() - t

    _timed("production_vor", lambda: compute_production_vor.run(season, league_id=lid, scoring_key=scoring_key))
    _timed("true_rank", lambda: compute_true_rank.run(season, league_id=lid))
    _timed("positional_depth", lambda: compute_positional_depth.run(season, league_id=lid))
    _timed("bracket_odds", lambda: compute_bracket_sim.run(season, league_id=lid, scoring_key=scoring_key))
    _timed("player_signal", lambda: compute_player_signal.run(season, league_id=lid))


# --- driver -------------------------------------------------------------------------------------------

def run(strata=SPINE_STRATA, limit=None, pilot=None) -> dict:
    tgts = pilot_targets(pilot, strata) if pilot else targets(strata, limit)
    t0 = time.time()
    computed = skipped = 0
    flagged_leagues = []          # (league_id, season, reason) — degenerate raw, NOT computed (flag, don't drop)
    errored_leagues = []          # (league_id, season, error) — ISOLATED transient failure, retried on re-run
    timing = defaultdict(float)   # read -> cumulative wall-clock (s)

    for i, r in enumerate(tgts, 1):
        lid, season, scoring_key = str(r["league_id"]), int(r["season"]), str(r["scoring_key"])
        tag = f"[{i}/{len(tgts)}] {r['stratum']:14} {lid} {season} {scoring_key}"
        try:
            if _spine_present(lid, season):
                skipped += 1
                print(f"  {tag}  SKIP (spine present)")
                continue
            reason = _degenerate_reason(lid, season)
            if reason:
                # A prior run may have written a partial spine (the reads before bracket_odds) before the
                # degeneracy surfaced — remove it so the league is cleanly absent, not a half-spine.
                for rd in READS:
                    _PATH[rd](season, lid).unlink(missing_ok=True)
                flagged_leagues.append((lid, season, reason))
                print(f"  {tag}  ⚠ FLAGGED (degenerate raw, not computed): {reason}")
                continue
            print(f"  {tag}  computing…")
            _compute_league(lid, season, scoring_key, timing)
            computed += 1
        except Exception as exc:   # noqa: BLE001 — isolate one league's failure; a re-run retries it
            errored_leagues.append((lid, season, str(exc)[:160]))
            print(f"      ✗ ERROR (isolated, will retry on re-run): {str(exc)[:160]}")

    elapsed = time.time() - t0
    report = {
        "targets": len(tgts), "computed": computed, "skipped": skipped,
        "elapsed_s": round(elapsed, 1),
        "timing": {k: round(timing[k], 1) for k in READS},
        "flagged_leagues": flagged_leagues,
        "errored_leagues": errored_leagues,
    }
    _print_report(report)
    return report


def _print_report(rep: dict) -> None:
    print("\n=== spine compute report ===")
    print(f"  targets={rep['targets']}  computed={rep['computed']}  skipped={rep['skipped']}  "
          f"(incremental re-run ≈ 0 — spine persisted)")
    print(f"  wall-clock={rep['elapsed_s']}s  per read family:")
    for r in READS:
        print(f"    {r:18} {rep['timing'][r]:>8.1f}s")
    fl = rep.get("flagged_leagues", [])
    print(f"  flagged leagues (degenerate raw, NOT computed — flag, don't drop): {len(fl)}")
    for lid, season, reason in fl:
        print(f"    {lid} {season}: {reason}")
    er = rep["errored_leagues"]
    print(f"  errored leagues (isolated; retried on re-run): {len(er)}")
    for lid, season, err in er:
        print(f"    {lid} {season}: {err}")


def main():
    ap = argparse.ArgumentParser(description="Compute the corpus measurement spine (Session 3b).")
    ap.add_argument("--strata", nargs="+", default=list(SPINE_STRATA),
                    choices=["matched", "generalization", "mine"])
    ap.add_argument("--limit", type=int, default=None, help="first N targets (deterministic order)")
    ap.add_argument("--pilot", type=int, default=None, help="compute N leagues across strata + report")
    a = ap.parse_args()
    run(strata=tuple(a.strata), limit=a.limit, pilot=a.pilot)


if __name__ == "__main__":
    main()
    sys.exit(0)
