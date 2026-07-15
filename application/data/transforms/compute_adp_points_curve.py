"""
Fit the historical ADP rank -> realized-points curve (the §2 preseason anchor's empirical core).

DECISION_READS §2 wants the ROS bull/bear range "anchored to realistic preseason limits (draft
capital / ADP ceiling & floor)". This transform answers the empirical question behind that: **what
does a player drafted at positional ADP rank r ACTUALLY produce over a full season?** — fit from
prior seasons, so the anchor reflects realized outcomes (including bust/injury risk in the floor and
league-winner upside in the ceiling), independent of the current in-season projection.

For each training season it pairs the preseason positional ADP rank (adp_preseason.pos_ecr_rank)
with the player's realized full-season PPR (Σ fantasy_points_ppr from nfl_stats). A player drafted
but who never produced (preseason injury, cut, bust) left-joins to a realized 0.0 — that IS the
floor signal, kept on purpose. Pairs are pooled across seasons, then per position the P10 / P50 /
P90 (= floor / center / ceiling) are read off a **rolling window over rank** (per-rank samples are
too thin alone: one player per exact rank per season). The freeze/target season is held out of the
fit so the anchor it feeds carries no leakage.

Output: snapshots/derived/adp_points_curve/holdout_{S}.parquet — one row per (position, pos_ecr_rank):
floor_ppr / center_ppr / ceiling_ppr + bin count n + provenance (holdout_season / train_seasons).
**One curve per held-out target season S**, fit on every season EXCEPT S — so a multi-season corpus
grading §2 on season S reads an anchor that never saw S (the leak the flat pooled curve hid). Gated by
check_adp_curve_leakage.py.

Usage:
    python3 -m application.data.transforms.compute_adp_points_curve --holdout 2025   # one season
    python3 -m application.data.transforms.compute_adp_points_curve --all            # every season
"""

import argparse
import sys

import polars as pl

from application.data import data_layer
from application.data.transforms._analytics import quantile

SKILL_POSITIONS = ["QB", "RB", "WR", "TE"]

# Curve is fit over rosterable draft depth; ranks beyond this flatten toward replacement and the
# anchor clamps a deeper player to the last fitted rank. Generous enough to cover every position's
# startable + bench-worthy pool in a standard league.
MAX_RANK = 60
# Rolling half-window over positional rank: rank r pools realized outcomes of players drafted in
# [r-HALF_WINDOW, r+HALF_WINDOW] across all training seasons, so each rank's percentiles rest on a
# real sample (~one player/rank/season alone is far too thin for a P10/P90).
HALF_WINDOW = 3
# A rank bin needs at least this many pooled samples to publish a curve point; thinner bins are
# omitted and the anchor falls back for players landing there.
MIN_BIN_N = 8
FLOOR_Q, CENTER_Q, CEILING_Q = 0.10, 0.50, 0.90


def _season_realized(season: int) -> pl.DataFrame:
    """(sleeper_player_id, realized_ppr) — realized full-season PPR from the frozen nfl_stats."""
    return (
        data_layer.read_nfl_stats(season)
        .filter(pl.col("position").is_in(SKILL_POSITIONS))
        .with_columns(pl.col("fantasy_points_ppr").fill_null(0.0))
        .group_by("sleeper_player_id")
        .agg(pl.col("fantasy_points_ppr").sum().alias("realized_ppr"))
        .filter(pl.col("sleeper_player_id").is_not_null())
    )


def _training_pairs(train_seasons: list[int]) -> pl.DataFrame:
    """Pool (position, pos_ecr_rank, realized_ppr) over the training seasons. ADP is the left side
    (every drafted player contributes, incl. a 0.0-realized bust) and realized is looked up per
    player; a drafted player with no stats row realizes 0.0."""
    frames = []
    for season in train_seasons:
        adp = data_layer.read_adp_preseason(season).select(
            "sleeper_player_id", "position", "pos_ecr_rank"
        )
        realized = _season_realized(season)
        pairs = adp.join(realized, on="sleeper_player_id", how="left").with_columns(
            pl.col("realized_ppr").fill_null(0.0)
        )
        frames.append(pairs.select("position", "pos_ecr_rank", "realized_ppr"))
    return pl.concat(frames)


def _isotonic_decreasing(values, weights):
    """Weighted pool-adjacent-violators fit, constrained **non-increasing** — the L2-optimal
    monotone curve. A better (lower) draft rank should never realize fewer points than a worse one;
    the raw rolling-window percentiles wiggle on ~20-35-sample bins, so this removes the local
    inversions without the downward bias a running-min would introduce (it averages violators,
    weighted by bin count, rather than flooring to the min). Returns one value per input rank."""
    stack = []  # each block: [weighted_sum, weight, count]
    for v, w in zip(values, weights):
        block = [v * w, w, 1]
        while stack and stack[-1][0] / stack[-1][1] < block[0] / block[1]:
            prev = stack.pop()
            block[0] += prev[0]; block[1] += prev[1]; block[2] += prev[2]
        stack.append(block)
    out = []
    for wsum, w, count in stack:
        out += [wsum / w] * count
    return out


def _fit_curve(pairs: pl.DataFrame) -> pl.DataFrame:
    """Per position × rank (1..MAX_RANK): floor/center/ceiling = P10/P50/P90 of realized PPR over the
    rolling rank window, then each series isotonic-smoothed (non-increasing in rank, weighted by bin
    count) and re-ordered floor ≤ center ≤ ceiling. Bins below MIN_BIN_N are omitted."""
    out_frames = []
    for pos in SKILL_POSITIONS:
        sub = pairs.filter(pl.col("position") == pos)
        raw = []
        for r in range(1, MAX_RANK + 1):
            vals = sub.filter(
                pl.col("pos_ecr_rank").is_between(r - HALF_WINDOW, r + HALF_WINDOW)
            )["realized_ppr"].to_list()
            if len(vals) < MIN_BIN_N:
                continue
            raw.append({
                "pos_ecr_rank": r, "n": len(vals),
                "floor_ppr": quantile(vals, FLOOR_Q),
                "center_ppr": quantile(vals, CENTER_Q),
                "ceiling_ppr": quantile(vals, CEILING_Q),
            })
        if not raw:
            continue
        wts = [row["n"] for row in raw]
        smoothed = {q: _isotonic_decreasing([row[q] for row in raw], wts)
                    for q in ("floor_ppr", "center_ppr", "ceiling_ppr")}
        for i, row in enumerate(raw):
            floor = smoothed["floor_ppr"][i]
            center = max(smoothed["center_ppr"][i], floor)      # keep floor ≤ center ≤ ceiling
            ceiling = max(smoothed["ceiling_ppr"][i], center)
            out_frames.append({
                "position": pos, "pos_ecr_rank": row["pos_ecr_rank"],
                "floor_ppr": round(floor, 1), "center_ppr": round(center, 1),
                "ceiling_ppr": round(ceiling, 1), "n": row["n"],
            })
    return pl.DataFrame(out_frames).sort("position", "pos_ecr_rank")


def _available_seasons() -> list[int]:
    """Seasons with BOTH preseason ADP and realized nfl_stats — the fittable/holdout-able set."""
    adp_seasons = set(data_layer.read_adp_preseason()["season"].unique().to_list())
    available = sorted(s for s in adp_seasons if data_layer._nfl_stats_path(s).exists())
    if not available:
        raise RuntimeError("No season has both adp_preseason and nfl_stats — run the fetchers first.")
    return available


def compute(holdout: int | None = None) -> pl.DataFrame:
    """Fit the curve on every season that has BOTH preseason ADP and realized nfl_stats, holding out
    `holdout` (default = the latest such season, i.e. the freeze/target) so the anchor is leak-free.
    Provenance columns holdout_season / train_seasons ride on every row (the leak gate reads them)."""
    available = _available_seasons()
    if holdout is None:
        holdout = max(available)
    train = [s for s in available if s != holdout]
    if not train:
        raise RuntimeError(f"No training seasons left after holding out {holdout}.")

    pairs = _training_pairs(train)
    curve = _fit_curve(pairs).with_columns(
        pl.lit(holdout, dtype=pl.Int64).alias("holdout_season"),
    )
    curve = curve.with_columns(
        pl.Series("train_seasons", [sorted(train)] * curve.height, dtype=pl.List(pl.Int64)),
    )

    print(f"=== ADP points curve: train={train}  holdout={holdout}  "
          f"(pairs={pairs.height}; ranks fit to {MAX_RANK}, window ±{HALF_WINDOW}) ===")
    for pos in SKILL_POSITIONS:
        c = curve.filter(pl.col("position") == pos).sort("pos_ecr_rank")
        if not c.height:
            continue
        # Monotonicity sanity: center should fall as positional rank rises.
        centers = c["center_ppr"].to_list()
        inversions = sum(1 for a, b in zip(centers, centers[1:]) if b > a + 1e-9)
        print(f"  {pos}: ranks {c['pos_ecr_rank'].min()}..{c['pos_ecr_rank'].max()}  "
              f"center {centers[0]:.0f}→{centers[-1]:.0f}  (center inversions: {inversions})")
        print(c.head(3).select("pos_ecr_rank", "floor_ppr", "center_ppr", "ceiling_ppr", "n"))
    return curve


def run(holdout: int | None = None) -> None:
    if holdout is None:
        holdout = max(_available_seasons())
    curve = compute(holdout)
    data_layer.write_adp_points_curve(curve, holdout)
    print(f"  → snapshots/derived/adp_points_curve/holdout_{holdout}.parquet ({curve.height} rows)")


def run_all() -> None:
    """One leak-free curve per held-out target season — every season with both ADP and nfl_stats."""
    for s in _available_seasons():
        run(s)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fit the historical ADP rank→realized-points curve.")
    parser.add_argument("--holdout", type=int, default=None,
                        help="season to exclude from the fit (default = latest = the freeze/target)")
    parser.add_argument("--all", action="store_true",
                        help="write one curve per held-out season (every fittable season)")
    args = parser.parse_args()
    if args.all:
        run_all()
    else:
        run(args.holdout)
