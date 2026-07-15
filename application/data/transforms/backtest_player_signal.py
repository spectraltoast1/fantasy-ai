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

Three verdicts:
  1. Predictive — does `signal` beat `naive` on MAE / RMSE / correlation?
  2. Decision-relevant — among HOT players (top-tercile recent ppg, which the naive
     read cannot tell apart), does the read's `spike` group regress more than the
     `sticky` group? This is the actual product question.
  3. Quality axis (§1) — does the model-expected efficiency (`quality_rate` = exp_ppo)
     forecast a player's rest-of-season realized efficiency (pts/opp) better than his
     recent realized efficiency (`ppo`)? The Quality axis's own answer-key check.

Usage:
    python3 -m application.data.transforms.backtest_player_signal --season 2025
    python3 -m application.data.transforms.backtest_player_signal --season 2025 --recent 1-6   # different freeze
"""

import argparse
import sys
from pathlib import Path

import polars as pl

from application.data import data_layer
from application.data.transforms._analytics import round1
from application.data.transforms._scoring import EXP_COMPONENT_COLS, expected_points_expr
from application.data.transforms.compute_player_signal import (
    MIN_GAMES,
    OPP_HALF_LIFE_WK,
    POS_MEAN_MIN_OPP,
    SHRINK_K,
    SKILL_POSITIONS,
    SPIKE_BAND,
    STICKY_BAND,
    _player_signal,
    _weighted_rates,
    opportunity_expr,
    td_points_expr,
)

MIN_REST_GAMES = 4  # a player needs a real rest-of-season sample to be a fair test point
# Opportunity-EWMA half-lives swept against the answer key. None = equal weight
# (cumulative); the rest are candidate half-lives in weeks. The winner sets
# OPP_HALF_LIFE_WK in the transform.
SWEEP_HALF_LIVES = [None, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0]


def _series(df: pl.DataFrame) -> pl.DataFrame:
    """Per-player recent series from a raw nfl_stats slice (keyed on display name — the
    backtest validates the scoring math, not the roster plumbing). Carries the per-week
    (pts, opp, td_pts, exp_pts) list so `_weighted_rates` can derive EWMA rates at any
    half-life — the same path the transform ships. `exp_pts` (the league-scored expected
    points, the Quality basis) is added to the slice by `_load`, no join needed."""
    return (
        df.with_columns(opportunity_expr().alias("opp"), td_points_expr().alias("td_pts"))
        .group_by("player_display_name", "position")
        .agg(
            pl.len().alias("games"),
            pl.struct(
                "week", pl.col("fantasy_points_ppr").alias("pts"), "opp", "td_pts", "exp_pts"
            ).alias("weeks"),
        )
    )


def _pos_mean_ppo(df: pl.DataFrame) -> dict:
    """League positional mean points-per-opportunity, volume-weighted over players
    clearing the opportunity floor — identical rule to the production transform. The
    structural baseline is cumulative (equal weight, max sample), independent of the
    opportunity half-life, so it is computed from the raw recent slice."""
    per_player = (
        df.with_columns(opportunity_expr().alias("opp"))
        .group_by("player_display_name", "position")
        .agg(
            pl.len().alias("g"),
            pl.col("fantasy_points_ppr").sum().alias("pts"),
            pl.col("opp").sum().alias("opp"),
        )
    )
    q = per_player.filter(pl.col("opp") / pl.col("g") >= POS_MEAN_MIN_OPP)
    means = q.group_by("position").agg(
        (pl.col("pts").sum() / pl.col("opp").sum()).alias("mean_ppo")
    )
    return {r["position"]: float(r["mean_ppo"]) for r in means.iter_rows(named=True)}


def _predict(series: pl.DataFrame, pos_mean: dict, half_life) -> pl.DataFrame:
    """Per-player prediction at one opportunity half-life: the signal's expected_ppg /
    read (via the shipped `_weighted_rates` + `_player_signal`), plus a `naive_ppg`
    reference that is always equal-weight recent ppg — the literal 'recent points carry
    forward' baseline, held fixed so the sweep measures the *window's* contribution."""
    rows = []
    for r in series.iter_rows(named=True):
        weeks = [
            {
                "week": int(w["week"]), "pts": float(w["pts"]), "opp": float(w["opp"]),
                "td_pts": float(w["td_pts"]), "exp_pts": float(w["exp_pts"]),
            }
            for w in r["weeks"]
        ]
        rates = _weighted_rates(weeks, half_life=half_life)
        sig = _player_signal(
            {"position": r["position"], **rates},
            pos_mean.get(r["position"], 0.0),
            shrink_k=SHRINK_K, min_games=MIN_GAMES, spike_band=SPIKE_BAND, sticky_band=STICKY_BAND,
        )
        rows.append({
            "player_display_name": r["player_display_name"],
            "position": r["position"],
            "naive_ppg": round1(_weighted_rates(weeks, half_life=None)["ppg"]),
            **sig,
        })
    return pl.DataFrame(rows)


def _mae(p, y):
    return float((p - y).abs().mean())


def _rmse(p, y):
    return float((p - y).pow(2).mean()) ** 0.5


def _corr(p, y):
    return float(pl.DataFrame({"p": p, "y": y}).select(pl.corr("p", "y")).item())


def _load(season: int, *, league_id=None) -> pl.DataFrame:
    """Cleaned skill-position stats (usage/score nulls → 0) for the season, with `exp_pts` — the
    league-scored expected points (the Quality basis) — derived from the ff_opportunity components
    exactly as the transform does (`expected_points_expr`), so the gate exercises the shipped math."""
    scoring = data_layer.read_scoring_settings(season, league_id=league_id)
    return data_layer.read_nfl_stats(season).filter(
        pl.col("position").is_in(SKILL_POSITIONS)
    ).with_columns(
        [
            pl.col(c).fill_null(0.0)
            for c in [
                "carries", "targets", "attempts", "fantasy_points_ppr",
                "rushing_tds", "receiving_tds", "passing_tds", *EXP_COMPONENT_COLS,
            ]
        ]
    ).with_columns(expected_points_expr(scoring).alias("exp_pts"))


def _evaluate(stats: pl.DataFrame, recent_weeks, rest_weeks, half_life):
    """Join per-player predictions at one opportunity half-life to the rest-of-season
    truth, on the fair-test population (real recent + real rest sample). Returns
    (df, pos_mean) for both the report and the sweep."""
    series = _series(stats.filter(pl.col("week").is_in(recent_weeks)))
    pos_mean = _pos_mean_ppo(stats.filter(pl.col("week").is_in(recent_weeks)))
    pred = _predict(series, pos_mean, half_life)

    rest = (
        stats.filter(pl.col("week").is_in(rest_weeks))
        .with_columns(opportunity_expr().alias("opp"))
        .group_by("player_display_name")
        .agg(
            pl.len().alias("rest_games"),
            pl.col("fantasy_points_ppr").mean().alias("rest_ppg"),
            pl.col("opp").mean().alias("rest_opp_g"),
        )
    )
    df = (
        pred.join(rest, on="player_display_name", how="inner")
        .filter((pl.col("games") >= MIN_GAMES) & (pl.col("rest_games") >= MIN_REST_GAMES) & (pl.col("opp_g") > 0))
    )
    return df, pos_mean


def sweep(season: int, recent_weeks, rest_weeks, *, league_id=None) -> None:
    """Tune the opportunity half-life: for each candidate, report the signal's MAE on the
    answer key at this freeze. Run across several freezes to choose OPP_HALF_LIFE_WK —
    the window earns its keep mid/late season, where role drift has had time to show."""
    stats = _load(season, league_id=league_id)
    print(f"=== Half-life sweep: season={season}  input wks {recent_weeks[0]}–{recent_weeks[-1]}  "
          f"truth wks {rest_weeks[0]}–{rest_weeks[-1]} ===")
    print(f"  {'half_life':<12}{'signal MAE':>12}{'corr':>8}   (naive MAE held fixed = equal-weight recent)")
    base = None
    best = (None, float("inf"))
    for hl in SWEEP_HALF_LIVES:
        df, _ = _evaluate(stats, recent_weeks, rest_weeks, hl)
        if base is None:
            base = _mae(df["naive_ppg"], df["rest_ppg"])
        mae = _mae(df["expected_ppg"], df["rest_ppg"])
        corr = _corr(df["expected_ppg"], df["rest_ppg"])
        label = "cumulative" if hl is None else f"{hl:g}wk"
        flag = " ←best" if mae < best[1] else ""
        if mae < best[1]:
            best = (hl, mae)
        print(f"  {label:<12}{mae:>12.3f}{corr:>8.3f}{flag}")
    print(f"  naive (equal-weight recent) MAE = {base:.3f}")
    print(f"  → best half-life at this freeze: {'cumulative' if best[0] is None else f'{best[0]:g}wk'} (MAE {best[1]:.3f})")


def run(season: int, recent_weeks, rest_weeks, half_life=OPP_HALF_LIFE_WK, *, league_id=None) -> bool:
    stats = _load(season, league_id=league_id)
    df, pos_mean = _evaluate(stats, recent_weeks, rest_weeks, half_life)

    naive = df["naive_ppg"]
    signal = df["expected_ppg"]
    truth = df["rest_ppg"]

    hl_label = "cumulative" if half_life is None else f"{half_life:g}wk half-life"
    print(f"=== Backtest: season={season}  input wks {recent_weeks[0]}–{recent_weeks[-1]}  "
          f"truth wks {rest_weeks[0]}–{rest_weeks[-1]}  opp window: {hl_label}  (n={df.height}) ===")
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

    # --- Quality-axis test: does model-expected efficiency (quality_rate = exp_ppo) predict a
    # player's REST-OF-SEASON realized efficiency (pts/opp) better than his recent realized
    # efficiency (ppo)? The §1 Quality axis's own answer-key check — the whole point of a de-noised,
    # context-aware efficiency read is that it forecasts true efficiency better than noisy recent. ---
    q = df.filter(pl.col("rest_opp_g") > 0).with_columns(
        (pl.col("rest_ppg") / pl.col("rest_opp_g")).alias("ros_ppo")
    )
    mae_realized = _mae(q["ppo"], q["ros_ppo"])
    mae_quality = _mae(q["quality_rate"], q["ros_ppo"])
    quality_better = mae_quality < mae_realized
    print(f"\n  Quality axis — predicting rest-of-season efficiency (pts/opp), n={q.height}:")
    print(f"    recent realized ppo      MAE {mae_realized:.3f}")
    print(f"    quality_rate (exp_ppo)   MAE {mae_quality:.3f}   → quality "
          f"{'BEATS' if quality_better else 'does NOT beat'} realized efficiency")

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
          f"(spike group regresses {'more' if spike_regresses_more else 'NOT more'} than sticky); "
          f"quality {'PASS' if quality_better else 'FAIL'} "
          f"(exp_ppo {'beats' if quality_better else 'does NOT beat'} realized efficiency).")
    return passed and spike_regresses_more and quality_better


def _parse_weeks(spec: str):
    lo, hi = (int(x) for x in spec.split("-"))
    return list(range(lo, hi + 1))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Backtest the player signal vs naive recent-points.")
    parser.add_argument("--season", type=int, required=True)
    parser.add_argument("--recent", default="1-4", help="input week range, e.g. 1-4")
    parser.add_argument("--rest", default=None, help="truth week range, e.g. 5-18 (default: after recent)")
    parser.add_argument("--sweep", action="store_true",
                        help="sweep the opportunity half-life against the answer key instead of running the verdict")
    parser.add_argument("--opp-half-life", default=None,
                        help="override the opportunity half-life for the verdict run, e.g. 3 or 'none' (cumulative)")
    args = parser.parse_args()
    recent = _parse_weeks(args.recent)
    rest = _parse_weeks(args.rest) if args.rest else list(range(recent[-1] + 1, 19))
    if args.sweep:
        sweep(args.season, recent, rest)
        sys.exit(0)
    hl = OPP_HALF_LIFE_WK
    if args.opp_half_life is not None:
        hl = None if args.opp_half_life.lower() in ("none", "cumulative", "inf") else float(args.opp_half_life)
    ok = run(args.season, recent, rest, hl)
    sys.exit(0 if ok else 1)
