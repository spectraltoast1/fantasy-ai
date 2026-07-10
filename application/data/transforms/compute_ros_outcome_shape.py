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

**Situation / security** — the forward face of the Opportunity "Trust" axis (§2). Rather than
re-derive it, the read carries the already-materialised structured evidence from
compute_player_signal per (as_of_week, roster_id, player): the Sleeper `security` tier
(stable / questionable / depth_chart_risk / flagged) plus the trust axis `direction` /
`reliability`. Carried through as evidence, not fused into a score. Draft-capital / ADP enrichment
and the AI news interpretation are deferred (no source fetched; Phase 6).

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
# against the 2025 answer key** to 1.645 (freeze-week coverage 0.835): note this sits *above* the
# normal-theory 1.28 for 80% — because ros_sigma sums the weekly bands under independence, but a
# player's weekly residuals are positively autocorrelated over a season (a bust tends to persist),
# so realised ROS is more dispersed than the independent sum predicts and the band must widen to
# stay honest. The gate's --sweep re-derives this. A league-agnostic tuning constant (config seed).
BULL_Z = 1.645


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


def _compute_as_of(vor_slice: pl.DataFrame, consensus: pl.DataFrame, signal_slice: pl.DataFrame,
                   n: int, max_proj_week: int, season: int, *, bull_z: float) -> list:
    """ROS Outcome Shape rows for one as-of cutoff N: reuse the Production VOR slice's ros_value as
    the borrowed centre, add the accumulated band std over the remaining weeks, form the bull/bear
    range, and carry the structured situation/security evidence from the player_signal slice.
    Returns row dicts tagged as_of_week = N (with a per-position league-relative bull spectrum)."""
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
        band = _outcome_band(center, sigma, bull_z=bull_z)
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

    all_rows = []
    for n in sorted(vor["as_of_week"].unique().to_list()):
        all_rows.extend(_compute_as_of(
            vor.filter(pl.col("as_of_week") == n),
            consensus,
            signal.filter(pl.col("as_of_week") == n),
            n, max_proj_week, season, bull_z=BULL_Z,
        ))

    df = pl.DataFrame(all_rows, infer_schema_length=None).sort(
        "as_of_week", "roster_id", "ros_bull", descending=[False, False, True]
    )
    freeze = int(df["as_of_week"].max())
    latest = df.filter(pl.col("as_of_week") == freeze)
    print(f"=== ROS Outcome Shape: season={season}  as_of_week 1..{freeze}  "
          f"(ROS horizon → week {max_proj_week}; BULL_Z={BULL_Z}; rows={df.height}) ===")
    print(f"  week {freeze} widest ranges (top bull ceilings):")
    print(latest.head(6).select(
        "sleeper_player_id", "position", "ros_bear", "ros_center", "ros_bull", "ros_sigma",
        "ros_cv", "security"))
    flagged = latest.filter(pl.col("security") != "stable").height
    print(f"  week {freeze} situation-flagged (security != stable): {flagged} of {latest.height}")
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
