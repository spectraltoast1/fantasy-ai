"""
Compute ROS Player Band — the scoring-scoped, roster-free half of §2 ROS Outcome Shape.

L0 keying (audit S3.2) split the old `ros_outcome_shape` into two entities. This is the half that
needs **no roster**: the per-player bull / bear rest-of-season band + its preseason-ADP anchor. Because
it is roster-free it is **scoring-scoped** — two leagues on the same scoring profile share one file. The
roster-relative half (spectrum position vs the league pool, situation/security carry-through) lives in
compute_ros_league_view.py; joined on sleeper_player_id the two reconstitute the old frame exactly.

**Bull / bear is the ROS-horizon analog of the §3 weekly spread.** §3 gives each week a borrowed centre
+ a calibrated band; summing the centres over the remaining schedule is exactly Production VOR's
`ros_value`, and summing the per-week *variances* gives the ROS band:

  - ros_center = the borrowed ROS centre = Σ weekly consensus centres over the remaining schedule
    (weeks > N), computed here directly from projection_consensus via the SAME pure aggregator
    Production VOR uses (`compute_production_vor._ros_values`) — so it can't drift from the §4 read
    (design law 3). **Rounded to 1 decimal before the band math** to match the value Production VOR
    persists (its `ros_value` is stored round1), so the band reproduces the old ros_outcome_shape
    frame-for-frame (the L0 no-regression invariant).
  - ros_sigma  = √(Σ band_ppr² over the same remaining weeks) — the §3 shrunk weekly residual std
    combined across weeks under weekly independence (the compute_bracket_sim assumption).
  - ros_bull / ros_bear = ros_center ± BULL_Z·ros_sigma, floored at 0, blended toward the preseason
    ADP anchor (weight decaying with the horizon). BULL_Z / ANCHOR_W are backtest-tuned jointly — see
    backtest_ros_player_band.py.
  - ros_cv = ros_sigma / ros_center — relative dispersion, a fragility proxy.

Preseason anchor, time decay, and the pure band helpers are unchanged from the pre-split module (the §2
math did not change — only the storage scope did). Roster-free means the band is emitted for the WHOLE
projected skill pool, not just rostered players; the league view selects the rostered subset.

Tall over as_of_week 1..freeze (the season-join freeze week Production VOR also stops at, so the
"latest" anchor the AI reads stays the freeze). Output:
snapshots/derived/scoring/<scoring_key>/ros_player_band_{season}.parquet.

Usage:
    python3 -m application.data.transforms.compute_ros_player_band --season 2025
"""

import argparse
import sys

import polars as pl

from application.data import data_layer
from application.data.transforms._analytics import round1
from application.data.transforms.compute_production_vor import _ros_values

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]

# Bull/bear half-width in σ units and the max preseason-anchor weight — backtest-tuned JOINTLY against
# the 2025 answer key (backtest_ros_player_band.py --sweep) to (1.44, 0.25): freeze-week coverage 0.817
# with balanced miss tails (below-bear 0.091 / above-bull 0.091). Unchanged by the L0 split — the storage
# scope moved, the math did not. (See the pre-split module history for the full derivation.)
BULL_Z = 1.44
ANCHOR_W = 0.25


def _ros_sigma(consensus: pl.DataFrame, remaining_weeks) -> pl.DataFrame:
    """Per player: the accumulated ROS band std over the remaining schedule = √(Σ band_ppr²).

    Mirrors compute_production_vor._ros_values but aggregates the §3 weekly band's *variance* (band_ppr²)
    instead of the centre — so ros_sigma sums over exactly the same remaining weeks as ros_value. A null
    weekly band contributes 0. One row per player with any projected remaining week.
    """
    return (
        consensus.filter(pl.col("week").is_in(list(remaining_weeks)))
        .group_by("sleeper_player_id")
        .agg(
            pl.col("band_ppr").fill_null(0.0).pow(2).sum().sqrt().alias("ros_sigma"),
            pl.len().alias("n_weeks_band"),
        )
    )


def _outcome_band(ros_center: float, ros_sigma: float, *, bull_z: float) -> dict:
    """bull/bear rest-of-season range around the borrowed centre: centre ± bull_z·sigma, floored at 0
    (a season's realised production can't be negative). ros_cv = sigma/centre (relative dispersion /
    fragility), None where the centre is non-positive (degenerate deep-bench spot)."""
    bull = max(0.0, ros_center + bull_z * ros_sigma)
    bear = max(0.0, ros_center - bull_z * ros_sigma)
    cv = ros_sigma / ros_center if ros_center > 0 else None
    return {"ros_bull": bull, "ros_bear": bear, "ros_cv": cv}


def _preseason_anchor(adp_row: dict | None, curve_lookup: dict, curve_max_rank: dict,
                      remaining_frac: float) -> dict | None:
    """The player's empirical preseason floor/center/ceiling (§2 anchor), scaled to the remaining
    schedule. `adp_row` is his preseason ADP (position, pos_ecr_rank, ecr, best, worst) or None if he
    wasn't drafted; `curve_lookup` maps (position, rank) → (floor, center, ceiling) full-season PPR from
    compute_adp_points_curve; deep ranks clamp to the position's deepest fitted rank. Returns None (→ no
    anchor, pure-projection fallback) when the player has no draft rank or no curve coverage. Points are
    scaled by `remaining_frac` so a full-season curve value lines up with the remaining-weeks ros_center
    it will blend with."""
    if adp_row is None:
        return None
    pos = adp_row["position"]
    max_rank = curve_max_rank.get(pos)
    if max_rank is None or adp_row["pos_ecr_rank"] is None:
        return None
    rank = min(max(int(adp_row["pos_ecr_rank"]), 1), max_rank)
    fcc = curve_lookup.get((pos, rank))
    if fcc is None:
        return None
    floor, center, ceiling = fcc
    return {
        "anchor_floor": floor * remaining_frac,
        "anchor_center": center * remaining_frac,
        "anchor_ceiling": ceiling * remaining_frac,
        "adp_ecr": adp_row["ecr"],
        "adp_best": adp_row["best"],
        "adp_worst": adp_row["worst"],
    }


def _blended_band(ros_center: float, ros_sigma: float, anchor: dict | None, w: float,
                  *, bull_z: float) -> dict:
    """bull/bear blended toward the preseason anchor: `(1-w)·projection_extreme + w·anchor_extreme`,
    floored at 0. `w` is the horizon-decaying anchor weight (0 → the pure-projection `_outcome_band`,
    the documented fallback for an undrafted / uncovered player). The projection extremes are taken
    *un-floored* so a negative projection bear can still be lifted by a positive preseason floor before
    the final 0-floor. ros_cv stays the projection's sigma/centre (fragility of the borrowed read)."""
    base = _outcome_band(ros_center, ros_sigma, bull_z=bull_z)
    if anchor is None or w <= 0.0:
        return {**base, "anchor_applied": False}
    proj_bull = ros_center + bull_z * ros_sigma
    proj_bear = ros_center - bull_z * ros_sigma
    bull = max(0.0, (1.0 - w) * proj_bull + w * anchor["anchor_ceiling"])
    bear = max(0.0, (1.0 - w) * proj_bear + w * anchor["anchor_floor"])
    return {"ros_bull": bull, "ros_bear": bear, "ros_cv": base["ros_cv"], "anchor_applied": True}


def _load_anchor_inputs(season: int) -> tuple[dict, dict, dict]:
    """(adp_map, curve_lookup, curve_max_rank) for the §2 preseason anchor. Returns empty maps if either
    ADP source is absent (fetchers not run) — every anchor then degrades to the pure-projection band,
    keeping the transform runnable without the ADP pipeline. Both sources are NFL-global (season-keyed)."""
    if not (data_layer.adp_preseason_exists() and data_layer.adp_points_curve_exists()):
        print("  [anchor] adp_preseason / adp_points_curve missing — running pure-projection band.")
        return {}, {}, {}
    adp_map = {
        r["sleeper_player_id"]: r
        for r in data_layer.read_adp_preseason(season).iter_rows(named=True)
    }
    curve = data_layer.read_adp_points_curve()
    curve_lookup = {
        (r["position"], r["pos_ecr_rank"]): (r["floor_ppr"], r["center_ppr"], r["ceiling_ppr"])
        for r in curve.iter_rows(named=True)
    }
    curve_max_rank = {
        r["position"]: int(r["pos_ecr_rank"])
        for r in curve.group_by("position").agg(pl.col("pos_ecr_rank").max()).iter_rows(named=True)
    }
    return adp_map, curve_lookup, curve_max_rank


def _band_as_of(consensus: pl.DataFrame, n: int, max_proj_week: int, season: int, *,
                bull_z: float, anchor_w: float, total_weeks: int,
                adp_map: dict, curve_lookup: dict, curve_max_rank: dict) -> list:
    """ROS player-band rows for one as-of cutoff N over the WHOLE projected pool: the borrowed centre
    (Σ remaining weekly centres, via the shared _ros_values), the accumulated band std, and the bull/bear
    range blended toward the preseason ADP anchor (weight decaying with the remaining horizon). Roster-
    free — no roster_id, no situation carry-through (those are the league view's job)."""
    remaining = range(n + 1, max_proj_week + 1)
    if not remaining:
        return []

    ros = _ros_values(consensus, remaining)   # per-player raw centre + n_weeks + position, whole pool
    sigma_map = {
        r["sleeper_player_id"]: r["ros_sigma"]
        for r in _ros_sigma(consensus, remaining).iter_rows(named=True)
    }

    rows = []
    for r in ros.iter_rows(named=True):
        pid = r["sleeper_player_id"]
        # Round the borrowed centre to 1 decimal BEFORE the band math — matching the value Production VOR
        # persists (round1(ros_value)), so the band reproduces the old ros_outcome_shape frame-for-frame.
        center = round1(r["ros_value"])
        sigma = sigma_map.get(pid, 0.0)
        remaining_frac = r["n_weeks"] / total_weeks if total_weeks else 0.0
        anchor = _preseason_anchor(adp_map.get(pid), curve_lookup, curve_max_rank, remaining_frac)
        w = anchor_w * remaining_frac
        band = _blended_band(center, sigma, anchor, w, bull_z=bull_z)
        rows.append({
            "season": season,
            "as_of_week": n,
            "sleeper_player_id": pid,
            "position": r["position"],
            "ros_center": round1(center),
            "ros_bull": round1(band["ros_bull"]),
            "ros_bear": round1(band["ros_bear"]),
            "ros_sigma": round1(sigma),
            "ros_cv": round(band["ros_cv"], 3) if band["ros_cv"] is not None else None,
            "n_weeks": int(r["n_weeks"]),
            "anchor_applied": band["anchor_applied"],
            "adp_ecr": anchor["adp_ecr"] if anchor else None,
            "adp_best": anchor["adp_best"] if anchor else None,
            "adp_worst": anchor["adp_worst"] if anchor else None,
            "anchor_floor": round1(anchor["anchor_floor"]) if anchor else None,
            "anchor_ceiling": round1(anchor["anchor_ceiling"]) if anchor else None,
        })
    return rows


def compute(season: int) -> pl.DataFrame:
    consensus = data_layer.read_projection_consensus(season).select(
        "week", "sleeper_player_id", "position", "center_ppr", "band_ppr"
    ).filter(pl.col("position").is_in(SKILL_POSITIONS))
    max_proj_week = int(consensus["week"].max())
    # as-of range = 1..freeze, the season-join freeze week Production VOR also stops at (max_roster_week),
    # so the AI's "latest" anchor stays the freeze. join_season is season-keyed (roster-free).
    freeze_week = int(data_layer.read_join_season(season)["week"].max())
    adp_map, curve_lookup, curve_max_rank = _load_anchor_inputs(season)

    all_rows = []
    for n in range(1, freeze_week + 1):
        all_rows.extend(_band_as_of(
            consensus, n, max_proj_week, season, bull_z=BULL_Z, anchor_w=ANCHOR_W,
            total_weeks=max_proj_week, adp_map=adp_map,
            curve_lookup=curve_lookup, curve_max_rank=curve_max_rank,
        ))

    df = pl.DataFrame(all_rows, infer_schema_length=None).sort(
        "as_of_week", "position", "ros_bull", descending=[False, False, True]
    )
    freeze = int(df["as_of_week"].max())
    latest = df.filter(pl.col("as_of_week") == freeze)
    print(f"=== ROS Player Band: season={season}  as_of_week 1..{freeze}  "
          f"(ROS horizon → week {max_proj_week}; BULL_Z={BULL_Z}; ANCHOR_W={ANCHOR_W}; rows={df.height}) ===")
    print(f"  week {freeze} widest ranges (top bull ceilings):")
    print(latest.head(6).select(
        "sleeper_player_id", "position", "ros_bear", "ros_center", "ros_bull", "ros_sigma",
        "anchor_floor", "anchor_ceiling"))
    applied = latest.filter(pl.col("anchor_applied")).height
    print(f"  week {freeze} preseason-anchor applied: {applied} of {latest.height}")
    return df


def run(season: int) -> None:
    df = compute(season)
    data_layer.write_ros_player_band(df, season)   # scoring-scoped; defaults to the is_mine profile
    sk = data_layer._active_league(season)[1]
    print(f"  → snapshots/derived/scoring/{sk}/ros_player_band_{season}.parquet")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute the ROS player band (scoring-scoped §2 half).")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    run(args.season)
    sys.exit(0)
