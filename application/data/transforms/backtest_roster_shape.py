"""
Gate for the roster-shape generalization (the "any-league" project, piece 3).

Production VOR (§4) and lineup-leakage used to hard-code the swap/replacement structure as "QB vs
FLEX(RB/WR/TE)" — a latent that silently mis-handles superflex/2QB. Both now derive it from the league's
declared `lineup_slots` via the shared `_analytics.position_pools`. Like piece 1, the real 2025 league is
standard 1QB with no answer key for the non-standard path, so this is a **generalization** gate — two
parts, exit 0 iff both pass:

  A — **No-regression.** Recompute `production_vor`, `team_leakage`, and their re-aggregators `true_rank`
      / `positional_depth` for the real (standard) league and assert **frame-equal** to the on-disk
      parquets. The generalized derivation must reproduce the old QB/'FLEX' partition *and labels*
      exactly — the working league is untouched.
  B — **Synthetic superflex correctness.** With a synthetic `SUPER_FLEX` lineup shape: `position_pools`
      pools QB with RB/WR/TE; VOR's `_pool_of` measures QB against the flex waiver line (one pool, not
      two); and lineup-leakage treats a benched QB as a legal swap for a started RB (a cross-position
      coachable fix labelled `SUPER_FLEX`) — impossible under the old hard-code.
"""

import argparse
import sys
from pathlib import Path

import polars as pl

from application.data import data_layer
from application.data.transforms._analytics import position_pools
from application.data.transforms import compute_production_vor as vor
from application.data.transforms import compute_team_leakage as leak
from application.data.transforms import compute_true_rank as tr
from application.data.transforms import compute_positional_depth as depth

_STD_SLOTS = [
    {"slot": "QB", "count": 1, "eligible": "QB"}, {"slot": "RB", "count": 2, "eligible": "RB"},
    {"slot": "WR", "count": 2, "eligible": "WR"}, {"slot": "TE", "count": 1, "eligible": "TE"},
    {"slot": "FLEX", "count": 2, "eligible": "RB,WR,TE"},
]
_SF_SLOTS = _STD_SLOTS + [{"slot": "SUPER_FLEX", "count": 1, "eligible": "QB,RB,WR,TE"}]


def _check(label, ok, results, extra=""):
    results.append(ok)
    print(f"    {label:56} {'PASS' if ok else 'FAIL'}{('  ' + extra) if extra else ''}")


def run(season: int) -> bool:
    results: list = []

    # --- A: no-regression on the real standard league (all four consumers) ---
    print(f"=== Roster-shape gate: season={season} ===")
    print("  A — no-regression (generalized derivation == on-disk on the standard league):")

    def frame_eq(name, recomputed, on_disk, sort):
        a = recomputed.sort(sort)
        b = on_disk.select(a.columns).sort(sort)
        _check(f"{name} frame-equal (rows {a.height})", a.equals(b), results)

    frame_eq("production_vor", vor.compute(season), data_layer.read_production_vor(season, as_of_week="all"),
             ["as_of_week", "roster_id", "sleeper_player_id"])
    frame_eq("team_leakage", leak.compute(season), data_layer.read_team_leakage(season, as_of_week="all"),
             ["as_of_week", "roster_id"])
    frame_eq("true_rank", tr.compute(season), data_layer.read_true_rank(season, as_of_week="all"),
             ["as_of_week", "roster_id"])
    frame_eq("positional_depth", depth.compute(season), data_layer.read_positional_depth(season, as_of_week="all"),
             ["as_of_week", "roster_id", "position"])

    # --- B: synthetic superflex correctness ---
    print("  B — synthetic superflex correctness:")
    std_pools = position_pools(_STD_SLOTS)
    sf_pools = position_pools(_SF_SLOTS)
    _check("standard pools = {QB:'QB', RB/WR/TE:'FLEX'}",
           std_pools == {"QB": "QB", "RB": "FLEX", "WR": "FLEX", "TE": "FLEX"}, results, str(std_pools))
    _check("superflex pools QB with RB/WR/TE",
           len(set(sf_pools.values())) == 1 and sf_pools["QB"] == "SUPER_FLEX", results, str(sf_pools))

    # VOR: QB shares a replacement pool with the flex under superflex (one pool), two under standard.
    vor_std = vor._pool_of(pl.DataFrame(_STD_SLOTS))
    vor_sf = vor._pool_of(pl.DataFrame(_SF_SLOTS))
    _check("VOR _pool_of: standard 2 pools, superflex 1 (QB pooled with flex)",
           len(set(vor_std.values())) == 2 and vor_sf["QB"] == vor_sf["RB"], results)

    # Leakage: a benched QB legally swaps for a started RB under superflex → a cross-position coachable
    # fix labelled SUPER_FLEX. One week: started a weak RB, benched a strong QB (both habitual in role).
    sf_slots = leak._expand_slots(_SF_SLOTS)  # 9 starting slots (QB,RB×2,WR×2,TE,FLEX×2,SUPER_FLEX)
    pool_by_week = {1: [
        # A FULL 9-man started lineup (weak RB started) + a benched QB that outscores it, so the
        # optimal lineup *displaces* the started RB with the benched QB in the SUPER_FLEX slot.
        {"name": "BenchQB", "position": "QB", "pts": 30.0, "started": False},
        {"name": "StartRB", "position": "RB", "pts": 3.0, "started": True},
        {"name": "QB0", "position": "QB", "pts": 20.0, "started": True},
        {"name": "RB1", "position": "RB", "pts": 12.0, "started": True},
        {"name": "WR1", "position": "WR", "pts": 11.0, "started": True},
        {"name": "WR2", "position": "WR", "pts": 10.0, "started": True},
        {"name": "TE1", "position": "TE", "pts": 9.0, "started": True},
        {"name": "FL1", "position": "WR", "pts": 8.0, "started": True},
        {"name": "FL2", "position": "RB", "pts": 7.0, "started": True},
        {"name": "FL3", "position": "RB", "pts": 6.0, "started": True},
    ]}
    season_by_name = {  # BenchQB habitually benched but higher rate than the habitual-starter StartRB
        "BenchQB": {"rate": 25.0, "startShare": 0.0, "lowSample": False, "current": True},
        "StartRB": {"rate": 4.0, "startShare": 1.0, "lowSample": False, "current": True},
    }
    lk = leak._team_leakage([1], pool_by_week, sf_slots, season_by_name, sf_pools,
                            rate_margin=leak.COACHABLE_RATE_MARGIN,
                            habitual_starter_threshold=leak.HABITUAL_STARTER_THRESHOLD)
    fix_positions = [f["position"] for f in lk["fixes"]]
    _check("leakage: benched QB → started RB is a legal SUPER_FLEX swap",
           lk["points_left"] > 0 and "SUPER_FLEX" in fix_positions, results,
           f"points_left={lk['points_left']}, fix_positions={fix_positions}")

    ok = all(results)
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — roster-shape derivation reproduces the standard "
          f"league byte-for-byte and correctly generalizes to superflex.")
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gate for the roster-shape (superflex) generalization.")
    parser.add_argument("--season", type=int, default=2025)
    args = parser.parse_args()
    sys.exit(0 if run(args.season) else 1)
