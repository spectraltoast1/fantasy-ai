"""
Gate for the roster-shape generalization (the "any-league" project, piece 3).

Production VOR (§4) used to hard-code the swap/replacement structure as "QB vs
FLEX(RB/WR/TE)" — a latent that silently mis-handles superflex/2QB. It now derives it from the league's
declared `lineup_slots` via the shared `_analytics.position_pools`. Like piece 1, the real 2025 league is
standard 1QB with no answer key for the non-standard path, so this is a **generalization** gate — two
parts, exit 0 iff both pass:

  A — **No-regression.** Recompute `production_vor` and its re-aggregators `true_rank`
      / `positional_depth` for the real (standard) league and assert **frame-equal** to the on-disk
      parquets. The generalized derivation must reproduce the old QB/'FLEX' partition *and labels*
      exactly — the working league is untouched.
  B — **Synthetic superflex correctness.** With a synthetic `SUPER_FLEX` lineup shape: `position_pools`
      pools QB with RB/WR/TE; and VOR's `_pool_of` measures QB against the flex waiver line (one pool, not
      two) — impossible under the old hard-code.
"""

import argparse
import sys
from pathlib import Path

import polars as pl

from application.data import data_layer
from application.data.transforms._analytics import position_pools
from application.data.transforms import compute_production_vor as vor
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


def diagnose(season: int) -> None:
    """Read-only: NAME the rows where on-disk production_vor and a fresh compute() disagree, then walk
    every drop-point on the fresh inputs to attribute the mechanism. Writes nothing, asserts nothing —
    the instrument the frame-eq check lacks (`.equals()` only returns a bool and never names a row).

    compute() is deterministic given its inputs, so a frame-eq FAIL means an INPUT moved under the
    persisted parquet. A player survives a fresh compute only if he (a) has a projected remaining week in
    projection_consensus, (b) is on a roster as of N in join_season (`_roster_as_of`), and (c) his position
    maps to a pool. This prints which of those each divergent player fails — and flags the registry⇄stats
    position conflict that is the tell for the roster-substrate reproducibility hole (audit S1.1)."""
    key = ["as_of_week", "roster_id", "sleeper_player_id"]
    on_disk = data_layer.read_production_vor(season, as_of_week="all")
    fresh = vor.compute(season)
    only_disk = on_disk.join(fresh.select(key), on=key, how="anti")
    only_fresh = fresh.join(on_disk.select(key), on=key, how="anti")
    print(f"\n=== production_vor frame diff: season={season} ===")
    print(f"  on-disk rows={on_disk.height}  fresh compute rows={fresh.height}  "
          f"(on-disk-not-fresh={only_disk.height}, fresh-not-on-disk={only_fresh.height})")

    reg = data_layer.read_sleeper_players().select(
        "sleeper_player_id", "full_name", "position", "team", "status")
    stats = data_layer.read_nfl_stats(season).select("sleeper_player_id", "week", "position")
    consensus = data_layer.read_projection_consensus(season).select(
        "week", "sleeper_player_id", "position", "center_ppr"
    ).filter(pl.col("position").is_in(vor.SKILL_POSITIONS))
    season_df = data_layer.read_join_season(season).filter(pl.col("position").is_in(vor.SKILL_POSITIONS))
    pool_of = vor._pool_of(data_layer.read_lineup_slots(season))
    max_proj_week = int(consensus["week"].max())

    drift_suspects = 0
    for direction, frame in (("ON-DISK but absent from fresh compute", only_disk),
                             ("in fresh compute but absent on-disk", only_fresh)):
        if not frame.height:
            continue
        print(f"\n  --- {frame.height} row(s): {direction} ---")
        named = frame.join(reg, on="sleeper_player_id", how="left")
        for pid in named.select("sleeper_player_id").unique().to_series().to_list():
            prows = named.filter(pl.col("sleeper_player_id") == pid).sort("as_of_week")
            id0 = prows.row(0, named=True)
            weeks = prows["as_of_week"].to_list()
            n = int(min(weeks))
            remaining = list(range(n + 1, max_proj_week + 1))
            reg_pos = id0["position"] if id0["position"] is not None else "<absent-from-registry>"
            stat_pos = sorted(stats.filter(pl.col("sleeper_player_id") == pid)["position"].unique().to_list())
            has_proj = consensus.filter(
                (pl.col("sleeper_player_id") == pid) & pl.col("week").is_in(remaining)).height > 0
            in_js = season_df.filter(pl.col("sleeper_player_id") == pid).height > 0
            in_roster = pid in vor._roster_as_of(season_df, n)
            pool = pool_of.get(reg_pos)
            # classify the drop-point
            if not has_proj:
                cause = "no projected remaining week (projection_consensus shifted)"
            elif not in_js or not in_roster:
                two_way = bool(stat_pos) and all(p not in vor.SKILL_POSITIONS for p in stat_pos) \
                    and reg_pos in vor.SKILL_POSITIONS
                cause = ("roster-side drop: absent from join_season — "
                         + ("registry⇄nfl_stats POSITION CONFLICT (two-way player; audit_join keeps him only "
                            "when the 24h registry labels him a skill position → REGISTRY-DRIFT reproducibility "
                            "hole)" if two_way else "roster resolution changed"))
                if two_way:
                    drift_suspects += 1
            elif pool is None:
                cause = f"position {reg_pos!r} maps to no pool"
            else:
                cause = "survives all drop-points in isolation — divergence is roster_id reassignment or ordering"
            print(f"    {id0['full_name'] or pid} ({pid})  as_of_weeks={weeks}  disk_roster_id={id0['roster_id']}")
            print(f"        registry pos={reg_pos} team={id0['team']} status={id0['status']}   nfl_stats pos={stat_pos}")
            print(f"        (a) projected remaining week? {has_proj}   (b) in join_season? {in_js} / "
                  f"roster_as_of({n})? {in_roster}   (c) pool({reg_pos})={pool}")
            print(f"        => {cause}")

    print()
    if drift_suspects:
        print(f"  MECHANISM: registry-drift reproducibility hole confirmed for {drift_suspects} player(s). "
              "The roster substrate (join_season) is rebuilt from the 24h Sleeper current-state registry via "
              "audit_join; a two-way player enters/leaves depending on the registry's label at rebuild time, "
              "so production_vor is NOT reproducible across registry refreshes.")
        print("  ACTION (follow-up session — do NOT regenerate here; that bakes in a transient registry "
              "state): pin/version the registry snapshot, or freeze `position` into join_season at write "
              "time so derived reads never depend on the moving cache. The gate stays honestly RED.")
    else:
        print("  MECHANISM: not a registry-drift signature — see the per-player cause lines above.")


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

    ok = all(results)
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — roster-shape derivation reproduces the standard "
          f"league byte-for-byte and correctly generalizes to superflex.")
    return ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Gate for the roster-shape (superflex) generalization.")
    parser.add_argument("--season", type=int, default=2025)
    parser.add_argument("--diagnose", action="store_true",
                        help="read-only: name + attribute the production_vor frame-eq divergence (no gate)")
    args = parser.parse_args()
    if args.diagnose:
        diagnose(args.season)
        sys.exit(0)
    sys.exit(0 if run(args.season) else 1)
