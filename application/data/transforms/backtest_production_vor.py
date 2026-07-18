"""
Backtest Production VOR against the full-2025 answer key.

The gate Production VOR (DECISION_READS.md §4) must clear before it drives any add/drop
surface: does the read actually rank rest-of-season *value*? VOR is built from the borrowed
projection, so the honest test is whether that projected value tracks what players really did.
Two verdicts (exit 0 iff both pass):

  - **Predictive** — per pool, does projected `ros_value` correlate with the **actual** ROS
    production (sum of realized fantasy_points_ppr over the same remaining weeks)? This
    validates the substrate the anchoring rests on. A VOR built on a projection that doesn't
    track reality is a confidently-wrong number (law 2). Threshold: corr ≥ CORR_MIN in each pool.
  - **Decision-relevant** — sort rostered players by VOR into terciles (dead weight / mid /
    studs) and confirm actual ROS production rises monotonically across them, with the
    negative-VOR ("below waiver") group clearly below the positive group. This is the add/drop
    claim VOR makes, tested the way backtest_player_signal tests spike-vs-sticky.

It imports the SAME pure functions the transform ships (`_ros_values`, `_pool_lines`, `_vor`,
`_pool_of`, `_roster_as_of`) — what's validated is exactly what serves the read, no re-derivation.
Also reported as evidence (not gated): how near the waiver-line anchor (vor ≈ 0) sits to the
actual replacement level, and the QB-vs-flex pool spreads (why 1QB compresses QB VOR).

Usage:
    python3 -m application.data.transforms.backtest_production_vor --season 2025
"""

import argparse
import sys
from pathlib import Path

import polars as pl

from application.data import data_layer
from application.data.transforms._analytics import mean, pearson
from application.data.transforms.compute_production_vor import (
    FORM_ANCHOR_W,
    SKILL_POSITIONS,
    _pool_lines,
    _pool_of,
    _realized_weekly_pts,
    _recent_form,
    _resolve_scoring,
    _roster_as_of,
    _ros_values,
    _vor,
)
# The scoring-scoped canonical answer key (player_weekly_pts_canonical) — reused, not re-derived (std instr 5).
from application.data.transforms.backtest_ros_player_band import _canonical_actual

# Minimum per-pool correlation between projected ros_value and actual ROS production.
CORR_MIN = 0.60
# The FORM_ANCHOR_W fit grades the de-biased ROS centre over the early-season decision window (as-of weeks
# 1..GRADE_WEEK) — where recent-form evidence exists and the ledger's production_vor predictions live (the
# roster freeze is weeks 1–4). Bounded + comparable to the band's freeze-week convention.
GRADE_WEEK = 4


def _actual_ros(season: int) -> pl.DataFrame:
    """Per (player, week) actual PPR points — the answer key the projected ROS is summed
    against over the matching remaining weeks."""
    return (
        data_layer.read_nfl_stats(season)
        .filter(pl.col("position").is_in(SKILL_POSITIONS))
        .select("sleeper_player_id", pl.col("week").cast(pl.Int64), "fantasy_points_ppr")
        .drop_nulls("sleeper_player_id")
        .group_by("sleeper_player_id", "week")
        .agg(pl.col("fantasy_points_ppr").first().alias("actual"))
    )


def _test_points(season: int, *, league_id=None, scoring_key=None) -> pl.DataFrame:
    """One row per (as_of_week N, rostered player): projected ros_value + vor from the shipped
    pure functions, and the actual ROS production over the same remaining weeks (N+1..end)."""
    consensus = data_layer.read_projection_consensus(season, scoring_key=scoring_key).select(
        "week", "sleeper_player_id", "position", "center_ppr"
    ).filter(pl.col("position").is_in(SKILL_POSITIONS))
    season_df = data_layer.read_join_season(season, league_id=league_id).filter(pl.col("position").is_in(SKILL_POSITIONS))
    pool_of = _pool_of(data_layer.read_lineup_slots(season, league_id=league_id))
    actual = _actual_ros(season)

    max_proj_week = int(consensus["week"].max())
    max_roster_week = int(season_df["week"].max())

    rows = []
    for n in range(1, max_roster_week + 1):
        remaining = list(range(n + 1, max_proj_week + 1))
        if not remaining:
            continue
        roster = _roster_as_of(season_df, n)
        rostered_ids = set(roster)
        ros = _ros_values(consensus, remaining)
        lines = _pool_lines(ros, rostered_ids, pool_of)
        # Actual ROS = realized points over the same remaining weeks, per player.
        act = (
            actual.filter(pl.col("week").is_in(remaining))
            .group_by("sleeper_player_id")
            .agg(pl.col("actual").sum().alias("actual_ros"))
        )
        act_map = {r["sleeper_player_id"]: float(r["actual_ros"]) for r in act.iter_rows(named=True)}
        for r in ros.filter(pl.col("sleeper_player_id").is_in(list(rostered_ids))).iter_rows(named=True):
            pool = pool_of.get(r["position"])
            line = lines.get(pool)
            if line is None:
                continue
            rows.append({
                "as_of_week": n,
                "sleeper_player_id": r["sleeper_player_id"],
                "position": r["position"],
                "pool": pool,
                "ros_value": float(r["ros_value"]),
                "vor": _vor(float(r["ros_value"]), line["waiver"], line["top"]),
                "waiver_line": line["waiver"],
                # Actual production over the remaining weeks (0.0 if he recorded none — a
                # rostered player who didn't play produced nothing, the honest truth).
                "actual_ros": act_map.get(r["sleeper_player_id"], 0.0),
            })
    return pl.DataFrame(rows)


def objective(season: int, consts: dict, *, reader=data_layer) -> float:
    """The tuner's scalar fit objective for FORM_ANCHOR_W (the S7 de-bias λ), at the value in `consts`, on
    `reader`'s allowed partition — LOWER is better. Scoring-scoped: for each scoring_key in the season's
    MATCHED cohort it builds the DE-BIASED ROS centre (the shipped `_ros_values` blend at λ) over the
    projected skill pool at as-of weeks 1..GRADE_WEEK, and scores MAE against the realised ROS under that
    key's CANONICAL answer key (`_canonical_actual` — NOT raw fantasy_points_ppr, the 6b basis: PPR
    over-credits receptions for non-PPR keys by up to ~7 pts/wk). Returns the mean per-key MAE.

    Reuses the shipped blend + recent-form helpers (std instr 5); recent-form is the SAME scoring-scoped
    series the transform consumes, so the fit measures exactly what would ship. λ=0 recovers the
    borrowed-centre MAE — the baseline the de-bias must beat. Graded over players with realised season
    signal (present in the answer key), so the never-played deep bench doesn't dilute the fit."""
    lam = consts.get("FORM_ANCHOR_W", FORM_ANCHOR_W)
    manifest = data_layer.read_corpus_manifest()  # metadata (no season arg → not a sealed read)
    keys = (manifest.filter((pl.col("stratum") == "matched") & (pl.col("season") == season))
            ["scoring_key"].unique().to_list())
    if not keys:
        raise ValueError(f"no matched leagues for season {season}")
    maes = []
    for sk in keys:
        # Read through `reader` FIRST (season-guarded ⇒ a sealed season raises before any downstream work).
        consensus = (
            reader.read_projection_consensus(season, scoring_key=sk)
            .select("week", "sleeper_player_id", "position", "center_ppr")
            .filter(pl.col("position").is_in(SKILL_POSITIONS))
        )
        truth = _canonical_actual(season, sk, reader=reader)   # (pid, week) → realised canonical pts
        played = {pid for (pid, _wk) in truth}                 # players with any realised week this season
        realized = _realized_weekly_pts(season, _resolve_scoring(season, sk, reader=reader), reader=reader)
        max_proj_week = int(consensus["week"].max())
        errs = []
        for n in range(1, min(GRADE_WEEK, max_proj_week - 1) + 1):
            remaining = list(range(n + 1, max_proj_week + 1))
            if not remaining:
                continue
            recent_form = _recent_form(realized, n) if realized.height else None
            ros = _ros_values(consensus, remaining, recent_form=recent_form, form_anchor_w=lam)
            for r in ros.iter_rows(named=True):
                pid = r["sleeper_player_id"]
                if pid not in played:
                    continue
                actual_ros = sum(truth.get((pid, wk), 0.0) for wk in remaining)
                errs.append(abs(r["ros_value"] - actual_ros))
        if errs:
            maes.append(sum(errs) / len(errs))
    if not maes:
        raise ValueError(f"no gradeable ROS-centre rows for season {season}")
    return sum(maes) / len(maes)


def run(season: int, *, league_id=None, scoring_key=None) -> bool:
    tp = _test_points(season, league_id=league_id, scoring_key=scoring_key)
    print(f"=== Production VOR backtest: season={season}  test points={tp.height} "
          f"(rostered player × as-of week) ===")

    # 1. Predictive — per-pool corr(projected ros_value, actual ROS).
    print()
    print(f"  predictive: corr(projected ros_value, actual ROS) per pool  (min {CORR_MIN:.2f}):")
    pool_ok = True
    for pool in ("QB", "FLEX"):
        g = tp.filter(pl.col("pool") == pool)
        r = pearson(g["ros_value"].to_list(), g["actual_ros"].to_list())
        ok = r is not None and r >= CORR_MIN
        pool_ok = pool_ok and ok
        print(f"    {pool:<5} n={g.height:<5} corr={r:.3f}  {'PASS' if ok else 'FAIL'}")

    # 2. Decision-relevant — VOR terciles → monotonic actual ROS; negatives clearly below.
    q1, q2 = tp["vor"].quantile(1 / 3), tp["vor"].quantile(2 / 3)
    tp2 = tp.with_columns(
        pl.when(pl.col("vor") <= q1).then(pl.lit("dead"))
        .when(pl.col("vor") <= q2).then(pl.lit("mid"))
        .otherwise(pl.lit("stud")).alias("tier")
    )
    tier_mean = {t: mean(g["actual_ros"].to_list()) for (t,), g in tp2.group_by("tier")}
    d, m, s = tier_mean.get("dead", 0.0), tier_mean.get("mid", 0.0), tier_mean.get("stud", 0.0)
    monotonic = d < m < s
    neg = tp.filter(pl.col("vor") < 0)
    pos = tp.filter(pl.col("vor") >= 0)
    neg_m, pos_m = mean(neg["actual_ros"].to_list()), mean(pos["actual_ros"].to_list())
    print()
    print(f"  decision-relevant: mean ACTUAL ROS production by VOR tier (want dead < mid < stud):")
    print(f"    dead {d:6.1f}   mid {m:6.1f}   stud {s:6.1f}   {'PASS' if monotonic else 'FAIL'}")
    print(f"    below-waiver (vor<0) {neg_m:.1f}  vs  at-or-above (vor≥0) {pos_m:.1f}  "
          f"(n {neg.height}/{pos.height})")

    # Evidence (not gated): the waiver anchor's realism + the pool spreads.
    near0 = tp.filter((pl.col("vor") >= -0.1) & (pl.col("vor") <= 0.1))
    print()
    print(f"  evidence: near-waiver players (|vor|≤0.1, n={near0.height}) mean actual ROS "
          f"{mean(near0['actual_ros'].to_list()):.1f}  (the realized replacement level)")

    ok = pool_ok and monotonic
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — projected ROS "
          f"{'tracks' if pool_ok else 'does NOT track'} actual per pool (≥{CORR_MIN:.2f}); "
          f"VOR tiers {'are' if monotonic else 'are NOT'} monotonic in actual production.")
    return ok


def __main():
    parser = argparse.ArgumentParser(description="Backtest Production VOR against the 2025 answer key.")
    parser.add_argument("--season", type=int, required=True)
    args = parser.parse_args()
    sys.exit(0 if run(args.season) else 1)


if __name__ == "__main__":
    __main()
