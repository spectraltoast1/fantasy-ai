"""
Compute ROS Outcome Shape — bull / bear / situation-security per player (DECISION_READS.md §2).

The forward player read that frames "what's the realistic rest-of-season range for this player,
and how solid is the ground under the bet?" This transform builds the **quantitative skeleton**;
the AI narrative + 1-10 grade roll-up is Phase 6 (we emit the structured anchor quantities, not a
fused grade — laws 2 + 4: don't collapse the axes, show the numbers).

**Bull / bear is the ROS-horizon analog of the §3 weekly spread.** §3 gives each week a borrowed
centre + a calibrated band; summing the centres over the remaining schedule is exactly Production
VOR's `ros_value`, and summing the per-week *variances* gives the ROS band:

  - ros_center = the borrowed ROS centre = Production VOR's `ros_value` (Σ weekly consensus centres
    over the remaining schedule, weeks > N). Borrowed, not rebuilt — reused directly so it can't
    drift from the §4 read (design law 3).
  - ros_sigma  = √(Σ band_ppr² over the same remaining weeks) — the §3 shrunk weekly residual std
    combined across weeks under **weekly independence** (the same documented assumption
    compute_bracket_sim makes for its team score-distribution σ; no residual-autocorrelation model).
  - ros_bull / ros_bear = ros_center ± BULL_Z·ros_sigma, floored at 0 (a bad season can't go
    negative). BULL_Z sets the interval width and is **backtest-tuned** — see
    backtest_ros_outcome_shape.py, the ROS-horizon analog of the §3 band's BAND_Z sweep.
  - ros_cv = ros_sigma / ros_center — relative dispersion, a fragility proxy (wide band per unit of
    value = a shakier bet).

**Time decay is emergent, not a separate mechanism (§2's "less remaining season = less room").**
As the cutoff N advances, the remaining schedule shrinks, so `Σ band²` shrinks, so the absolute
band compresses toward the realised path — exactly the dynamic §2 specifies, falling straight out
of the horizon math.

**Preseason anchor (§2's "realistic preseason limits").** The pure-projection band above knows only
the in-season projection — it has no memory of what the player was *expected* to be preseason, so a
slumping star's ceiling collapses and a volatile benchwarmer's bull case can balloon past reality.
The anchor fixes both by pulling bull/bear toward an empirical preseason range: the historical
**ADP rank → realized-points** curve (compute_adp_points_curve.py) gives each drafted player a
floor / center / ceiling for "what a player drafted at his positional ADP rank actually produces",
scaled to the remaining schedule. The blend weight `w_N = ANCHOR_W · (remaining_weeks / total_weeks)`
decays with the horizon — prior-driven early, evidence-driven late (§2's dynamic, made explicit
rather than only emergent). `ros_center` stays the borrowed projection (law 3 — borrow the centre,
build the spread); only the bull/bear extremes are anchored. A player with no preseason draft rank
(undrafted) or missing curve coverage falls back to `w=0` — the pure-projection band — so the read
never breaks. Preseason inputs ride along as evidence (`adp_ecr` / `adp_best` / `adp_worst` /
`anchor_floor` / `anchor_ceiling` / `anchor_applied`).

**Situation / security** — the forward face of the Opportunity "Trust" axis (§2). Rather than
re-derive it, the read carries the already-materialised structured evidence from
compute_player_signal per (as_of_week, roster_id, player): the Sleeper `security` tier
(stable / questionable / depth_chart_risk / flagged) plus the trust axis `direction` /
`reliability`. Carried through as evidence, not fused into a score. The AI news interpretation is
deferred (Phase 6).

Tall over as_of_week like the other derived analytics (roster-as-of-N inherited from the Production
VOR slice); read via read_ros_outcome_shape(season, as_of_week=None) (default = latest).

Output: snapshots/derived/ros_outcome_shape_{season}.parquet, one row per (as_of_week, rostered player).

Usage:
    python -m application.data.transforms.compute_ros_outcome_shape --season 2025
"""

import argparse
import sys
from collections import defaultdict
from pathlib import Path

import polars as pl

from application.data import data_layer
from application.data.transforms._analytics import round1, spectrum_positions

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]

# Bull/bear half-width in σ units. Targets an ~80% (10th/90th) "good season / bad season" range,
# wider than §3's interquartile band, per §2's "realistic high / low" framing. **Backtest-tuned
# jointly with ANCHOR_W against the 2025 answer key** (backtest_ros_outcome_shape.py --sweep) to
# (1.44, 0.25): freeze-week coverage 0.817 with balanced miss tails (below-bear 0.091 / above-bull
# 0.091) — the objective is |coverage−target| + |tail imbalance|, so the pair is both calibrated and
# centred, not coverage-chased into a lopsided band. Sits above the normal-theory 1.28 for 80%
# because ros_sigma sums the weekly bands under independence, but a player's weekly residuals are
# positively autocorrelated over a season (a bust persists), so realised ROS is more dispersed than
# the independent sum predicts and the band must widen to stay honest. (Was 1.645 pre-anchor: the
# anchor corrects the projection's low-miss bias, so the same coverage needs less raw width.)
BULL_Z = 1.44
# Max preseason-anchor weight, at a full remaining season (the blend weight is ANCHOR_W scaled by the
# remaining-season fraction, so it decays to ~0 as the horizon closes — §2's prior→evidence dynamic).
# ANCHOR_W = 0 recovers the pure-projection band (the pre-anchor behaviour). **Backtest-tuned jointly
# with BULL_Z** (above): the sweep is free to drive it to 0 if the anchor earns nothing, and it lands
# at 0.25 — the anchor rebalances the freeze-week miss tails from a lopsided 0.128/0.037 (pre-anchor,
# projection overprojects floors) to a centred 0.091/0.091. Empirical, not assumed.
ANCHOR_W = 0.25


def _ros_sigma(consensus: pl.DataFrame, remaining_weeks) -> pl.DataFrame:
    """Per player: the accumulated ROS band std over the remaining schedule = √(Σ band_ppr²).

    Mirrors compute_production_vor._ros_values but aggregates the §3 weekly band's *variance*
    (band_ppr²) instead of the centre — so ros_sigma sums over exactly the same remaining weeks as
    ros_value. A null weekly band contributes 0 (guarded the way compute_bracket_sim does with
    `band_ppr or 0.0`). One row per player with any projected remaining week.
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
    """bull/bear rest-of-season range around the borrowed centre: centre ± bull_z·sigma, floored at
    0 (a season's realised production can't be negative). ros_cv = sigma/centre (relative
    dispersion / fragility), None where the centre is non-positive (degenerate deep-bench spot)."""
    bull = max(0.0, ros_center + bull_z * ros_sigma)
    bear = max(0.0, ros_center - bull_z * ros_sigma)
    cv = ros_sigma / ros_center if ros_center > 0 else None
    return {"ros_bull": bull, "ros_bear": bear, "ros_cv": cv}


def _preseason_anchor(adp_row: dict | None, curve_lookup: dict, curve_max_rank: dict,
                      remaining_frac: float) -> dict | None:
    """The player's empirical preseason floor/center/ceiling (§2 anchor), scaled to the remaining
    schedule. `adp_row` is his preseason ADP (position, pos_ecr_rank, ecr, best, worst) or None if he
    wasn't drafted; `curve_lookup` maps (position, rank) → (floor, center, ceiling) full-season PPR
    from compute_adp_points_curve; deep ranks clamp to the position's deepest fitted rank. Returns
    None (→ no anchor, pure-projection fallback) when the player has no draft rank or no curve
    coverage. Points are scaled by `remaining_frac` so a full-season curve value lines up with the
    remaining-weeks ros_center it will blend with."""
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
    *un-floored* so a negative projection bear can still be lifted by a positive preseason floor
    before the final 0-floor. ros_cv stays the projection's sigma/centre (fragility of the borrowed
    read, unchanged by the anchor)."""
    base = _outcome_band(ros_center, ros_sigma, bull_z=bull_z)
    if anchor is None or w <= 0.0:
        return {**base, "anchor_applied": False}
    proj_bull = ros_center + bull_z * ros_sigma
    proj_bear = ros_center - bull_z * ros_sigma
    bull = max(0.0, (1.0 - w) * proj_bull + w * anchor["anchor_ceiling"])
    bear = max(0.0, (1.0 - w) * proj_bear + w * anchor["anchor_floor"])
    return {"ros_bull": bull, "ros_bear": bear, "ros_cv": base["ros_cv"], "anchor_applied": True}


def _compute_as_of(vor_slice: pl.DataFrame, consensus: pl.DataFrame, signal_slice: pl.DataFrame,
                   n: int, max_proj_week: int, season: int, *, bull_z: float, anchor_w: float,
                   total_weeks: int, adp_map: dict, curve_lookup: dict, curve_max_rank: dict) -> list:
    """ROS Outcome Shape rows for one as-of cutoff N: reuse the Production VOR slice's ros_value as
    the borrowed centre, add the accumulated band std over the remaining weeks, blend the bull/bear
    range toward the preseason ADP anchor (weight decaying with the remaining horizon), and carry the
    structured situation/security evidence from the player_signal slice. Returns row dicts tagged
    as_of_week = N (with a per-position league-relative bull spectrum)."""
    remaining = range(n + 1, max_proj_week + 1)
    if not remaining:
        return []

    sigma_map = {
        r["sleeper_player_id"]: r["ros_sigma"]
        for r in _ros_sigma(consensus, remaining).iter_rows(named=True)
    }
    sig_map = {r["sleeper_player_id"]: r for r in signal_slice.iter_rows(named=True)}

    rows = []
    for r in vor_slice.iter_rows(named=True):
        pid = r["sleeper_player_id"]
        center = r["ros_value"]
        sigma = sigma_map.get(pid, 0.0)
        # Horizon-decaying anchor: full-season curve scaled to the remaining share, and the blend
        # weight ANCHOR_W tapered by that same share (prior-driven early, evidence-driven late).
        remaining_frac = r["n_weeks"] / total_weeks if total_weeks else 0.0
        anchor = _preseason_anchor(adp_map.get(pid), curve_lookup, curve_max_rank, remaining_frac)
        w = anchor_w * remaining_frac
        band = _blended_band(center, sigma, anchor, w, bull_z=bull_z)
        sig = sig_map.get(pid, {})
        rows.append({
            "season": season,
            "as_of_week": n,
            "roster_id": int(r["roster_id"]),
            "sleeper_player_id": pid,
            "position": r["position"],
            "ros_center": round1(center),
            "ros_bull": round1(band["ros_bull"]),
            "ros_bear": round1(band["ros_bear"]),
            "ros_sigma": round1(sigma),
            "ros_cv": round(band["ros_cv"], 3) if band["ros_cv"] is not None else None,
            "n_weeks": int(r["n_weeks"]),
            "security": sig.get("security", "unknown"),
            "direction": sig.get("direction"),
            "reliability": sig.get("reliability"),
            "anchor_applied": band["anchor_applied"],
            "adp_ecr": anchor["adp_ecr"] if anchor else None,
            "adp_best": anchor["adp_best"] if anchor else None,
            "adp_worst": anchor["adp_worst"] if anchor else None,
            "anchor_floor": round1(anchor["anchor_floor"]) if anchor else None,
            "anchor_ceiling": round1(anchor["anchor_ceiling"]) if anchor else None,
        })

    # League-relative bull ceiling within each position cohort at this cutoff (the §2 "vs league"
    # benchmark; separate from the per-player band math the gate validates).
    by_pos = defaultdict(list)
    for i, row in enumerate(rows):
        by_pos[row["position"]].append(i)
    for idxs in by_pos.values():
        sp = spectrum_positions([rows[i]["ros_bull"] for i in idxs])
        for i, s in zip(idxs, sp):
            rows[i]["spectrum_pos"] = round(s, 3)
    return rows


def _load_anchor_inputs(season: int) -> tuple[dict, dict, dict]:
    """(adp_map, curve_lookup, curve_max_rank) for the §2 preseason anchor. Returns empty maps if
    either ADP source is absent (fetchers not run) — every anchor then degrades to the pure-projection
    band, keeping the transform runnable without the ADP pipeline."""
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


def compute(season: int) -> pl.DataFrame:
    vor = data_layer.read_production_vor(season, as_of_week="all").select(
        "as_of_week", "roster_id", "sleeper_player_id", "position", "ros_value", "n_weeks"
    )
    consensus = data_layer.read_projection_consensus(season).select(
        "week", "sleeper_player_id", "band_ppr"
    )
    signal = data_layer.read_player_signal(season, as_of_week="all").select(
        "as_of_week", "sleeper_player_id", "security", "direction", "reliability"
    )
    max_proj_week = int(data_layer.read_projection_consensus(season)["week"].max())
    adp_map, curve_lookup, curve_max_rank = _load_anchor_inputs(season)

    all_rows = []
    for n in sorted(vor["as_of_week"].unique().to_list()):
        all_rows.extend(_compute_as_of(
            vor.filter(pl.col("as_of_week") == n),
            consensus,
            signal.filter(pl.col("as_of_week") == n),
            n, max_proj_week, season, bull_z=BULL_Z, anchor_w=ANCHOR_W,
            total_weeks=max_proj_week, adp_map=adp_map,
            curve_lookup=curve_lookup, curve_max_rank=curve_max_rank,
        ))

    df = pl.DataFrame(all_rows, infer_schema_length=None).sort(
        "as_of_week", "roster_id", "ros_bull", descending=[False, False, True]
    )
    freeze = int(df["as_of_week"].max())
    latest = df.filter(pl.col("as_of_week") == freeze)
    print(f"=== ROS Outcome Shape: season={season}  as_of_week 1..{freeze}  "
          f"(ROS horizon → week {max_proj_week}; BULL_Z={BULL_Z}; ANCHOR_W={ANCHOR_W}; rows={df.height}) ===")
    print(f"  week {freeze} widest ranges (top bull ceilings):")
    print(latest.head(6).select(
        "sleeper_player_id", "position", "ros_bear", "ros_center", "ros_bull", "ros_sigma",
        "anchor_floor", "anchor_ceiling"))
    applied = latest.filter(pl.col("anchor_applied")).height
    flagged = latest.filter(pl.col("security") != "stable").height
    print(f"  week {freeze} preseason-anchor applied: {applied} of {latest.height}; "
          f"situation-flagged (security != stable): {flagged}")
    return df


def run(season: int) -> None:
    df = compute(season)
    data_layer.write_ros_outcome_shape(df, season)
    print(f"  → snapshots/derived/ros_outcome_shape_{season}.parquet")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Compute ROS Outcome Shape from the borrowed projection.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    run(args.season)
