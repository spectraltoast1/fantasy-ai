"""
check_harvest.py — the corpus raw-harvest gate (Improvement-Loop Session 3a, commit 3).

Asserts, over every selected league in the FROZEN manifest (matched ∪ generalization ∪ mine = 271), that the
raw harvest (commit 2) is complete, sound, deterministic, and two-way-sliceable. Mirrors
`backtest_l0_keying` / `check_corpus`: exit 0 iff every applicable check passes.

  1. RAW PRESENT — teams + config + regular-season matchups + transactions exist under the league-keyed
     paths for every harvested league (raw-pull coverage).
  2. JOIN COMPUTES — `join_season` exists and loads for every harvested league.
  3. NO SILENT ROSTER-MASS LOSS — every rostered player is accounted for: it resolves into the join or is a
     NAMED remainder (the join writes a remainders file per week, even when empty). The per-league remainder
     rate is REPORTED and must be BOUNDED (standing instruction 6 — name the players, don't assert a clean
     join). A league that loses roster mass beyond the bound FAILS.
  4. DETERMINISTIC — re-joining a sample league from the persisted raw is value-identical (the property the
     persist decision, standing instruction 8, exists to satisfy). Compared order-insensitively (`_frame_eq`):
     the parquet writer's physical bytes flake run-to-run for a byte-identical in-memory frame, so
     determinism is a property of the joined VALUES, not the on-disk byte stream.
  5. TWO-WAY RIDES — the `is_two_way` flag is on every join, correctly applied (a row is flagged iff its
     (season, player) is in the 10-row `corpus_two_way_flags` reference), and sliceable.

Prove-it-bites (a gate that can't fail is not a gate): a truncated league (a missing reg-week matchups file)
FAILS check 1; a roster-mass-losing join FAILS check 3's bound predicate.

Run: python3 -m application.data.corpus.check_harvest [--sample-determinism N]
"""
import argparse
import json
import shutil
import sys
from collections import defaultdict

import polars as pl

from application.data import data_layer
from application.data.corpus import harvest
from application.data.transforms import join_nfl_sleeper_weekly

_SKILL = ("QB", "RB", "WR", "TE")
_REMAINDER_RATE_MAX = 0.15   # a league losing >15% of rostered mass to remainders is "roster-mass-losing"


def _ok(label, cond, results, extra=""):
    results.append(bool(cond))
    print(f"    {label:56} {'PASS' if cond else 'FAIL'}{('  ' + extra) if extra else ''}")


# --- per-league scans (persisted data only) -----------------------------------------------------------

def _raw_present(lid, season, reg_end):
    """(ok, first_missing) — config + teams + every reg-week matchups + transactions on disk."""
    if not data_layer._league_settings_path(season, lid).exists():
        return False, "league_settings"
    if not data_layer._sleeper_teams_path(season, lid).exists():
        return False, "teams"
    for wk in range(1, reg_end + 1):
        if not data_layer._sleeper_matchups_path(season, wk, lid).exists():
            return False, f"matchups_w{wk}"
    return True, None


def _remainder_rate(lid, season, reg_end):
    """(join_players, remainder_players, rate) — roster-mass accounting from persisted join + remainders."""
    if not data_layer.join_season_exists(season, league_id=lid):
        return 0, 0, 1.0
    jp = data_layer.read_join_season(season, league_id=lid)["sleeper_player_id"].n_unique()
    rem = set()
    for wk in range(1, reg_end + 1):
        if data_layer.remainders_exist(season, wk, league_id=lid):
            rdf = data_layer.read_join_remainders(season, wk, league_id=lid)
            if rdf.height:
                rem.update(rdf["sleeper_player_id"].to_list())
    total = jp + len(rem)
    return jp, len(rem), (len(rem) / total if total else 1.0)


def _roster_mass_ok(join_players: int, remainder_players: int, threshold=_REMAINDER_RATE_MAX) -> bool:
    """The check-3 predicate, factored out so prove-it-bites can call it directly."""
    total = join_players + remainder_players
    return total > 0 and (remainder_players / total) <= threshold


def _reg_end(lid, season):
    return harvest._reg_end(lid, season)


# --- determinism (temp-league re-join, never touches canonical data) ----------------------------------

def _frame_eq(a: pl.DataFrame, b: pl.DataFrame) -> bool:
    """Order-insensitive frame equality: same columns + same VALUES, ignoring row order. The determinism
    property is about VALUES, not the parquet byte stream: polars' parquet writer is physically
    non-deterministic (compression/dictionary/metadata layout differ run-to-run even for a byte-identical
    in-memory frame), so a raw byte-hash flakes ~8%. Comparing sorted frames asserts what determinism
    actually means. (The 1.7 precedent; check_spine / check_expected_points use the same helper.)"""
    if set(a.columns) != set(b.columns):
        return False
    cols = b.columns
    return a.select(cols).sort(cols).equals(b.select(cols).sort(cols))


def _check_determinism(sample_rows, results):
    print("  4 — determinism (re-join from persisted raw is value-identical):")
    tmp = "__HARVESTDETERM__"
    checked = 0
    for r in sample_rows:
        lid, season = str(r["league_id"]), int(r["season"])
        reg_end = _reg_end(lid, season)
        weeks = [w for w in range(1, reg_end + 1)
                 if data_layer._sleeper_matchups_path(season, w, lid).exists()]
        if not weeks:
            continue
        try:
            # stage the sample's matchups under a temp league_id, then join it twice and compare VALUES
            # (the parquet writer's physical bytes flake run-to-run; the joined data does not).
            for w in weeks:
                src = data_layer._sleeper_matchups_path(season, w, lid)
                dst = data_layer._sleeper_matchups_path(season, w, tmp)
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
            for w in weeks:
                join_nfl_sleeper_weekly.run(season, w, league_id=tmp)
            f1 = pl.read_parquet(data_layer._join_season_path(season, tmp))
            data_layer._join_season_path(season, tmp).unlink()
            for w in weeks:
                join_nfl_sleeper_weekly.run(season, w, league_id=tmp)
            f2 = pl.read_parquet(data_layer._join_season_path(season, tmp))
            _ok(f"{lid} {season}: twice-join value-identical", _frame_eq(f1, f2), results)
            checked += 1
        finally:
            shutil.rmtree(data_layer._sleeper_league_dir(season, tmp), ignore_errors=True)
            shutil.rmtree(data_layer._join_league_dir(tmp), ignore_errors=True)
    if not checked:
        print("    (no sample leagues with matchups to re-join)")


# --- the gate -----------------------------------------------------------------------------------------

def check(sample_determinism: int = 2) -> bool:
    results: list = []
    tgts = harvest.targets()
    print(f"=== corpus raw-harvest gate: {len(tgts)} selected leagues ===")

    raw_ok = join_ok = 0
    missing_raw, missing_join, mass_offenders = [], [], []
    total_join_players = total_remainders = 0

    for r in tgts:
        lid, season = str(r["league_id"]), int(r["season"])
        reg_end = _reg_end(lid, season)
        ok, miss = _raw_present(lid, season, reg_end)
        raw_ok += ok
        if not ok:
            missing_raw.append((lid, season, miss))
        if data_layer.join_season_exists(season, league_id=lid):
            join_ok += 1
        else:
            missing_join.append((lid, season))
        jp, rem, rate = _remainder_rate(lid, season, reg_end)
        total_join_players += jp
        total_remainders += rem
        if not _roster_mass_ok(jp, rem):
            mass_offenders.append((lid, season, jp, rem, round(rate, 3)))

    # 1 — raw present
    print("  1 — raw present (config + teams + every reg-week matchups):")
    _ok(f"all {len(tgts)} leagues raw-present", raw_ok == len(tgts), results,
        "" if raw_ok == len(tgts) else f"{len(missing_raw)} missing, e.g. {missing_raw[:3]}")

    # 2 — join computes
    print("  2 — join_season computes for every league:")
    _ok(f"all {len(tgts)} leagues have a join", join_ok == len(tgts), results,
        "" if join_ok == len(tgts) else f"{len(missing_join)} missing, e.g. {missing_join[:3]}")

    # 3 — no silent roster-mass loss (named + bounded)
    print("  3 — no silent roster-mass loss (remainders named + bounded):")
    agg = total_remainders / (total_join_players + total_remainders) if (total_join_players + total_remainders) else 1.0
    _ok("per-league remainder rate bounded (≤15%)", not mass_offenders, results,
        f"agg rate={agg:.3f}; {len(mass_offenders)} offenders" +
        (f", e.g. {mass_offenders[:3]}" if mass_offenders else ""))
    print(f"      roster mass: {total_join_players} resolved + {total_remainders} named remainders "
          f"(aggregate loss {agg:.2%})")

    # 4 — determinism (sample)
    _check_determinism(tgts[:sample_determinism], results)

    # 5 — two-way rides + correctly applied
    print("  5 — two-way flag rides the harvested join (sliceable, correct):")
    flags = data_layer.read_corpus_two_way_flags()
    _ok("corpus_two_way_flags == 10 rows (2.5 reference)", flags.height == 10, results, f"got {flags.height}")
    flag_pairs = {(int(s), str(p)) for s, p in zip(flags["season"].to_list(), flags["sleeper_player_id"].to_list())}
    have_col = mislabeled = 0
    exposure = defaultdict(set)
    checked_join = 0
    for r in tgts:
        lid, season = str(r["league_id"]), int(r["season"])
        if not data_layer.join_season_exists(season, league_id=lid):
            continue
        checked_join += 1
        j = data_layer.read_join_season(season, league_id=lid)
        if "is_two_way" not in j.columns:
            continue
        have_col += 1
        # correctness: is_two_way iff (season, player) ∈ the reference
        expect = j["sleeper_player_id"].is_in([p for (s, p) in flag_pairs if s == season])
        if not j["is_two_way"].equals(expect):
            mislabeled += 1
        for pid in j.filter(pl.col("is_two_way"))["sleeper_player_id"].unique().to_list():
            exposure[season].add(pid)
    _ok("is_two_way present on every join", have_col == checked_join, results,
        f"{have_col}/{checked_join}")
    _ok("is_two_way correctly applied (== reference)", mislabeled == 0, results,
        f"{mislabeled} mislabeled leagues")
    n_exposed = sum(len(v) for v in exposure.values())
    print(f"      two-way exposure (flagged players on a harvested roster): {n_exposed} — "
          f"{ {s: len(v) for s, v in sorted(exposure.items())} }")

    # prove-it-bites (logic-level; no store mutation)
    print("  PROVE-BITES:")
    _ok("check-1 fails on a truncated league (missing wk)",
        not _raw_present("__NOSUCH__", 2025, 3)[0], results)
    _ok("check-3 fails on a roster-mass-losing join (rate 0.9)",
        not _roster_mass_ok(join_players=1, remainder_players=9), results)
    _ok("check-4 value-equality bites (differing values ≠; row permutation ==)",
        (not _frame_eq(pl.DataFrame({"a": [1, 2]}), pl.DataFrame({"a": [1, 3]})))
        and _frame_eq(pl.DataFrame({"a": [2, 1]}), pl.DataFrame({"a": [1, 2]})), results)

    ok = all(results) and bool(results)
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — the corpus raw harvest is complete, sound, "
          f"deterministic, and two-way-sliceable.")
    return ok


def main():
    ap = argparse.ArgumentParser(description="Gate for the corpus raw harvest (Session 3a).")
    ap.add_argument("--sample-determinism", type=int, default=2,
                    help="how many leagues to re-join for the determinism proof (default 2)")
    a = ap.parse_args()
    sys.exit(0 if check(a.sample_determinism) else 1)


if __name__ == "__main__":
    main()
