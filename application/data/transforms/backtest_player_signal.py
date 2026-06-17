"""
Backtest the spike signal-quality read against the full-2025 answer key.

This is the gate the Phase 1 engine must clear before it ships live (Product
Roadmap): the repeatability read has to predict rest-of-season production *better
than a naive "recent points carry forward" baseline*. If it can't beat that baseline,
the engine isn't real yet.

It imports the SAME pure `_player_signal` function the production transform ships, so
what's validated here is exactly what serves the front end — no parallel re-derivation
that could drift.

Method (no peeking — the input window is strictly before the truth window):
  - INPUT  = recent weeks (default 1–4, the simulated freeze). Per player: games,
    per-game PPR points, per-game opportunity, per-game TD points; plus the league
    positional mean points-per-opportunity from the full NFL pool.
  - TRUTH  = rest-of-season weeks (default 5–18), per-game PPR points actually scored.
  - Two predictors of rest-of-season ppg are compared against truth:
      naive  = recent_ppg                (recent points carry forward)
      signal = expected_ppg              (opportunity × efficiency-regressed-to-mean)
  - Reported on the population with a real recent sample and a real rest sample.

Two verdicts:
  1. Predictive — does `signal` beat `naive` on MAE / RMSE / correlation?
  2. Decision-relevant — among HOT players (top-tercile recent ppg, which the naive
     read cannot tell apart), does the read's `spike` group regress more than the
     `sticky` group? This is the actual product question.

Usage:
    python backtest_player_signal.py --season 2025
    python backtest_player_signal.py --season 2025 --recent 1-6   # different freeze
"""

import argparse
import sys
from pathlib import Path

import polars as pl

_TRANSFORMS_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(_TRANSFORMS_DIR.parent))
sys.path.insert(0, str(_TRANSFORMS_DIR))
import data_layer
from compute_player_signal import (
    MIN_GAMES,
    POS_MEAN_MIN_OPP,
    SHRINK_K,
    SKILL_POSITIONS,
    SPIKE_BAND,
    STICKY_BAND,
    _player_signal,
    opportunity_expr,
)

MIN_REST_GAMES = 4  # a player needs a real rest-of-season sample to be a fair test point


def _agg(df: pl.DataFrame) -> pl.DataFrame:
    """Per-player recent aggregate from a raw nfl_stats slice (keyed on display name —
    the backtest validates the scoring math, not the roster plumbing)."""
    return (
        df.with_columns(opportunity_expr().alias("opp"))
        .group_by("player_display_name", "position")
        .agg(
            pl.len().alias("games"),
            pl.col("fantasy_points_ppr").sum().alias("pts_tot"),
            pl.col("opp").sum().alias("opp_tot"),
            (
                (pl.col("rushing_tds") + pl.col("receiving_tds")) * 6
                + pl.col("passing_tds") * 4
            ).sum().alias("td_pts_tot"),
        )
        .with_columns(
            (pl.col("pts_tot") / pl.col("games")).alias("ppg"),
            (pl.col("opp_tot") / pl.col("games")).alias("opp_g"),
            (pl.col("td_pts_tot") / pl.col("games")).alias("td_ppg"),
        )
    )


def _pos_mean_ppo(recent: pl.DataFrame) -> dict:
    """League positional mean points-per-opportunity, volume-weighted over players
    clearing the opportunity floor — identical rule to the production transform."""
    q = recent.filter(pl.col("opp_g") >= POS_MEAN_MIN_OPP)
    means = q.group_by("position").agg(
        (pl.col("pts_tot").sum() / pl.col("opp_tot").sum()).alias("mean_ppo")
    )
    return {r["position"]: float(r["mean_ppo"]) for r in means.iter_rows(named=True)}


def _mae(p, y):
    return float((p - y).abs().mean())


def _rmse(p, y):
    return float((p - y).pow(2).mean()) ** 0.5


def _corr(p, y):
    return float(pl.DataFrame({"p": p, "y": y}).select(pl.corr("p", "y")).item())


def run(season: int, recent_weeks, rest_weeks) -> bool:
    stats = data_layer.read_nfl_stats(season).filter(pl.col("position").is_in(SKILL_POSITIONS))
    stats = stats.with_columns(
        [
            pl.col(c).fill_null(0.0)
            for c in [
                "carries", "targets", "attempts", "fantasy_points_ppr",
                "rushing_tds", "receiving_tds", "passing_tds",
            ]
        ]
    )

    recent = _agg(stats.filter(pl.col("week").is_in(recent_weeks)))
    pos_mean = _pos_mean_ppo(recent)

    rest = (
        stats.filter(pl.col("week").is_in(rest_weeks))
        .group_by("player_display_name")
        .agg(pl.len().alias("rest_games"), pl.col("fantasy_points_ppr").mean().alias("rest_ppg"))
    )

    rows = []
    for r in recent.iter_rows(named=True):
        sig = _player_signal(
            {k: r[k] for k in ("position", "games", "ppg", "opp_g", "td_ppg")},
            pos_mean.get(r["position"], 0.0),
            shrink_k=SHRINK_K,
            min_games=MIN_GAMES,
            spike_band=SPIKE_BAND,
            sticky_band=STICKY_BAND,
        )
        rows.append({"player_display_name": r["player_display_name"], "position": r["position"], **sig})
    pred = pl.DataFrame(rows)

    df = (
        pred.join(rest, on="player_display_name", how="inner")
        .filter((pl.col("games") >= MIN_GAMES) & (pl.col("rest_games") >= MIN_REST_GAMES) & (pl.col("opp_g") > 0))
    )

    naive = df["recent_ppg"]
    signal = df["expected_ppg"]
    truth = df["rest_ppg"]

    print(f"=== Backtest: season={season}  input wks {recent_weeks[0]}–{recent_weeks[-1]}  "
          f"truth wks {rest_weeks[0]}–{rest_weeks[-1]}  (n={df.height}) ===")
    print(f"  positional mean pts/opp: " + ", ".join(f"{p} {v:.3f}" for p, v in sorted(pos_mean.items())))
    print()
    print(f"  {'predictor':<10}{'MAE':>8}{'RMSE':>8}{'corr':>8}")
    print(f"  {'naive':<10}{_mae(naive, truth):>8.3f}{_rmse(naive, truth):>8.3f}{_corr(naive, truth):>8.3f}")
    print(f"  {'signal':<10}{_mae(signal, truth):>8.3f}{_rmse(signal, truth):>8.3f}{_corr(signal, truth):>8.3f}")
    mae_gain = (_mae(naive, truth) - _mae(signal, truth)) / _mae(naive, truth) * 100
    print(f"  → signal cuts rest-of-season MAE by {mae_gain:.1f}% vs naive recent-points")

    # --- Decision-relevant test: hot players, spike vs sticky read ---
    hot = df.with_columns(
        (pl.col("recent_ppg") >= pl.col("recent_ppg").quantile(0.66).over("position")).alias("hot")
    ).filter(pl.col("hot"))
    spike = hot.filter(pl.col("read") == "spike")
    sticky = hot.filter(pl.col("read") == "sticky")

    def line(name, g):
        if g.height == 0:
            return f"  {name:<8} n=0"
        chg = float((g["rest_ppg"] - g["recent_ppg"]).mean())
        return (f"  {name:<8} n={g.height:<3} recent {g['recent_ppg'].mean():5.2f} → "
                f"rest {g['rest_ppg'].mean():5.2f}  (chg {chg:+5.2f})  td_share {g['td_share'].mean():.2f}")

    print("\n  Hot players (top-tercile recent ppg — naive treats these alike):")
    print(line("spike", spike))
    print(line("sticky", sticky))

    print("\n  Spike reads the manager would be warned on (largest regression risk):")
    for r in spike.sort("regression_risk", descending=True).head(6).iter_rows(named=True):
        print(f"    {r['player_display_name']:<22}{r['position']:<3} recent {r['recent_ppg']:5.1f} → "
              f"rest {r['rest_ppg']:5.1f}  risk {r['regression_risk']:.2f}  td_share {r['td_share']:.2f}")

    # --- Verdict ---
    passed = _mae(signal, truth) < _mae(naive, truth)
    spike_regresses_more = (
        spike.height > 0 and sticky.height > 0
        and float((spike["rest_ppg"] - spike["recent_ppg"]).mean())
        < float((sticky["rest_ppg"] - sticky["recent_ppg"]).mean())
    )
    print()
    print(f"  VERDICT: predictive {'PASS' if passed else 'FAIL'} "
          f"(signal {'beats' if passed else 'does NOT beat'} naive on MAE); "
          f"decision-relevant {'PASS' if spike_regresses_more else 'FAIL'} "
          f"(spike group regresses {'more' if spike_regresses_more else 'NOT more'} than sticky).")
    return passed and spike_regresses_more


def _parse_weeks(spec: str):
    lo, hi = (int(x) for x in spec.split("-"))
    return list(range(lo, hi + 1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest the player signal vs naive recent-points.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--recent", default="1-4", help="input week range, e.g. 1-4")
    parser.add_argument("--rest", default=None, help="truth week range, e.g. 5-18 (default: after recent)")
    args = parser.parse_args()
    recent = _parse_weeks(args.recent)
    rest = _parse_weeks(args.rest) if args.rest else list(range(recent[-1] + 1, 19))
    ok = run(args.season, recent, rest)
    sys.exit(0 if ok else 1)
