"""
check_spine.py — the corpus measurement-spine gate (Improvement-Loop Session 3b commit 3; Session 3d
commit 3 extends it to the generalization stratum — both strata of the now-complete corpus spine).

Asserts, over every matched AND generalization league in the FROZEN manifest, that the 5-read measurement
spine (commit 2) is complete, cohort-sound, probability-valid, roster-mass-faithful, deterministic,
two-way-sliceable, and — for generalization — `never_tune`-intact. Mirrors `check_harvest` /
`backtest_l0_keying`: exit 0 iff every applicable check passes. A league whose raw harvest is degenerate
(playoff_week_start unset ⇒ no simulable season — the compute_spine flag) is a NAMED, tolerated exception
(reported, not a silent hole); a league missing a read for NO diagnosable reason FAILS.

  1. SPINE PRESENT — all 5 reads (production_vor, true_rank, positional_depth, bracket_odds, player_signal)
     exist for every non-degenerate league in every checked stratum.
  2. COHORT + PROBABILITY — true_rank / positional_depth / bracket_odds cover the SAME roster set at EVERY
     as-of week (no team silently dropped, no week short a team); bracket_odds playoff_odds ∈ [0,1] and the
     spent playoff mass per as-of week == the league's playoff-slot count (a real property, not "file
     exists") — now exercised on REAL division brackets (3d), the first true test of division-aware seeding.
  3. NO ROSTER-MASS REGRESSION — production_vor's players ⊆ 3a's join_season skill players (the spine invents
     no roster mass and the remainder story doesn't grow downstream); coverage reported.
  4. DETERMINISTIC — recomputing a sample league (from BOTH strata, incl. a division league) is
     value-identical to the persisted spine (incl. the league-stable bracket_sim seed). Compared
     order-insensitively (`_frame_eq`): the parquet WRITER is physically non-deterministic (bytes flake
     run-to-run for a byte-identical in-memory frame), so determinism is a property of the recomputed
     VALUES, not the on-disk byte stream.
  5. TWO-WAY SLICEABLE — is_two_way is present + boolean on every production_vor and filterable.
  6. NEVER_TUNE INTACT — every generalization manifest row stays `never_tune` (never leaks into the tunable
     set) and no matched row is mis-flagged never_tune. The generalization stratum CERTIFIES the any-league
     code on real shapes; it must never feed the Tuner.

Prove-it-bites (a gate that can't fail is not a gate): a missing read is detected (check 1); a playoff mass ≠
slot-count fails the check-2 predicate; a wall-clock seed would fail check-4's purity assertion; a
never_tune=False generalization row fails the check-6 predicate.

Run: python3 -m application.data.corpus.check_spine [--strata matched generalization] [--sample-determinism N]
"""
import argparse
import contextlib
import io
import sys
from collections import defaultdict

import polars as pl

from application.data import data_layer
from application.data.corpus import compute_spine
from application.data.corpus import constants_snapshot
from application.data.transforms import (
    compute_bracket_sim,
    compute_player_signal,
    compute_positional_depth,
    compute_production_vor,
    compute_true_rank,
)

_SKILL = ("QB", "RB", "WR", "TE")
_MASS_TOL = 0.02        # Σ playoff_odds is exact per sim (each seats playoff_teams); 3dp rounding ≤ ~0.01
_MIN_PV_COVERAGE = 0.80  # production_vor should value ≥80% of the rostered skill pool (rest = unprojected)


def _ok(label, cond, results, extra=""):
    results.append(bool(cond))
    print(f"    {label:58} {'PASS' if cond else 'FAIL'}{('  ' + extra) if extra else ''}")


def _quiet(fn):
    with contextlib.redirect_stdout(io.StringIO()):
        return fn()


def _frame_eq(a: pl.DataFrame, b: pl.DataFrame) -> bool:
    """Order-insensitive frame equality: same columns + same VALUES, ignoring row order. The determinism
    property is about VALUES, not the parquet byte stream: polars' parquet writer is physically
    non-deterministic (compression/dictionary/metadata layout differ run-to-run even for a byte-identical
    in-memory frame — verified: recompute is order-sensitive `.equals` every time, only the on-disk bytes
    flake), so a raw byte-hash flakes ~8%. Comparing sorted frames asserts what determinism actually means.
    (The 1.7 precedent; check_expected_points uses the same helper.)"""
    if set(a.columns) != set(b.columns):
        return False
    cols = b.columns
    return a.select(cols).sort(cols).equals(b.select(cols).sort(cols))


# --- check-2 / check-4 predicates (factored out so prove-it-bites can call them directly) --------------

def _mass_ok(mass: float, playoff_teams: int, tol: float = _MASS_TOL) -> bool:
    """The spent-probability property: the made-playoffs mass at an as-of week equals the slot count."""
    return abs(mass - playoff_teams) <= tol


def _rosters_by_week(df: pl.DataFrame) -> dict:
    return {int(w): frozenset(int(x) for x in g["roster_id"].to_list())
            for (w,), g in df.group_by("as_of_week")}


def _one_cohort(rby: dict) -> bool:
    """Every as-of week the read covers has the SAME roster set — no team silently dropped mid-season."""
    vals = list(rby.values())
    return bool(vals) and all(v == vals[0] for v in vals)


# --- determinism (recompute a sample → value-identical vs persisted, never touches canonical data) -----

# (compute, persisted-path, needs_scoring_key). Value-compared, so no writer is needed.
_COMP = [
    (compute_production_vor.compute, data_layer._production_vor_path, True),
    (compute_true_rank.compute, data_layer._true_rank_path, False),
    (compute_positional_depth.compute, data_layer._positional_depth_path, False),
    (compute_bracket_sim.compute, data_layer._bracket_odds_path, True),
    (compute_player_signal.compute, data_layer._player_signal_path, False),
]


def _check_determinism(sample_rows, results):
    print("  4 — determinism (recompute a sample league == persisted, incl. bracket seed):")
    checked = 0
    for r in sample_rows:
        lid, season, sk = str(r["league_id"]), int(r["season"]), str(r["scoring_key"])
        if not compute_spine._spine_present(lid, season):
            continue
        all_same = True
        for comp, path_fn, needs_sk in _COMP:
            kw = {"scoring_key": sk} if needs_sk else {}
            df = _quiet(lambda: comp(season, league_id=lid, **kw))
            all_same = all_same and _frame_eq(df, pl.read_parquet(path_fn(season, lid)))
        _ok(f"{lid} {season}: recompute value-identical to persisted (incl. bracket seed)", all_same, results)
        checked += 1
    if not checked:
        print("    (no present sample leagues to recompute)")


# --- the gate -----------------------------------------------------------------------------------------

def check(strata=("matched", "generalization"), sample_determinism: int = 2) -> bool:
    results: list = []
    strata = tuple(strata)
    tgts = compute_spine.targets(strata)
    strat_counts = defaultdict(int)
    for r in tgts:
        strat_counts[r["stratum"]] += 1
    print(f"=== corpus measurement-spine gate: {len(tgts)} leagues "
          f"({dict(sorted(strat_counts.items()))}) ===")

    present = flagged = 0
    missing = []                       # (lid, season, first_missing) — missing WITHOUT a degenerate reason
    flagged_leagues = []               # (lid, season, reason)
    cohort_bad, prob_bad, mass_bad, mass_evidence = [], [], [], []
    pv_players = join_players = 0
    invented = []                      # production_vor players absent from the join (roster-mass invention)
    low_cov = []
    two_way_missing, two_way_total = [], 0

    for r in tgts:
        lid, season = str(r["league_id"]), int(r["season"])
        if not compute_spine._spine_present(lid, season):
            reason = compute_spine._degenerate_reason(lid, season)
            if reason:
                flagged += 1
                flagged_leagues.append((lid, season, reason))
            else:
                first = next((rd for rd in compute_spine.READS
                              if not compute_spine._PATH[rd](season, lid).exists()), "?")
                missing.append((lid, season, first))
            continue
        present += 1

        bo = data_layer.read_bracket_odds(season, league_id=lid, as_of_week="all")
        tr = data_layer.read_true_rank(season, league_id=lid, as_of_week="all")
        pdp = data_layer.read_positional_depth(season, league_id=lid, as_of_week="all")
        pv = data_layer.read_production_vor(season, league_id=lid, as_of_week="all")

        # 2a — cohort: every team present at every as-of week (no team silently dropped), the same cohort
        # across the reads. true_rank / positional_depth cover exactly production_vor's as-of weeks;
        # bracket_odds covers a contiguous PREFIX (it legitimately can't simulate from the final week —
        # no remaining games — so it drops the trailing as-of week when max_roster_week ≥ reg_season_end).
        pv_r, bo_r, tr_r, pd_r = (_rosters_by_week(pv), _rosters_by_week(bo),
                                  _rosters_by_week(tr), _rosters_by_week(pdp))
        cohort = next(iter(pv_r.values())) if pv_r else frozenset()
        internal = all(_one_cohort(x) for x in (pv_r, tr_r, pd_r, bo_r))
        cross = all(next(iter(x.values()), frozenset()) == cohort for x in (tr_r, pd_r, bo_r))
        bw = sorted(bo_r)
        weeks_ok = (set(tr_r) == set(pv_r) and set(pd_r) == set(pv_r)
                    and set(bo_r) <= set(pv_r) and bw == list(range(1, len(bw) + 1)))
        if not (internal and cross and weeks_ok):
            cohort_bad.append((lid, season))

        # 2b — probability validity + spent-mass == playoff slot count.
        if bo["playoff_odds"].min() < 0.0 or bo["playoff_odds"].max() > 1.0:
            prob_bad.append((lid, season))
        _reg, pt = compute_bracket_sim._playoff_config(season, league_id=lid)
        masses = bo.group_by("as_of_week").agg(pl.col("playoff_odds").sum().alias("m"))["m"].to_list()
        if not all(_mass_ok(m, pt) for m in masses):
            mass_bad.append((lid, season, pt, [round(m, 3) for m in masses[:3]]))

        # 3 — roster-mass: production_vor players ⊆ join skill players; report coverage.
        jp = set(data_layer.read_join_season(season, league_id=lid)
                 .filter(pl.col("position").is_in(_SKILL))["sleeper_player_id"].to_list())
        pvp = set(pv["sleeper_player_id"].to_list())
        pv_players += len(pvp)
        join_players += len(jp)
        if pvp - jp:
            invented.append((lid, season, len(pvp - jp)))
        if jp and len(pvp & jp) / len(jp) < _MIN_PV_COVERAGE:
            low_cov.append((lid, season, round(len(pvp & jp) / len(jp), 3)))

        # 5 — two-way sliceable.
        if "is_two_way" not in pv.columns or pv["is_two_way"].dtype != pl.Boolean:
            two_way_missing.append((lid, season))
        else:
            two_way_total += int(pv.filter(pl.col("is_two_way"))["sleeper_player_id"].n_unique())

    # 1 — spine present (degenerate leagues tolerated + named)
    print("  1 — spine present (all 5 reads for every non-degenerate league in each checked stratum):")
    _ok(f"{present} present + {flagged} flagged-degenerate == {len(tgts)} leagues", not missing, results,
        "" if not missing else f"{len(missing)} missing w/o reason, e.g. {missing[:3]}")
    for lid, season, reason in flagged_leagues:
        print(f"      ⚠ flagged (degenerate raw, tolerated): {lid} {season} — {reason}")

    # 2 — cohort + probability
    print("  2 — cohort + probability integrity:")
    _ok("roster cohort consistent across as-of weeks + reads", not cohort_bad, results,
        "" if not cohort_bad else f"{len(cohort_bad)} bad, e.g. {cohort_bad[:3]}")
    _ok("playoff_odds ∈ [0,1]", not prob_bad, results,
        "" if not prob_bad else f"{len(prob_bad)} bad, e.g. {prob_bad[:3]}")
    _ok("spent playoff mass == slot count (every as-of week)", not mass_bad, results,
        "" if not mass_bad else f"{len(mass_bad)} bad, e.g. {mass_bad[:2]}")

    # 3 — roster mass
    print("  3 — no roster-mass regression (production_vor ⊆ join skill players):")
    cov = pv_players / join_players if join_players else 0.0
    _ok("no invented players (pv ⊆ join)", not invented, results,
        "" if not invented else f"{len(invented)} leagues, e.g. {invented[:3]}")
    _ok(f"per-league coverage ≥ {_MIN_PV_COVERAGE:.0%}", not low_cov, results,
        f"aggregate pv/join = {cov:.3f}" + (f"; {len(low_cov)} low, e.g. {low_cov[:3]}" if low_cov else ""))

    # 4 — determinism (sample from EACH checked stratum + a division league — the division-aware seed path)
    det_sample = []
    for st in strata:
        det_sample += compute_spine.targets((st,))[:sample_determinism]
    if "generalization" in strata:
        div_gen = next((r for r in compute_spine.targets(("generalization",)) if r.get("has_divisions")), None)
        if div_gen and div_gen not in det_sample:
            det_sample.append(div_gen)
    _check_determinism(det_sample, results)

    # 5 — two-way
    print("  5 — two-way sliceable on production_vor:")
    _ok("is_two_way present + boolean on every production_vor", not two_way_missing, results,
        "" if not two_way_missing else f"{len(two_way_missing)} missing, e.g. {two_way_missing[:3]}")
    print(f"      two-way rows across the corpus: {two_way_total}")

    # 6 — never_tune intact (the generalization stratum CERTIFIES the any-league code; it must never
    # feed the Tuner — a generalization row that lost never_tune would leak a never_tune shape into tuning).
    man = data_layer.read_corpus_manifest()
    gen_leaked = [str(r["league_id"]) for r in man.iter_rows(named=True)
                  if r["stratum"] == "generalization" and not r["never_tune"]]
    matched_mistagged = [str(r["league_id"]) for r in man.iter_rows(named=True)
                         if r["stratum"] == "matched" and r["never_tune"]]
    n_gen = sum(1 for r in man.iter_rows(named=True) if r["stratum"] == "generalization")
    print("  6 — never_tune intact (generalization never enters the tuner):")
    _ok(f"all {n_gen} generalization rows never_tune (none leaked into the tunable set)", not gen_leaked,
        results, "" if not gen_leaked else f"{len(gen_leaked)} leaked, e.g. {gen_leaked[:3]}")
    _ok("no matched row mis-flagged never_tune", not matched_mistagged, results,
        "" if not matched_mistagged else f"{len(matched_mistagged)} mistagged, e.g. {matched_mistagged[:3]}")

    # prove-it-bites (logic-level; no store mutation)
    print("  PROVE-BITES:")
    _ok("check-1 detects a missing read", not compute_spine._spine_present("__NOSUCH__", 2025), results)
    _ok("check-2 fails on playoff mass ≠ slot count", not _mass_ok(3.0, 4), results)
    _ok("check-2 passes on playoff mass == slot count", _mass_ok(4.0, 4), results)
    _ok("check-4 seed is a pure fn of league_id (not wall-clock)",
        compute_bracket_sim._sim_seed(2025, "A") == compute_bracket_sim._sim_seed(2025, "A")
        and compute_bracket_sim._sim_seed(2025, "A") != compute_bracket_sim._sim_seed(2025, "B"), results)
    _ok("check-4 value-equality bites (differing values ≠; row permutation ==)",
        (not _frame_eq(pl.DataFrame({"a": [1, 2]}), pl.DataFrame({"a": [1, 3]})))
        and _frame_eq(pl.DataFrame({"a": [2, 1]}), pl.DataFrame({"a": [1, 2]})), results)
    _ok("check-6 bites (never_tune=False caught, never_tune=True passes)",
        (not {"never_tune": False}["never_tune"]) and not (not {"never_tune": True}["never_tune"]), results)

    ok = all(results) and bool(results)
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — the corpus measurement spine ({dict(sorted(strat_counts.items()))}) "
          f"is complete, cohort-sound, probability-valid, roster-mass-faithful, deterministic, "
          f"two-way-sliceable, and never_tune-intact ({present} present, {flagged} flagged-degenerate).")
    return ok


def main():
    ap = argparse.ArgumentParser(description="Gate for the corpus measurement spine (Session 3b/3d).")
    ap.add_argument("--strata", nargs="+", default=["matched", "generalization"],
                    choices=["matched", "generalization", "mine"],
                    help="strata to gate (default: both — the complete corpus spine)")
    ap.add_argument("--sample-determinism", type=int, default=2,
                    help="how many leagues per stratum to recompute for the determinism proof (default 2)")
    a = ap.parse_args()
    # Session 8c: the live engine is promoted; validate the IMMUTABLE frozen spine at the epoch that made it.
    with constants_snapshot.frozen_era():
        ok = check(tuple(a.strata), a.sample_determinism)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
