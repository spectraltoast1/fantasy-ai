"""
Backtest the ROS Player Band bull/bear band against the full-2025 answer key.

(Renamed from backtest_ros_outcome_shape.py in the L0 keying split — the band it validates is now the
scoring-scoped ros_player_band; the calibration is computed on the is_mine league's rostered players
[band ⋈ production_vor], reproducing the pre-split numbers since it rebuilds the band through the same
pure functions from production_vor.ros_value.)

The gate §2's quantitative skeleton (DECISION_READS.md §2) must clear: is the rest-of-season
bull/bear range **calibrated** — does a player's realised ROS production actually land inside
[ros_bear, ros_bull] about as often as the interval claims? Bull/bear is the ROS-horizon analog
of the §3 weekly spread, so it earns its width the same way §3 does: against reality, not by
assumption. Two verdicts (exit 0 iff both pass):

  - **Calibration (predictive)** — at the freeze week, the fraction of players whose actual ROS
    lands in [ros_bear, ros_bull] must sit within COVERAGE_TOL of the TARGET (0.80 — an ~80% "good
    season / bad season" range, §2's realistic high/low). The two tail rates (below-bear /
    above-bull) are reported as evidence: the skeleton's band is symmetric-by-design (no ROS-level
    skew term — a documented deferral; the §3 per-week band already carries the skew this sums
    over), so we gate combined coverage and *report* tail balance. `--sweep` tunes BULL_Z against
    the answer key — the ROS analog of the §3 gate's BAND_Z sweep. This is the real test: summing
    independent weekly bands assumes zero residual autocorrelation, and BULL_Z absorbs whatever
    that assumption gets wrong.
  - **Decision-relevant** — sort players by ros_bull (the ceiling) into terciles and confirm actual
    realised ROS rises monotonically (dead < mid < stud), the way backtest_production_vor tests VOR
    tiers. Confirms the bull ceiling carries ranking signal, not just width.

It imports the SAME pure functions the transform ships (`_ros_sigma`, `_preseason_anchor`,
`_blended_band`, `_load_anchor_inputs`) — what's validated is exactly what serves the read, no
re-derivation. Per-player realised ROS is a simple
Σ actual PPR over the remaining weeks (a player read, not a team read — no optimal_lineup). The
band's forward inputs (each week's band_ppr, built from weeks < that week) never see the actuals
they're tested against — no leakage.

**Small-sample honesty (documented):** the primary gate is the **freeze-week** snapshot (each
player once, longest real ROS). Coverage across ~160 players is a fair calibration sample, but a
league-wide over/under-projection correlates their misses, so pooling the nested per-week windows
(same player at N=1..4) would inflate n without independent signal — reported as evidence only.

**Preseason-anchor honesty (documented):** the roster is frozen at weeks 1–4, so every tested cutoff
(N=1..4) sits in the **early / prior-heavy** regime — the anchor weight w_N = ANCHOR_W · (remaining/
total) is near its max here (≈0.19 at the freeze). The late-season, evidence-heavy tail of the decay
(w_N → 0 as the horizon closes) is asserted by construction, not exercised by this answer key; it
cannot be until an as-of week past the freeze exists. The sweep therefore tunes ANCHOR_W where the
anchor matters most, which is the honest place to tune it. The gate reports the pre-anchor vs
anchored freeze-week tails so the anchor's calibration contribution is visible, not assumed.

Usage:
    python3 -m application.data.transforms.backtest_ros_player_band --season 2025
    python3 -m application.data.transforms.backtest_ros_player_band --season 2025 --sweep
"""

import argparse
import sys
from pathlib import Path

import polars as pl

from application.data import data_layer
from application.data.transforms._analytics import mean
from application.data.transforms.compute_ros_player_band import (
    ANCHOR_W, BULL_Z, SKILL_POSITIONS, _blended_band, _load_anchor_inputs, _preseason_anchor, _ros_sigma,
)

# Target bull/bear coverage — the fraction of players whose actual ROS should land in the band.
# 0.80 = an ~80% (10th/90th) "good season / bad season" interval, §2's realistic high/low.
TARGET_COVERAGE = 0.80
# The freeze-week combined coverage must land within this of TARGET_COVERAGE.
COVERAGE_TOL = 0.05
# BULL_Z candidates swept against the answer key. Labelled by their normal-theory coverage so the
# sweep output is legible; residuals summed over the ROS horizon are near-normal by CLT, so the
# empirical best sits near the 0.80 target's 1.28 unless autocorrelation shifts it.
BULL_Z_GRID = [0.674, 0.842, 1.036, 1.150, 1.282, 1.440, 1.645, 1.960]
# Preseason-anchor max weight candidates. 0.0 = pure-projection band (the pre-anchor read), so the
# sweep is free to conclude the §2 anchor earns nothing at the freeze and drive it to 0 — the shipped
# weight is whatever the answer key rewards, jointly with BULL_Z (the anchor reshapes the band, so
# the two must be tuned together, not in sequence).
ANCHOR_W_GRID = [0.0, 0.25, 0.5, 0.75, 1.0]


def _actual_weekly(season: int) -> dict:
    """(sleeper_player_id, week) → actual PPR points, the answer key for realised ROS."""
    df = (
        data_layer.read_nfl_stats(season)
        .filter(pl.col("position").is_in(SKILL_POSITIONS))
        .select("sleeper_player_id", pl.col("week").cast(pl.Int64), "fantasy_points_ppr")
        .drop_nulls("sleeper_player_id")
        .group_by("sleeper_player_id", "week")
        .agg(pl.col("fantasy_points_ppr").first().alias("actual"))
    )
    return {(r["sleeper_player_id"], r["week"]): float(r["actual"]) for r in df.iter_rows(named=True)}


def _test_points(season: int, bull_z: float, anchor_w: float):
    """One row per (as_of_week N, player): the shipped bull/bear band + the actual ROS over the same
    remaining weeks. Rebuilds the band through the transform's own `_preseason_anchor` / `_blended_band`
    (and `_load_anchor_inputs`), so what's validated is exactly what serves the read — no re-derivation.
    Returns (rows, freeze_week). Security is carried for the situation-axis evidence line."""
    vor = data_layer.read_production_vor(season, as_of_week="all").select(
        "as_of_week", "roster_id", "sleeper_player_id", "position", "ros_value", "n_weeks"
    )
    consensus = data_layer.read_projection_consensus(season).select(
        "week", "sleeper_player_id", "band_ppr"
    )
    signal = data_layer.read_player_signal(season, as_of_week="all").select(
        "as_of_week", "sleeper_player_id", "security"
    )
    actual = _actual_weekly(season)
    adp_map, curve_lookup, curve_max_rank = _load_anchor_inputs(season)

    weeks = sorted(vor["as_of_week"].unique().to_list())
    freeze = max(weeks)
    max_proj_week = int(consensus["week"].max())

    rows = []
    for n in weeks:
        remaining = list(range(n + 1, max_proj_week + 1))
        if not remaining:
            continue
        sigma_map = {
            r["sleeper_player_id"]: r["ros_sigma"]
            for r in _ros_sigma(consensus, remaining).iter_rows(named=True)
        }
        sec_map = {
            r["sleeper_player_id"]: r["security"]
            for r in signal.filter(pl.col("as_of_week") == n).iter_rows(named=True)
        }
        for r in vor.filter(pl.col("as_of_week") == n).iter_rows(named=True):
            pid = r["sleeper_player_id"]
            remaining_frac = r["n_weeks"] / max_proj_week if max_proj_week else 0.0
            anchor = _preseason_anchor(adp_map.get(pid), curve_lookup, curve_max_rank, remaining_frac)
            band = _blended_band(
                r["ros_value"], sigma_map.get(pid, 0.0), anchor, anchor_w * remaining_frac, bull_z=bull_z
            )
            act = sum(actual.get((pid, wk), 0.0) for wk in remaining)
            rows.append({
                "as_of_week": n, "roster_id": int(r["roster_id"]), "sleeper_player_id": pid,
                "position": r["position"], "bear": band["ros_bear"],
                "bull": band["ros_bull"], "actual": act,
                "security": sec_map.get(pid, "unknown"),
            })
    return rows, freeze


def _coverage(df: pl.DataFrame) -> tuple[float, float, float]:
    """(inside-band rate, below-bear rate, above-bull rate)."""
    n = df.height
    inside = df.filter((pl.col("actual") >= pl.col("bear")) & (pl.col("actual") <= pl.col("bull"))).height
    below = df.filter(pl.col("actual") < pl.col("bear")).height
    above = df.filter(pl.col("actual") > pl.col("bull")).height
    return inside / n, below / n, above / n


def sweep(season: int) -> None:
    """Sweep (BULL_Z × ANCHOR_W) jointly against the answer key: pick the pair whose freeze-week
    coverage is closest to TARGET_COVERAGE (tails reported so an asymmetric miss is visible). Joint
    because the preseason anchor reshapes the band, so the calibrated width depends on the anchor
    weight — tuning them in sequence would miss the interaction."""
    print(f"=== BULL_Z × ANCHOR_W sweep (freeze week): season={season}  target coverage={TARGET_COVERAGE:.2f} ===")
    print(f"  {'bull_z':>8}{'anchor_w':>10}{'coverage':>10}{'below-bear':>12}{'above-bull':>12}{'score':>9}")
    # Selection objective = |coverage − target| + |below-bear − above-bull|: calibrated AND centered.
    # The band is symmetric-by-design (no ROS skew term), so among equally-calibrated pairs the honest
    # choice is the one whose miss tails are balanced, not one skewed low or high — this is why a
    # coverage-only pick can mislead (it will chase target coverage into a lopsided band).
    best = (None, None, 9.9)
    for w in ANCHOR_W_GRID:
        for z in BULL_Z_GRID:
            rows, freeze = _test_points(season, z, w)
            fz = pl.DataFrame(rows).filter(pl.col("as_of_week") == freeze)
            cov, below, above = _coverage(fz)
            score = abs(cov - TARGET_COVERAGE) + abs(below - above)
            if score < best[2]:
                best = (z, w, score)
            print(f"  {z:>8.3f}{w:>10.2f}{cov:>10.3f}{below:>12.3f}{above:>12.3f}{score:>9.3f}")
    print(f"  → best (BULL_Z, ANCHOR_W) at this answer key: ({best[0]}, {best[1]}) "
          f"score={best[2]:.3f} (|cov-tgt|+|tail imbalance|) — bake into compute_ros_player_band.py")


def run(season: int, bull_z: float = BULL_Z, anchor_w: float = ANCHOR_W) -> bool:
    rows, freeze = _test_points(season, bull_z, anchor_w)
    tp = pl.DataFrame(rows)
    fz = tp.filter(pl.col("as_of_week") == freeze)
    print(f"=== ROS Player Band backtest: season={season}  test points={tp.height} "
          f"(player × as-of week; freeze week={freeze}, n={fz.height})  BULL_Z={bull_z}  ANCHOR_W={anchor_w} ===")

    # 1. Calibration — freeze-week coverage near TARGET, tails reported (symmetric band, no ROS skew term).
    cov, below, above = _coverage(fz)
    cov_pool, _, _ = _coverage(tp)
    calibrated = abs(cov - TARGET_COVERAGE) <= COVERAGE_TOL
    print()
    print(f"  calibration (freeze week {freeze}; target {TARGET_COVERAGE:.2f} ± {COVERAGE_TOL:.2f}):")
    print(f"    actual ROS in [bear, bull] = {cov:.3f}  {'PASS' if calibrated else 'FAIL'}")
    print(f"    tails: below-bear {below:.3f} / above-bull {above:.3f}  (symmetric band — evidence, not gated)")
    print(f"    [evidence] pooled coverage over weeks 1..{freeze} (n={tp.height}, nested/non-indep) = {cov_pool:.3f}")

    # Anchor effect (evidence): the §2 preseason anchor's mark on the freeze-week band vs the
    # pre-anchor pure-projection band at the SAME bull_z (isolates what the anchor changed, not the width).
    pre_rows, _ = _test_points(season, bull_z, 0.0)
    pre = pl.DataFrame(pre_rows).filter(pl.col("as_of_week") == freeze)
    pcov, pbelow, pabove = _coverage(pre)
    print()
    print(f"  [evidence] preseason-anchor effect at freeze (bull_z={bull_z}):")
    print(f"    pre-anchor  (ANCHOR_W=0.00): coverage {pcov:.3f}  below-bear {pbelow:.3f}  above-bull {pabove:.3f}")
    print(f"    anchored    (ANCHOR_W={anchor_w:.2f}): coverage {cov:.3f}  below-bear {below:.3f}  above-bull {above:.3f}")

    # 2. Decision-relevant — terciles by ros_bull, actual ROS rises monotonically (dead < mid < stud).
    g = fz.sort("bull", descending=False)
    third = g.height // 3
    dead = mean(g.head(third)["actual"].to_list())
    stud = mean(g.tail(third)["actual"].to_list())
    mid = mean(g.slice(third, g.height - 2 * third)["actual"].to_list())
    monotonic = dead < mid < stud
    print()
    print(f"  decision-relevant: mean ACTUAL ROS by ros_bull tercile (expect dead < mid < stud)")
    print(f"    dead {dead:.1f}  <  mid {mid:.1f}  <  stud {stud:.1f}   {'PASS' if monotonic else 'FAIL'}")

    # Evidence (not gated): does the situation axis carry signal — do non-stable players miss LOW more?
    def _miss_low(df):
        return df.filter(pl.col("actual") < pl.col("bear")).height / df.height if df.height else float("nan")
    stable = fz.filter(pl.col("security") == "stable")
    shaky = fz.filter(pl.col("security") != "stable")
    print()
    print(f"  [evidence] below-bear (bear-case broke) rate by security tier:")
    print(f"    stable {_miss_low(stable):.3f} (n={stable.height})   non-stable {_miss_low(shaky):.3f} (n={shaky.height})")

    ok = calibrated and monotonic
    print()
    print(f"  VERDICT: {'PASS' if ok else 'FAIL'} — bull/bear band {'is' if calibrated else 'is NOT'} "
          f"calibrated at the freeze (coverage {cov:.3f} vs target {TARGET_COVERAGE:.2f}); "
          f"ros_bull {'ranks' if monotonic else 'does NOT rank'} realised ROS (dead<mid<stud).")
    return ok


def __main():
    parser = argparse.ArgumentParser(description="Backtest ROS Outcome Shape against the 2025 answer key.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--sweep", action="store_true",
                        help="sweep BULL_Z against the answer key instead of running the verdict")
    args = parser.parse_args()
    if args.sweep:
        sweep(args.season)
        sys.exit(0)
    sys.exit(0 if run(args.season) else 1)


if __name__ == "__main__":
    __main()
