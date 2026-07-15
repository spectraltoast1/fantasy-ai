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
from application.data.transforms import compute_market_vor as mv
from application.data.transforms import compute_bracket_sim as bracket

_STD_SLOTS = [
    {"slot": "QB", "count": 1, "eligible": "QB"}, {"slot": "RB", "count": 2, "eligible": "RB"},
    {"slot": "WR", "count": 2, "eligible": "WR"}, {"slot": "TE", "count": 1, "eligible": "TE"},
    {"slot": "FLEX", "count": 2, "eligible": "RB,WR,TE"},
]
_SF_SLOTS = _STD_SLOTS + [{"slot": "SUPER_FLEX", "count": 1, "eligible": "QB,RB,WR,TE"}]


def _check(label, ok, results, extra=""):
    results.append(ok)
    print(f"    {label:56} {'PASS' if ok else 'FAIL'}{('  ' + extra) if extra else ''}")


def _named_entity_diff(name, fresh, on_disk, keys) -> None:
    """Print the FULL changed row-set between a fresh compute and the on-disk parquet — rows on one side
    only, plus value-changed rows — each tagged with its player/roster id. The bounded-movement instrument
    the frame-eq bool lacks: it lets "moves only the named two-way players" be proven, not asserted. Floats
    are rounded before comparison; value diffs use a null-safe per-column filter (never a join on float
    columns, whose NaN/-0.0 semantics manufacture phantom diffs)."""
    on_disk = on_disk.select(fresh.columns)
    fc = [c for c in fresh.columns if fresh[c].dtype in (pl.Float64, pl.Float32)]
    fr = fresh.with_columns([pl.col(c).round(6) for c in fc])
    od = on_disk.with_columns([pl.col(c).round(6) for c in fc])
    only_fresh = fr.join(od.select(keys), on=keys, how="anti")
    only_disk = od.join(fr.select(keys), on=keys, how="anti")
    common = fr.join(od, on=keys, how="inner", suffix="_od")
    valcols = [c for c in fresh.columns if c not in keys]
    expr = None
    for c in valcols:
        e = pl.col(c).ne_missing(pl.col(f"{c}_od"))
        expr = e if expr is None else (expr | e)
    val_changed = common.filter(expr) if expr is not None else common.head(0)
    idcol = "sleeper_player_id" if "sleeper_player_id" in fresh.columns else keys[-1]

    def ids(df):
        return sorted({str(x) for x in df[idcol].to_list()}) if df.height else []

    total = only_fresh.height + only_disk.height + val_changed.height
    print(f"  {name:16} fresh={fresh.height:5} disk={on_disk.height:5}  fresh_only={only_fresh.height} "
          f"disk_only={only_disk.height} val_changed={val_changed.height}  [{'CLEAN' if total == 0 else str(total) + ' changed'}]")
    if only_fresh.height:
        print(f"       fresh_only {idcol}: {ids(only_fresh)}")
    if only_disk.height:
        print(f"       disk_only  {idcol}: {ids(only_disk)}")
    if val_changed.height:
        print(f"       val_changed {idcol}: {ids(val_changed)}")


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

    reg = data_layer.read_pinned_sleeper_players().select(
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
                         + ("registry⇄nfl_stats POSITION CONFLICT (two-way player): nflreadpy labels him "
                            "non-skill, so the join skill-filter drops him before the remainder step. "
                            "Session 1.7 makes the PINNED registry authoritative for eligibility, so he is "
                            "reclassified to his fantasy slot and kept — deterministically. If still absent, "
                            "the pinned snapshot lacks him or predates his skill classification"
                            if two_way else "roster resolution changed"))
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
        print(f"  MECHANISM: registry⇄nfl_stats position conflict for {drift_suspects} two-way player(s). "
              "Skill-eligibility is a FANTASY question (Sleeper registry), but nflreadpy (a stats source) was "
              "answering it — a two-way player is labelled non-skill by his defensive line and dropped by the "
              "join skill-filter, so his membership drifted with the mutable registry across rebuilds.")
        print("  RESOLUTION (Session 1.7): the PINNED registry snapshot is authoritative for rostered "
              "skill-eligibility (join_nfl_sleeper_weekly + audit_join + market_vor read it), so this is "
              "deterministic. A non-empty divergence here AFTER the rebuild means the pin is stale or lacks "
              "the player — investigate, do not regenerate to taste.")
    else:
        print("  No divergence — on-disk reproduces a fresh compute (deterministic).")

    # --- Extend the bounded audit to the other roster-strength reads (Session 1.7): name every changed
    #     row so 'moves only the named two-way players' is proven, not asserted.
    print("\n=== downstream frame diff (fresh compute vs on-disk) ===")
    _named_entity_diff("true_rank", tr.compute(season),
                       data_layer.read_true_rank(season, as_of_week="all"), ["as_of_week", "roster_id"])
    _named_entity_diff("positional_depth", depth.compute(season),
                       data_layer.read_positional_depth(season, as_of_week="all"),
                       ["as_of_week", "roster_id", "position"])
    try:
        od_mv = pl.read_parquet(data_layer._market_vor_path(season, data_layer._active_league(season)[0]))
        _named_entity_diff("market_vor", mv.compute(season), od_mv,
                           ["snapshot_date", "roster_id", "sleeper_player_id"])
    except Exception as e:  # market_vor is optional (POC entity) — report, don't crash the diagnostic
        print(f"  market_vor: skipped ({type(e).__name__}: {str(e)[:80]})")
    try:
        od_bo = data_layer.read_bracket_odds(season, as_of_week="all")
        _named_entity_diff("bracket_odds", bracket.compute(season), od_bo, ["as_of_week", "roster_id"])
    except Exception as e:
        print(f"  bracket_odds: skipped ({type(e).__name__}: {str(e)[:80]})")


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

    # --- C: determinism (Session 1.7) — the substrate reads reproduce on a re-run. With the registry
    #     pinned, a fresh compute cannot drift; two computes must carry identical VALUES. Compared
    #     order-INSENSITIVELY (sort by all columns first): polars' multi-threaded group_by can legitimately
    #     reorder tied rows within a run, and every consumer sorts, so row order is not a determinism
    #     property — the values are. (The pipeline-level twice-run in the session rebuild sorts the same
    #     way.) ---
    print("  C — determinism (compute twice == identical values, order-insensitive):")
    for cname, cfn in (("production_vor", vor.compute), ("true_rank", tr.compute),
                       ("positional_depth", depth.compute), ("market_vor", mv.compute)):
        try:
            a, b = cfn(season), cfn(season)
            _check(f"{cname} compute×2 identical", a.sort(a.columns).equals(b.sort(b.columns)), results)
        except Exception as e:
            _check(f"{cname} compute×2 identical", False, results, f"{type(e).__name__}: {str(e)[:60]}")

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
